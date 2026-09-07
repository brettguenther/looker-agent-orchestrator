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

import json
import unittest
from app.a2ui_builder import (
    GEMINI_ENTERPRISE_COMPOSITE_CATALOG_ID,
    A2UI_V0_9_EXTENSION_URI,
    A2UI_MIME_TYPE,
    A2A_DATAPART_START_TAG,
    A2A_DATAPART_END_TAG,
    record_a2ui_surface,
    pop_a2ui_surfaces,
    wrap_a2ui_datapart_envelope,
    build_material_table_surface,
    build_vega_chart_surface,
    build_analytics_surface,
    extract_vega_spec,
    extract_datagrid,
)


class TestA2UIBuilder(unittest.TestCase):

    def test_constants(self):
        self.assertEqual(A2UI_MIME_TYPE, "application/json+a2ui")
        self.assertEqual(A2UI_V0_9_EXTENSION_URI, "https://a2ui.org/a2a-extension/a2ui/v0.9")
        self.assertEqual(
            GEMINI_ENTERPRISE_COMPOSITE_CATALOG_ID,
            "https://www.gstatic.com/vertexaisearch/a2ui/v0_9/gemini_enterprise_composite_catalog.json",
        )

    def test_record_and_pop_surfaces(self):
        dummy_surface = [{"createSurface": {"surfaceId": "test"}}]
        record_a2ui_surface(dummy_surface)
        popped = pop_a2ui_surfaces()
        self.assertEqual(len(popped), 1)
        self.assertEqual(popped[0], dummy_surface)
        self.assertEqual(len(pop_a2ui_surfaces()), 0)

    def test_a2a_datapart_envelope(self):
        msg = {"version": "v0.9", "createSurface": {"surfaceId": "s1"}}
        payload = wrap_a2ui_datapart_envelope(msg)
        self.assertTrue(payload.startswith(A2A_DATAPART_START_TAG))
        self.assertTrue(payload.endswith(A2A_DATAPART_END_TAG))

        inner_json_str = payload[len(A2A_DATAPART_START_TAG) : -len(A2A_DATAPART_END_TAG)]
        envelope_dict = json.loads(inner_json_str)
        self.assertIn("data", envelope_dict)
        self.assertEqual(envelope_dict["data"], msg)
        self.assertIn("metadata", envelope_dict)
        self.assertEqual(envelope_dict["metadata"]["mimeType"], "application/json+a2ui")

    def test_build_material_table_surface(self):
        cols = [{"header": "Brand", "field": "brand"}, {"header": "Revenue", "field": "revenue"}]
        rows = [{"brand": "Calvin Klein", "revenue": 69036.64}]
        surface = build_material_table_surface(columns=cols, rows=rows, title="Top Brands")

        self.assertEqual(len(surface), 3)
        self.assertEqual(surface[0]["version"], "v0.9")
        self.assertIn("createSurface", surface[0])
        self.assertEqual(
            surface[0]["createSurface"]["catalogId"],
            GEMINI_ENTERPRISE_COMPOSITE_CATALOG_ID,
        )
        self.assertIn("updateDataModel", surface[1])
        expected_rows = [{"brand": "Calvin Klein", "revenue": "69,036.64"}]
        self.assertEqual(surface[1]["updateDataModel"]["value"]["rows"], expected_rows)
        self.assertIn("updateComponents", surface[2])
        components = surface[2]["updateComponents"]["components"]
        root = components[0]
        self.assertEqual(root["id"], "root")
        self.assertEqual(root["component"], "MaterialCard")
        self.assertIn("table_1", root["children"])
        table_comp = next(c for c in components if c["id"] == "table_1")
        self.assertEqual(table_comp["rows"], expected_rows)
        # Verify all cell values are strictly strings (composite catalog schema constraint)
        for row in table_comp["rows"]:
            for k, v in row.items():
                self.assertIsInstance(v, str)

    def test_build_vega_chart_surface(self):
        spec = {"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "mark": "bar"}
        surface = build_vega_chart_surface(spec=spec, height=320, title="Revenue Chart")

        self.assertEqual(len(surface), 2)
        self.assertEqual(surface[0]["version"], "v0.9")
        self.assertIn("createSurface", surface[0])
        self.assertIn("updateComponents", surface[1])
        components = surface[1]["updateComponents"]["components"]
        root = components[0]
        self.assertEqual(root["component"], "MaterialCard")
        self.assertIn("chart_1", root["children"])

    def test_extract_vega_spec_from_part(self):
        spec_dict = {"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "mark": "bar", "encoding": {}}
        part1 = {"kind": "chart", "vegaConfig": spec_dict}
        self.assertEqual(extract_vega_spec(parts=[part1]), spec_dict)

        part2 = {"kind": "data", "data": {"spec": spec_dict}}
        self.assertEqual(extract_vega_spec(parts=[part2]), spec_dict)

        part3 = {"vegaConfig": json.dumps(spec_dict)}
        self.assertEqual(extract_vega_spec(parts=[part3]), spec_dict)

    def test_extract_vega_spec_gda_surface_update(self):
        gda_part = {
            "data": {
                "data": {
                    "surfaceUpdate": {
                        "surfaceId": "chart-surface-1",
                        "components": [
                            {
                                "id": "root-container",
                                "component": {
                                    "id": "vega-chart",
                                    "VegaChart": {
                                        "spec": {
                                            "$schema": "https://vega.github.io/schema/vega-lite/v4.17.0.json",
                                            "mark": "bar",
                                            "encoding": {"x": {"field": "Category"}},
                                        }
                                    },
                                },
                            }
                        ],
                    }
                }
            }
        }
        extracted = extract_vega_spec(parts=[gda_part])
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted["mark"], "bar")
        self.assertEqual(extracted["encoding"]["x"]["field"], "Category")

    def test_extract_datagrid(self):
        gda_part = {
            "data": {
                "data": {
                    "surfaceUpdate": {
                        "surfaceId": "grid-surface-1",
                        "components": [
                            {
                                "id": "root-container",
                                "component": {
                                    "id": "data-grid",
                                    "DataGrid": {
                                        "rowData": [
                                            {"products.category": "Beverages", "sales.total": 61024240.92},
                                            {"products.category": "Wine", "sales.total": 52647789.67},
                                        ],
                                        "schema": {
                                            "fields": [
                                                {"name": "products.category", "display_name": "Category"},
                                                {"name": "sales.total", "display_name": "Total Sales"},
                                            ]
                                        },
                                    },
                                },
                            }
                        ],
                    }
                }
            }
        }
        datagrid = extract_datagrid(parts=[gda_part])
        self.assertIsNotNone(datagrid)
        self.assertEqual(len(datagrid["rowData"]), 2)

    def test_build_analytics_surface_combined(self):
        spec = {"$schema": "https://vega.github.io/schema/vega-lite/v4.17.0.json", "mark": "bar"}
        grid = {
            "rowData": [
                {"products.category": "Beverages", "sales.total": 61024240.92},
            ],
            "schema": {
                "fields": [
                    {"name": "products.category", "display_name": "Category"},
                    {"name": "sales.total", "display_name": "Total Sales"},
                ]
            },
        }
        surface = build_analytics_surface("Top Sales", spec=spec, datagrid=grid)
        self.assertEqual(len(surface), 3)
        self.assertEqual(surface[0]["createSurface"]["catalogId"], GEMINI_ENTERPRISE_COMPOSITE_CATALOG_ID)

        components = surface[2]["updateComponents"]["components"]
        root = components[0]
        self.assertEqual(root["id"], "root")
        self.assertEqual(root["component"], "MaterialCard")
        self.assertIn("chart_1", root["children"])
        self.assertIn("divider_1", root["children"])
        self.assertIn("table_1", root["children"])

        chart_comp = next(c for c in components if c["id"] == "chart_1")
        self.assertEqual(chart_comp["component"], "VegaChart")
        self.assertEqual(chart_comp["spec"], spec)

        table_comp = next(c for c in components if c["id"] == "table_1")
        self.assertEqual(table_comp["component"], "MaterialTable")
        self.assertEqual(table_comp["rows"][0]["sales.total"], "61,024,240.92")

    def test_unique_surface_ids_per_invocation(self):
        # Two consecutive calls should generate distinct surface IDs to prevent multi-turn chat overwrites
        s1 = build_analytics_surface("Turn 1 Data", spec={"mark": "bar"})
        s2 = build_analytics_surface("Turn 2 Data", spec={"mark": "line"})

        id1 = s1[0]["createSurface"]["surfaceId"]
        id2 = s2[0]["createSurface"]["surfaceId"]
        self.assertNotEqual(id1, id2)
        self.assertTrue(id1.startswith("surface_"))
        self.assertTrue(id2.startswith("surface_"))

        # All messages within s1 must share id1
        for msg in s1:
            key = next(k for k in msg if k != "version")
            self.assertEqual(msg[key]["surfaceId"], id1)

        # Explicit surface ID is honored if provided
        explicit = build_analytics_surface("Explicit Surface", surface_id="custom_surface_123")
        self.assertEqual(explicit[0]["createSurface"]["surfaceId"], "custom_surface_123")


if __name__ == "__main__":
    unittest.main()

