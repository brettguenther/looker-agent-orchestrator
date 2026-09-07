# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Serve the reasoning_engine ``{class_method, input}`` contract over HTTP.

Exists to guarantee support for the Vertex AI Console Playground and Gemini
Enterprise (via ADK registration), which both invoke the engine through this
contract. Agent Engine forwards calls to ``/api/reasoning_engine`` (sync) and
``/api/stream_reasoning_engine`` (streaming); dispatch is limited to the
:class:`AdkApp` ``register_operations()`` methods so the wire output matches a
packaged Agent Engine.
"""

import base64
import inspect
import json
import logging
import uuid

from fastapi import FastAPI, HTTPException, Request, encoders, responses
from vertexai.agent_engines.templates.adk import AdkApp

from app.app_utils import services

logger = logging.getLogger(__name__)


def _no_op_instrumentor_builder(project_id: str) -> None:
    """No-op so set_up() keeps the startup instrumentor and generate_content spans."""
    return None


def attach_reasoning_engine_routes(app: FastAPI) -> None:
    """Register reasoning_engine routes that dispatch to an AdkApp."""
    runtime: AdkApp | None = None
    streaming_methods: set[str] = set()
    sync_methods: set[str] = set()

    def get_runtime() -> AdkApp:
        nonlocal runtime, streaming_methods, sync_methods
        if runtime is None:
            from app.agent import app as adk_app

            # Reuse the process-wide services so sessions created here are
            # visible to the adk_api and A2A paths, and vice versa (see services.py).
            runtime = AdkApp(
                app=adk_app,
                session_service_builder=services.get_session_service,
                artifact_service_builder=services.get_artifact_service,
                instrumentor_builder=_no_op_instrumentor_builder,
            )
            runtime.set_up()
            operations = runtime.register_operations()
            streaming_methods = set(operations.get("stream", [])) | set(
                operations.get("async_stream", [])
            )
            sync_methods = set(operations.get("", [])) | set(
                operations.get("async", [])
            )
        return runtime

    def resolve_method(class_method: str, *, streaming: bool):
        rt = get_runtime()
        allowed = streaming_methods if streaming else sync_methods
        if class_method not in allowed:
            raise HTTPException(
                status_code=404,
                detail=f"Unsupported reasoning_engine method: {class_method!r}",
            )
        return getattr(rt, class_method)

    @app.post("/api/stream_reasoning_engine")
    async def stream_query(request: Request) -> responses.StreamingResponse:
        body = await request.json()
        requested_method = body.get("class_method")
        if requested_method:
            method = resolve_method(requested_method, streaming=True)
        else:
            rt = get_runtime()
            if hasattr(rt, "async_stream_query"):
                method = getattr(rt, "async_stream_query")
            else:
                method = resolve_method("stream_query", streaming=True)

        kwargs = (
            body.get("input")
            if "input" in body and isinstance(body.get("input"), dict)
            else {k: v for k, v in body.items() if k != "class_method"}
        )
        if not isinstance(kwargs, dict):
            kwargs = {}

        sig = inspect.signature(method)
        if "user_id" in sig.parameters and ("user_id" not in kwargs or not kwargs["user_id"]):
            kwargs["user_id"] = "end_user"

        session_id = kwargs.get("session_id")
        user_id = kwargs.get("user_id", "end_user")
        if "request_json" in kwargs:
            try:
                parsed_req = json.loads(kwargs["request_json"])
                session_id = parsed_req.get("session_id") or session_id
                user_id = parsed_req.get("user_id") or user_id
            except Exception:
                pass

        async def generator():
            emitted_a2ui: set[str] = set()

            res = method(**kwargs)
            if inspect.isasyncgen(res) or hasattr(res, "__aiter__"):
                async for event in res:
                    if isinstance(event, dict):
                        content = event.get("content") or {}
                        parts = content.get("parts") or []
                        for p in parts:
                            if isinstance(p, dict):
                                inline = p.get("inlineData") or p.get("inline_data") or {}
                                if inline.get("mimeType") in ("application/json+a2ui", "application/a2ui+json"):
                                    emitted_a2ui.add(str(inline.get("data")))
                    yield json.dumps(event) + "\n"
            else:
                for event in res:
                    if isinstance(event, dict):
                        content = event.get("content") or {}
                        parts = content.get("parts") or []
                        for p in parts:
                            if isinstance(p, dict):
                                inline = p.get("inlineData") or p.get("inline_data") or {}
                                if inline.get("mimeType") in ("application/json+a2ui", "application/a2ui+json"):
                                    emitted_a2ui.add(str(inline.get("data")))
                    yield json.dumps(event) + "\n"

            # Check if any A2UI components were captured during tool execution
            from app.a2ui_builder import pop_a2ui_surfaces, wrap_a2ui_datapart_envelope
            pending_surfaces = pop_a2ui_surfaces()
            for surface_messages in pending_surfaces:
                messages_to_emit = surface_messages if isinstance(surface_messages, list) else [surface_messages]
                parts = []
                for msg in messages_to_emit:
                    msg_str = json.dumps(msg)
                    if msg_str not in emitted_a2ui:
                        emitted_a2ui.add(msg_str)
                        payload = wrap_a2ui_datapart_envelope(msg)
                        b64_data = base64.b64encode(payload.encode("utf-8")).decode("utf-8")
                        parts.append({
                            "inlineData": {
                                "mimeType": "text/plain",
                                "data": b64_data,
                            }
                        })
                if parts:
                    if requested_method == "streaming_agent_run_with_events":
                        a2ui_event = {
                            "events": [
                                {
                                    "author": "looker_orchestrator",
                                    "content": {
                                        "role": "model",
                                        "parts": parts,
                                    },
                                    "id": str(uuid.uuid4()),
                                    "invocation_id": "",
                                }
                            ],
                            "session_id": session_id,
                        }
                    else:
                        a2ui_event = {
                            "author": "agent",
                            "content": {
                                "role": "model",
                                "parts": parts,
                            },
                        }
                    yield json.dumps(a2ui_event) + "\n"

        return responses.StreamingResponse(
            content=generator(), media_type="application/json"
        )

    @app.post("/api/reasoning_engine")
    async def query(request: Request) -> responses.JSONResponse:
        body = await request.json()
        requested_method = body.get("class_method")
        if requested_method:
            method = resolve_method(requested_method, streaming=False)
        else:
            rt = get_runtime()
            method = getattr(rt, "get_session", None) or resolve_method(
                "get_session", streaming=False
            )

        kwargs = (
            body.get("input")
            if "input" in body and isinstance(body.get("input"), dict)
            else {k: v for k, v in body.items() if k != "class_method"}
        )
        if not isinstance(kwargs, dict):
            kwargs = {}

        sig = inspect.signature(method)
        if "user_id" in sig.parameters and ("user_id" not in kwargs or not kwargs["user_id"]):
            kwargs["user_id"] = "end_user"

        output = (
            await method(**kwargs)
            if inspect.iscoroutinefunction(method)
            else method(**kwargs)
        )
        return responses.JSONResponse(
            content=encoders.jsonable_encoder({"output": output})
        )
