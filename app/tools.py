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

"""Analytical tools connecting the orchestrator to Looker via Gemini Data Analytics."""

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

import google.auth
import google.auth.transport.requests
import httpx
from google.adk.tools import ToolContext

from config.settings import settings
from app.auth import resolve_looker_token
from app.a2ui_builder import (
    record_a2ui_surface,
    build_analytics_surface,
    extract_vega_spec,
    extract_datagrid,
    A2UI_MIME_TYPE,
)

logger = logging.getLogger(__name__)


def _get_gcp_bearer_token() -> str:
    """Acquires a valid Google Cloud IAM access token using application default credentials."""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    return creds.token


async def _invoke_gda_data_agent(
    agent_name: str,
    agent_resource: str,
    query: str,
    looker_token: str,
    timeout_secs: float = 90.0,
) -> str:
    """Executes a query directly against the Gemini Data Analytics DataA2AService endpoint.

    Bypasses the Looker web proxy to receive native A2UI v0.9 VegaChart and DataGrid components.
    Authenticates via Google Cloud IAM bearer tokens and injects the end-user Looker OAuth
    token via the Google A2A authorizations extension header and metadata.
    """
    try:
        gcp_token = await asyncio.to_thread(_get_gcp_bearer_token)
    except Exception as e:
        logger.error(f"Failed to acquire GCP IAM credentials: {e}")
        return f"Authentication error: Failed to obtain Google Cloud IAM credentials ({e})."

    url = f"https://geminidataanalytics.googleapis.com/v1/a2a/{agent_resource}/v1/message:stream"
    headers = {
        "Authorization": f"Bearer {gcp_token}",
        "Content-Type": "application/json",
        "X-A2A-Extensions": "https://www.googleapis.com/gemini-enterprise/a2a/extensions/authorizations/v1,https://a2ui.org/a2a-extension/a2ui/v0.9",
        "Accept": "application/json",
    }

    body = {
        "message": {
            "messageId": f"msg_{uuid.uuid4().hex[:12]}",
            "role": "ROLE_USER",
            "content": [{"text": query}],
        },
        "configuration": {
            "acceptedOutputModes": ["text/plain", A2UI_MIME_TYPE],
        },
        "metadata": {
            "https://www.googleapis.com/gemini-enterprise/a2a/extensions/authorizations/v1": {
                "looker_auth": {
                    "access_token": looker_token,
                }
            }
        },
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_secs) as http_client:
            resp = await http_client.post(url, headers=headers, json=body)
            if resp.status_code == 200:
                events = resp.json()
                if not isinstance(events, list):
                    events = [events]

                narrative_texts: List[str] = []
                vega_spec: Optional[Dict[str, Any]] = None
                data_grid: Optional[Dict[str, Any]] = None
                failure_msg: Optional[str] = None

                for item in events:
                    if not isinstance(item, dict):
                        continue

                    # Check for task failure
                    if "statusUpdate" in item:
                        status = item["statusUpdate"].get("status", {})
                        if status.get("state") == "TASK_STATE_FAILED":
                            msg = status.get("message", {})
                            err_content = [
                                p["text"] for p in msg.get("content", [])
                                if isinstance(p, dict) and p.get("text")
                            ]
                            failure_msg = "".join(err_content).strip() or "Task failed in Gemini Data Analytics service."

                    # Check for artifact updates
                    if "artifactUpdate" in item:
                        art = item["artifactUpdate"].get("artifact", {})
                        art_name = art.get("name", "")
                        parts = art.get("parts", [])

                        # 1. Native VegaChart specification
                        spec = extract_vega_spec(parts=parts)
                        if spec:
                            vega_spec = spec

                        # 2. Native DataGrid data
                        grid = extract_datagrid(parts=parts)
                        if grid:
                            data_grid = grid

                        # 3. Narrative text parts
                        for p in parts:
                            if isinstance(p, dict) and p.get("text"):
                                if art_name == "Final response":
                                    narrative_texts.append(p["text"])
                                elif not narrative_texts and art_name != "Data result":
                                    narrative_texts.append(p["text"])

                if failure_msg:
                    logger.error(f"Gemini Data Analytics error for {agent_name}: {failure_msg}")
                    if "Requires authentication" in failure_msg or "UNAUTHENTICATED" in failure_msg:
                        return f"Looker authentication expired or invalid. Please re-authenticate your Looker account: {failure_msg}"
                    return f"Error from {agent_name}: {failure_msg}"

                # Render native A2UI surface (VegaChart, MaterialTable, or combined card)
                if vega_spec or data_grid:
                    title = (vega_spec.get("title") if vega_spec else None) or f"{agent_name}: {query.strip().capitalize()}"
                    surface = build_analytics_surface(
                        title=str(title),
                        spec=vega_spec,
                        datagrid=data_grid,
                    )
                    record_a2ui_surface(surface)

                result_text = "".join(narrative_texts).strip()
                return result_text or f"Successfully queried {agent_name}."

            elif resp.status_code in (401, 403):
                logger.error(f"GDA invocation returned HTTP {resp.status_code}: {resp.text}")
                return f"Authentication error accessing Gemini Data Analytics (HTTP {resp.status_code}). Please verify IAM and Looker permissions."
            else:
                logger.error(f"GDA invocation returned HTTP {resp.status_code}: {resp.text}")
                return f"Error querying {agent_name} (HTTP {resp.status_code}): {resp.text}"

    except Exception as e:
        logger.exception(f"Unexpected error invoking Gemini Data Analytics agent {agent_name}: {e}")
        return f"Error executing query against {agent_name}: {e}"


async def query_domain_agent_1(query: str, tool_context: ToolContext) -> str:
    """Queries the primary Looker domain agent for analytical metrics and business data.

    Args:
        query: The business question regarding primary domain data.
        tool_context: The ADK tool context containing session and OAuth state.
    """
    token = resolve_looker_token(tool_context)
    if not token:
        return "Authentication error: Looker user access token is not available in context. Please connect your Looker account."

    logger.info(f"Routing query to {settings.looker_agent_1_name} ({settings.looker_agent_1_resource})...")
    return await _invoke_gda_data_agent(
        agent_name=settings.looker_agent_1_name,
        agent_resource=settings.looker_agent_1_resource,
        query=query,
        looker_token=token,
    )


async def query_domain_agent_2(query: str, tool_context: ToolContext) -> str:
    """Queries the secondary Looker domain agent for analytical metrics and business data.

    Args:
        query: The business question regarding secondary domain data.
        tool_context: The ADK tool context containing session and OAuth state.
    """
    token = resolve_looker_token(tool_context)
    if not token:
        return "Authentication error: Looker user access token is not available in context. Please connect your Looker account."

    logger.info(f"Routing query to {settings.looker_agent_2_name} ({settings.looker_agent_2_resource})...")
    return await _invoke_gda_data_agent(
        agent_name=settings.looker_agent_2_name,
        agent_resource=settings.looker_agent_2_resource,
        query=query,
        looker_token=token,
    )


# Dynamically set tool docstrings based on configured domain agent definitions
query_domain_agent_1.__doc__ = f"""Queries {settings.looker_agent_1_name} for analytical metrics and business data. {settings.looker_agent_1_description}

Args:
    query: The business question regarding {settings.looker_agent_1_name} data.
    tool_context: The ADK tool context containing session and OAuth state.
"""

query_domain_agent_2.__doc__ = f"""Queries {settings.looker_agent_2_name} for analytical metrics and business data. {settings.looker_agent_2_description}

Args:
    query: The business question regarding {settings.looker_agent_2_name} data.
    tool_context: The ADK tool context containing session and OAuth state.
"""

# Backward compatibility aliases
query_ecommerce_sales_agent = query_domain_agent_1
query_ecomm_site_traffic_agent = query_domain_agent_2
