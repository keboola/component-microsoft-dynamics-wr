import csv
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dynamics.client import DynamicsClient  # noqa: E402
from keboola.component.exceptions import UserException  # noqa: E402


class TestGetEndpointNavigationProperties(unittest.TestCase):
    """Unit tests for DynamicsClient.get_endpoint_navigation_properties."""

    def setUp(self):
        self.client = DynamicsClient.__new__(DynamicsClient)
        self.client.base_url = 'https://org.crm.dynamics.com/api/data/v9.2/'

    def _mock_ok_response(self, value_list):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {'value': value_list}
        return mock_resp

    def test_returns_navigation_property_names(self):
        self.client.get_raw = MagicMock(return_value=self._mock_ok_response([
            {'ReferencingEntityNavigationPropertyName': 'customerid_account'},
            {'ReferencingEntityNavigationPropertyName': 'customerid_contact'},
        ]))
        result = self.client.get_endpoint_navigation_properties('incident')
        self.assertIn('customerid_account', result)
        self.assertIn('customerid_contact', result)
        self.assertEqual(len(result), 2)

    def test_filters_empty_nav_property_names(self):
        self.client.get_raw = MagicMock(return_value=self._mock_ok_response([
            {'ReferencingEntityNavigationPropertyName': 'customerid_account'},
            {'ReferencingEntityNavigationPropertyName': ''},
            {'ReferencingEntityNavigationPropertyName': None},
            {},
        ]))
        result = self.client.get_endpoint_navigation_properties('incident')
        self.assertEqual(result, ['customerid_account'])

    def test_empty_response_returns_empty_list(self):
        self.client.get_raw = MagicMock(return_value=self._mock_ok_response([]))
        result = self.client.get_endpoint_navigation_properties('incident')
        self.assertEqual(result, [])

    def test_http_error_is_propagated(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError('403 Forbidden')
        self.client.get_raw = MagicMock(return_value=mock_resp)
        with self.assertRaises(requests.HTTPError):
            self.client.get_endpoint_navigation_properties('incident')


class TestCheckInputAttributes(unittest.TestCase):
    """Tests for the polymorphic @odata.bind validation in check_input_attributes."""

    def _build_component(self, table_name, rows, supported_attrs, nav_properties, operation='upsert'):
        tmp_dir = tempfile.mkdtemp()
        csv_path = os.path.join(tmp_dir, f'{table_name}.csv')
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'data'])
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    'id': row.get('id', 'test-uuid'),
                    'data': json.dumps(row['data']),
                })

        mock_table = MagicMock()
        mock_table.name = f'{table_name}.csv'
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
            'incidents',
            [{'id': 'abc', 'data': {'customerid_account@odata.bind': '/accounts(xyz)'}}],
            supported_attrs=['title', 'description'],
            nav_properties=['customerid_account', 'customerid_contact'],
        )
        comp.check_input_attributes()  # must not raise

    def test_regular_odata_bind_on_attribute_is_accepted(self):
        """Standard @odata.bind on a regular entity attribute still passes."""
        comp = self._build_component(
            'incidents',
            [{'id': 'abc', 'data': {'mil_incidentcategoryl1id@odata.bind': '/mil_incidentcategories(xyz)'}}],
            supported_attrs=['mil_incidentcategoryl1id', 'title'],
            nav_properties=[],
        )
        comp.check_input_attributes()  # must not raise

    def test_invalid_odata_bind_key_is_rejected(self):
        """A typo in an @odata.bind key is caught and raises UserException."""
        comp = self._build_component(
            'incidents',
            [{'id': 'abc', 'data': {'nonexistent_field@odata.bind': '/something(xyz)'}}],
            supported_attrs=['title'],
            nav_properties=['customerid_account'],
        )
        with self.assertRaises(UserException):
            comp.check_input_attributes()

    def test_regular_supported_attribute_is_accepted(self):
        """Plain field present in supported_attrs passes without error."""
        comp = self._build_component(
            'incidents',
            [{'id': 'abc', 'data': {'title': 'Test', 'description': 'Desc'}}],
            supported_attrs=['title', 'description'],
            nav_properties=[],
        )
        comp.check_input_attributes()  # must not raise

    def test_unsupported_plain_attribute_is_rejected(self):
        """Plain field absent from supported_attrs raises UserException."""
        comp = self._build_component(
            'incidents',
            [{'id': 'abc', 'data': {'title': 'Test', 'notanattr': 'value'}}],
            supported_attrs=['title'],
            nav_properties=[],
        )
        with self.assertRaises(UserException):
            comp.check_input_attributes()

    def test_delete_operation_skips_attribute_validation(self):
        """Delete rows bypass attribute validation entirely."""
        comp = self._build_component(
            'incidents',
            [{'id': 'some-id', 'data': {}}],
            supported_attrs=[],
            nav_properties=[],
            operation='delete',
        )
        comp.check_input_attributes()  # must not raise


if __name__ == '__main__':
    unittest.main()
