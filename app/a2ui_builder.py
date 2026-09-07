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

"""A2UI v0.9 declarative UI builder for Gemini Enterprise.

Constructs schema-compliant A2UI surfaces containing interactive VegaChart
visualizations and MaterialTable data tables emitted by Gemini Data Analytics.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

A2UI_V0_9_EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v0.9"
GEMINI_ENTERPRISE_COMPOSITE_CATALOG_ID = (
    "https://www.gstatic.com/vertexaisearch/a2ui/v0_9/gemini_enterprise_composite_catalog.json"
)
A2UI_MIME_TYPE = "application/json+a2ui"
A2A_DATAPART_START_TAG = "<a2a_datapart_json>"
A2A_DATAPART_END_TAG = "</a2a_datapart_json>"

# In-memory queue for passing generated A2UI surfaces from tool execution to streaming generator
_PENDING_SURFACES: List[List[Dict[str, Any]]] = []


def wrap_a2ui_datapart_envelope(message: Dict[str, Any]) -> str:
    """Wraps an A2UI message in the <a2a_datapart_json> envelope required by Dolphin and Assistant Server.

    In Gemini Enterprise Discovery Engine / Dolphin, raw inlineData parts are converted to
    GCS file uploads and rendered as file attachments unless wrapped in <a2a_datapart_json>
    with mime_type text/plain (b/487311358). Assistant Server's ui_event_utils unwrap this
    envelope and route the inner application/json+a2ui payload to the UCS widget renderer.
    """
    envelope = {
        "data": message,
        "metadata": {
            "mimeType": A2UI_MIME_TYPE,
        },
    }
    return f"{A2A_DATAPART_START_TAG}{json.dumps(envelope)}{A2A_DATAPART_END_TAG}"


def record_a2ui_surface(surface_messages: List[Dict[str, Any]]) -> None:
    """Registers an A2UI declarative message sequence to be emitted during streaming."""
    if surface_messages:
        _PENDING_SURFACES.append(surface_messages)
        logger.info(f"Recorded A2UI surface with {len(surface_messages)} message(s). Total pending: {len(_PENDING_SURFACES)}")


def pop_a2ui_surfaces() -> List[List[Dict[str, Any]]]:
    """Retrieves and clears all pending A2UI surfaces."""
    global _PENDING_SURFACES
    surfaces = list(_PENDING_SURFACES)
    _PENDING_SURFACES.clear()
    return surfaces


def _format_cell_value(val: Any) -> str:
    """Formats cell values to strings per the Gemini Enterprise composite catalog schema.

    MaterialTable.rows enforces: additionalProperties: {"type": "string"}.
    All cell values must be string-formatted to pass schema validation in the UCS widget.
    """
    if val is None:
        return ""
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, float):
        if val.is_integer():
            return f"{int(val):,}"
        return f"{val:,.2f}"
    if isinstance(val, int):
        if 1900 <= val <= 2100:
            return str(val)
        return f"{val:,}"
    return str(val)


def generate_surface_id(prefix: str = "surface") -> str:
    """Generates a unique surface ID for isolating multi-turn chat turns."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def build_a2ui_surface(
    components: List[Dict[str, Any]],
    data_model: Optional[Dict[str, Any]] = None,
    surface_id: Optional[str] = None,
    catalog_id: str = GEMINI_ENTERPRISE_COMPOSITE_CATALOG_ID,
) -> List[Dict[str, Any]]:
    """Builds a complete A2UI v0.9 declarative message sequence for Gemini Enterprise."""
    effective_surface_id = surface_id or generate_surface_id()
    messages: List[Dict[str, Any]] = [
        {
            "version": "v0.9",
            "createSurface": {
                "surfaceId": effective_surface_id,
                "catalogId": catalog_id,
            }
        }
    ]
    if data_model:
        messages.append({
            "version": "v0.9",
            "updateDataModel": {
                "surfaceId": effective_surface_id,
                "path": "/",
                "value": data_model,
            }
        })
    messages.append({
        "version": "v0.9",
        "updateComponents": {
            "surfaceId": effective_surface_id,
            "components": components,
        }
    })
    return messages


def build_material_table_surface(
    columns: List[Dict[str, str]],
    rows: List[Dict[str, Any]],
    title: Optional[str] = None,
    surface_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Constructs an A2UI v0.9 MaterialTable component surface."""
    string_rows = [
        {str(k): _format_cell_value(v) for k, v in r.items()}
        for r in rows
    ]
    table_id = "table_1"
    child_ids = [table_id]
    components: List[Dict[str, Any]] = []

    if title:
        components.append({
            "id": "title_1",
            "component": "MaterialText",
            "text": title,
            "usageHint": "h3",
        })
        child_ids.insert(0, "title_1")

    components.append({
        "id": table_id,
        "component": "MaterialTable",
        "columns": columns,
        "rows": string_rows,
    })

    root_component = {
        "id": "root",
        "component": "MaterialCard",
        "children": child_ids,
    }
    return build_a2ui_surface(
        [root_component, *components],
        data_model={"rows": string_rows},
        surface_id=surface_id,
    )


def build_vega_chart_surface(
    spec: Dict[str, Any],
    height: int = 290,
    title: Optional[str] = None,
    surface_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Constructs an A2UI v0.9 VegaChart component surface."""
    chart_id = "chart_1"
    child_ids = [chart_id]
    components: List[Dict[str, Any]] = []

    if title:
        components.append({
            "id": "title_1",
            "component": "MaterialText",
            "text": title,
            "usageHint": "h3",
        })
        child_ids.insert(0, "title_1")

    components.append({
        "id": chart_id,
        "component": "VegaChart",
        "spec": spec,
        "height": height,
    })

    root_component = {
        "id": "root",
        "component": "MaterialCard",
        "children": child_ids,
    }
    return build_a2ui_surface(
        [root_component, *components],
        surface_id=surface_id,
    )


def build_analytics_surface(
    title: str,
    spec: Optional[Dict[str, Any]] = None,
    datagrid: Optional[Dict[str, Any]] = None,
    height: int = 290,
    surface_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Constructs a unified A2UI v0.9 surface containing a VegaChart, MaterialTable, or both.

    Renders all components inside a single MaterialCard container separated by a
    MaterialDivider to prevent surface overwrite collisions in Gemini Enterprise.
    """
    child_ids: List[str] = []
    components: List[Dict[str, Any]] = []
    data_model: Optional[Dict[str, Any]] = None

    if title:
        child_ids.append("title_1")
        components.append({
            "id": "title_1",
            "component": "MaterialText",
            "text": title,
            "usageHint": "h3",
        })

    if spec:
        child_ids.append("chart_1")
        components.append({
            "id": "chart_1",
            "component": "VegaChart",
            "spec": spec,
            "height": height,
        })

    if spec and datagrid:
        child_ids.append("divider_1")
        components.append({
            "id": "divider_1",
            "component": "MaterialDivider",
        })

    if datagrid:
        fields = datagrid.get("schema", {}).get("fields", [])
        columns = [
            {"header": f.get("display_name") or f.get("name", "Column"), "field": f.get("name", "")}
            for f in fields
        ]
        raw_rows = datagrid.get("rowData", [])
        string_rows = [
            {str(k): _format_cell_value(v) for k, v in r.items()}
            for r in raw_rows
        ]
        data_model = {"rows": string_rows}
        child_ids.append("table_1")
        components.append({
            "id": "table_1",
            "component": "MaterialTable",
            "columns": columns,
            "rows": string_rows,
        })

    root_component = {
        "id": "root",
        "component": "MaterialCard",
        "children": child_ids,
    }
    return build_a2ui_surface(
        [root_component, *components],
        data_model=data_model,
        surface_id=surface_id,
    )


def extract_vega_spec(parts: Optional[List[Any]] = None) -> Optional[Dict[str, Any]]:
    """Extracts native Looker Vega-Lite chart specifications from GDA artifact parts."""
    if not parts:
        return None
    for p in parts:
        if not isinstance(p, dict):
            continue
        # Direct vegaConfig / spec attributes
        for key in ("vegaConfig", "vega_config", "spec", "chart"):
            val = p.get(key)
            if isinstance(val, dict) and any(k in val for k in ("mark", "encoding", "$schema")):
                return val
            if isinstance(val, str) and "mark" in val:
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, dict) and any(k in parsed for k in ("mark", "encoding", "$schema")):
                        return parsed
                except Exception:
                    pass

        # Nested in GDA data payload
        data_val = p.get("data")
        if isinstance(data_val, dict):
            inner = data_val.get("data", data_val)
            if isinstance(inner, dict):
                surface_update = inner.get("surfaceUpdate", {})
                for comp_entry in surface_update.get("components", []):
                    comp = comp_entry.get("component", {})
                    if isinstance(comp, dict):
                        vega_obj = comp.get("VegaChart", {})
                        if isinstance(vega_obj, dict) and "spec" in vega_obj:
                            return vega_obj["spec"]

            for key in ("vegaConfig", "vega_config", "spec", "chart"):
                val = data_val.get(key)
                if isinstance(val, dict) and any(k in val for k in ("mark", "encoding", "$schema")):
                    return val
                if isinstance(val, str) and "mark" in val:
                    try:
                        parsed = json.loads(val)
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        pass
            if any(k in data_val for k in ("mark", "encoding", "$schema")):
                return data_val

    return None


def extract_datagrid(parts: Optional[List[Any]] = None) -> Optional[Dict[str, Any]]:
    """Extracts native DataGrid data from GDA artifact parts."""
    if not parts:
        return None
    for p in parts:
        if not isinstance(p, dict):
            continue
        data_val = p.get("data")
        if isinstance(data_val, dict):
            inner = data_val.get("data", data_val)
            if isinstance(inner, dict):
                surface_update = inner.get("surfaceUpdate", {})
                for comp_entry in surface_update.get("components", []):
                    comp = comp_entry.get("component", {})
                    if isinstance(comp, dict) and "DataGrid" in comp:
                        return comp["DataGrid"]
    return None
