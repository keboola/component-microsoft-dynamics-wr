import csv
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from keboola.component.exceptions import UserException  # noqa: E402

from dynamics.client import DynamicsClient  # noqa: E402


class TestGetEndpointNavigationProperties(unittest.TestCase):
    """Unit tests for DynamicsClient.get_endpoint_navigation_properties."""

    def setUp(self):
        self.client = DynamicsClient.__new__(DynamicsClient)
        self.client.base_url = "https://org.crm.dynamics.com/api/data/v9.2/"

    def _mock_ok_response(self, value_list):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"value": value_list}
        return mock_resp

    def test_returns_navigation_property_names(self):
        self.client.get_raw = MagicMock(
            return_value=self._mock_ok_response(
                [
                    {"ReferencingEntityNavigationPropertyName": "customerid_account"},
                    {"ReferencingEntityNavigationPropertyName": "customerid_contact"},
                ]
            )
        )
        result = self.client.get_endpoint_navigation_properties("incident")
        self.assertIn("customerid_account", result)
        self.assertIn("customerid_contact", result)
        self.assertEqual(len(result), 2)

    def test_filters_empty_nav_property_names(self):
        self.client.get_raw = MagicMock(
            return_value=self._mock_ok_response(
                [
                    {"ReferencingEntityNavigationPropertyName": "customerid_account"},
                    {"ReferencingEntityNavigationPropertyName": ""},
                    {"ReferencingEntityNavigationPropertyName": None},
                    {},
                ]
            )
        )
        result = self.client.get_endpoint_navigation_properties("incident")
        self.assertEqual(result, ["customerid_account"])

    def test_empty_response_returns_empty_list(self):
        self.client.get_raw = MagicMock(return_value=self._mock_ok_response([]))
        result = self.client.get_endpoint_navigation_properties("incident")
        self.assertEqual(result, [])

    def test_http_error_is_propagated(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
        self.client.get_raw = MagicMock(return_value=mock_resp)
        with self.assertRaises(requests.HTTPError):
            self.client.get_endpoint_navigation_properties("incident")


class TestCheckInputAttributes(unittest.TestCase):
    """Tests for the polymorphic @odata.bind validation in check_input_attributes."""

    def _build_component(self, table_name, rows, supported_attrs, nav_properties, operation="upsert"):
        tmp_dir = tempfile.mkdtemp()
        csv_path = os.path.join(tmp_dir, f"{table_name}.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "data"])
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "id": row.get("id", "test-uuid"),
                        "data": json.dumps(row["data"]),
                    }
                )

        mock_table = MagicMock()
        mock_table.name = f"{table_name}.csv"
        mock_table.full_path = csv_path

        mock_client = MagicMock()
        mock_client.supported_endpoints = {table_name: table_name}
        mock_client.get_endpoint_attributes.return_value = supported_attrs
        mock_client.get_endpoint_navigation_properties.return_value = nav_properties

        mock_cfg = MagicMock()
        mock_cfg.operation = operation

        from component import Component

        comp = Component.__new__(Component)
        comp.in_tables = [mock_table]
        comp._client = mock_client
        comp.cfg = mock_cfg
        return comp

    def test_polymorphic_nav_property_odata_bind_is_accepted(self):
        """customerid_account@odata.bind passes when customerid_account is a nav property."""
        comp = self._build_component(
            "incidents",
            [{"id": "abc", "data": {"customerid_account@odata.bind": "/accounts(xyz)"}}],
            supported_attrs=["title", "description"],
            nav_properties=["customerid_account", "customerid_contact"],
        )
        comp.check_input_attributes()  # must not raise

    def test_regular_odata_bind_on_attribute_is_accepted(self):
        """Standard @odata.bind on a regular entity attribute still passes."""
        comp = self._build_component(
            "incidents",
            [{"id": "abc", "data": {"mil_incidentcategoryl1id@odata.bind": "/mil_incidentcategories(xyz)"}}],
            supported_attrs=["mil_incidentcategoryl1id", "title"],
            nav_properties=[],
        )
        comp.check_input_attributes()  # must not raise

    def test_invalid_odata_bind_key_is_rejected(self):
        """A typo in an @odata.bind key is caught and raises UserException."""
        comp = self._build_component(
            "incidents",
            [{"id": "abc", "data": {"nonexistent_field@odata.bind": "/something(xyz)"}}],
            supported_attrs=["title"],
            nav_properties=["customerid_account"],
        )
        with self.assertRaises(UserException):
            comp.check_input_attributes()

    def test_regular_supported_attribute_is_accepted(self):
        """Plain field present in supported_attrs passes without error."""
        comp = self._build_component(
            "incidents",
            [{"id": "abc", "data": {"title": "Test", "description": "Desc"}}],
            supported_attrs=["title", "description"],
            nav_properties=[],
        )
        comp.check_input_attributes()  # must not raise

    def test_unsupported_plain_attribute_is_rejected(self):
        """Plain field absent from supported_attrs raises UserException."""
        comp = self._build_component(
            "incidents",
            [{"id": "abc", "data": {"title": "Test", "notanattr": "value"}}],
            supported_attrs=["title"],
            nav_properties=[],
        )
        with self.assertRaises(UserException):
            comp.check_input_attributes()

    def test_delete_operation_skips_attribute_validation(self):
        """Delete rows bypass attribute validation entirely."""
        comp = self._build_component(
            "incidents",
            [{"id": "some-id", "data": {}}],
            supported_attrs=[],
            nav_properties=[],
            operation="delete",
        )
        comp.check_input_attributes()  # must not raise


class TestEntitySetNameDerivation(unittest.TestCase):
    """Regression tests for CFTL-658.

    keboola-component >=1.5 overrides ``TableDefinition.name`` with the Storage
    table name from the manifest, which is unrelated to the Dynamics entity set.
    The entity set must be derived from the on-disk filename (``full_path``), not
    ``table.name``, otherwise every config whose Storage table name differs from
    the entity set name fails endpoint validation.

    These tests build a *real* ``TableDefinition`` via the installed
    keboola-component library (no hand-set mock for ``name``) so they both
    reproduce the library's behaviour and prove the fix against the real object.
    """

    STORAGE_NAME = "FINAL_REMIND_ME_PROD_ACCOUNT_GUID"

    def _real_table(self, on_disk_filename, rows=None, sliced=False):
        """Build a real TableDefinition whose Storage name differs from its filename.

        Writes an on-disk table named ``on_disk_filename`` plus a manifest whose
        ``name`` is the unrelated Storage table name, then lets the real library
        construct the TableDefinition exactly as ``get_input_tables_definitions``
        does.
        """
        from keboola.component.dao import TableDefinition

        tmp_dir = tempfile.mkdtemp()
        data_path = os.path.join(tmp_dir, on_disk_filename)

        if sliced:
            os.makedirs(data_path)
            with open(os.path.join(data_path, "part-0.csv"), "w", newline="") as f:
                self._write_rows(f, rows)
        else:
            with open(data_path, "w", newline="") as f:
                self._write_rows(f, rows)

        manifest_path = data_path + ".manifest"
        with open(manifest_path, "w") as f:
            json.dump({"id": f"in.c-bucket.{self.STORAGE_NAME}", "name": self.STORAGE_NAME}, f)

        table = TableDefinition.build_from_manifest(manifest_path)
        # Guard: confirm the library really does override name with the Storage
        # name in the installed version — otherwise the test proves nothing.
        self.assertEqual(table.name, self.STORAGE_NAME)
        return table

    @staticmethod
    def _write_rows(f, rows):
        writer = csv.DictWriter(f, fieldnames=["id", "data"])
        writer.writeheader()
        for row in rows or []:
            writer.writerow({"id": row.get("id", "test-uuid"), "data": json.dumps(row["data"])})

    def _component_for(self, table, supported_endpoints, supported_attrs=None, nav_properties=None):
        mock_client = MagicMock()
        mock_client.supported_endpoints = supported_endpoints
        mock_client.get_endpoint_attributes.return_value = supported_attrs or []
        mock_client.get_endpoint_navigation_properties.return_value = nav_properties or []

        mock_cfg = MagicMock()
        mock_cfg.operation = "upsert"

        from component import Component

        comp = Component.__new__(Component)
        comp.in_tables = [table]
        comp._client = mock_client
        comp.cfg = mock_cfg
        return comp

    def test_entity_set_name_uses_filename_not_storage_name(self):
        from component import Component

        table = self._real_table("incidents.csv")
        self.assertEqual(Component._entity_set_name(table), "incidents")

    def test_entity_set_name_for_sliced_table_directory(self):
        from component import Component

        table = self._real_table("incidents", sliced=True)
        self.assertEqual(Component._entity_set_name(table), "incidents")

    def test_check_input_endpoints_resolves_filename_over_storage_name(self):
        """The bug: endpoint validation rejected the Storage name. It must use the filename."""
        table = self._real_table("incidents.csv")
        comp = self._component_for(table, supported_endpoints={"incidents": "incident"})
        comp.check_input_endpoints()  # must not raise

    def test_check_input_attributes_resolves_filename_over_storage_name(self):
        table = self._real_table("incidents.csv", rows=[{"id": "abc", "data": {"title": "Test"}}])
        comp = self._component_for(
            table,
            supported_endpoints={"incidents": "incident"},
            supported_attrs=["title"],
        )
        comp.check_input_attributes()  # must not raise


if __name__ == "__main__":
    unittest.main()
