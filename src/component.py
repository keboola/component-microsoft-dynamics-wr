import csv
import logging
import json
import os
from keboola.component.base import ComponentBase
from keboola.component.exceptions import UserException
from configuration import Configuration
from dynamics.client import DynamicsClient
from dynamics.result import DynamicsResultsWriter

APP_VERSION = '0.1.3'

SUPPORTED_OPERATIONS = ['delete', 'create_and_update', 'upsert']
MANDATORYFIELDS_UPSERT = ['id', 'data']
MANDATORYFIELDS_DELETE = ['id']


class Component(ComponentBase):

    def __init__(self):

        super().__init__()
        self.cfg: Configuration
        self._client: DynamicsClient = None
        self.in_tables = self.get_input_tables_definitions()
        self.writer = DynamicsResultsWriter(self.tables_out_path)

    def run(self):

        self._init_configuration()
        self.check_input_tables()

        self.init_client()
        self._client.get_entity_metadata()

        self.check_input_endpoints()

        self.check_input_attributes()

        for table in self.in_tables:

            endpoint = table.name.replace('.csv', '')

            logging.info(f"Writing data to {endpoint}.")
            error_counter = 0

            with open(table.full_path) as inTable:

                table_reader = csv.DictReader(inTable)

                for row in table_reader:

                    record_id = row['id'].strip()
                    record_data = None

                    if record_id == '' and self.cfg.operation != 'create_and_update':
                        if self.cfg.continue_on_error is False:
                            raise UserException("For upsert and delete operations, all records must have valid IDs "
                                                "provided.")

                        self.writer.writerow({
                            **row,
                            **{
                                'operation_status': "MISSING_ID_ERROR",
                                'operation_response': "For upsert and delete operations, an ID must to be provided" +
                                                      " for all records."
                            }
                        }, endpoint, self.cfg.operation)
                        error_counter += 1
                        continue

                    if self.cfg.operation == 'create_and_update':
                        if record_id == '':
                            record_operation = 'create'
                        else:
                            record_operation = 'update'

                    else:
                        record_operation = self.cfg.operation

                    if record_operation != 'delete':
                        record_data = self.parse_json_from_string(row['data'])

                        if record_data is None:
                            if self.cfg.continue_on_error is False:
                                raise UserException(''.join([f"Invalid data provided. {row['data']} is not a valid",
                                                             " JSON or Python Dictionary representation."]))

                            else:
                                self.writer.writerow({**row, **{
                                    'operation_status': "DATA_ERROR",
                                    'operation_message': "Data provided is not a valid JSON or Python Dict object."
                                }}, endpoint, record_operation)

                                error_counter += 1
                                continue

                    req_record = self.make_request(record_operation, endpoint, record_id, record_data)

                    success, request_id, request_status_dict = self.parse_response(record_operation, req_record)

                    if success is False and self.cfg.continue_on_error is False:
                        raise UserException(f"There was an error during {record_operation} operation"
                                            f"on {endpoint} endpoint. Received: {request_status_dict}.")

                    else:
                        error_counter += int(not success)
                        self.writer.writerow({**row, **request_status_dict}, endpoint, record_operation, request_id)

            if error_counter != 0:
                logging.warning(''.join([f"There were {error_counter} errors during {self.cfg.operation} operation on",
                                         f" {endpoint} endpoint."]))

    def _init_configuration(self) -> None:
        try:
            self.validate_configuration_parameters(Configuration.get_dataclass_required_parameters())
        except UserException as e:
            raise UserException(f"{e} The configuration is invalid. Please check that you added a configuration row.")
        self.cfg: Configuration = Configuration.fromDict(parameters=self.configuration.parameters)

    def init_client(self):
        organization_url = self.configuration.parameters.get('organization_url')
        if not organization_url:
            raise UserException('You must fill in the Organization URL')

        credentials = self.configuration.oauth_credentials

        if not credentials:
            raise UserException("The configuration is not authorized. Please authorize it first.")

        refresh_token = credentials.data['refresh_token']

        self._client = DynamicsClient(credentials.appKey, credentials.appSecret, organization_url,
                                      refresh_token, self.cfg.api_version)

    def check_input_tables(self):

        if len(self.in_tables) == 0:
            raise UserException("No input tables specified. At least one input table is required.")

        if self.cfg.operation == 'delete':
            _mandFields = MANDATORYFIELDS_DELETE

        else:
            _mandFields = MANDATORYFIELDS_UPSERT

        mand_fields_set = set(_mandFields)
        tables_with_missing_fields = []

        for table in self.in_tables:
            with open(table.full_path) as in_table:

                _rdr = csv.DictReader(in_table)
                _table_cols = set(_rdr.fieldnames if _rdr.fieldnames is not None else [])
                col_diff = list(mand_fields_set - _table_cols)

                if len(col_diff) != 0:
                    tables_with_missing_fields += [table.name]

        if len(tables_with_missing_fields) != 0:
            raise UserException(f"Mandatory fields {mand_fields_set} missing in tables {tables_with_missing_fields}.")

    def check_input_endpoints(self):

        unsupported_endpoints = []

        for table in self.in_tables:
            endpoint = table.name.replace('.csv', '').lower()
            if endpoint not in list(self._client.supported_endpoints.keys()):
                unsupported_endpoints += [endpoint]

        if len(unsupported_endpoints) > 0:
            url_endpoints = os.path.join(self.cfg.organization_url,
                                         f'api/data/{self.cfg.api_version}/EntityDefinitions?%24select=EntitySetName')
            raise UserException(' '.join(["Some endpoints are not available in the Dynamics CRM API instance.",
                                          f"Unsupported endpoints: {unsupported_endpoints}. For the list of available",
                                          f"endpoints, please visit: {url_endpoints},",
                                          "or refer to your Dynamics CRM settings."]))

    def check_input_attributes(self):

        for table in self.in_tables:
            table_name = table.name.replace('.csv', '').lower()
            endpoint = self._client.supported_endpoints[table_name]
            supported_attributes = self._client.get_endpoint_attributes(endpoint)

            logging.info(f"Supported attributes for {endpoint}: {supported_attributes}")

            with open(table.full_path) as inTable:
                table_reader = csv.DictReader(inTable)
                row_counter = 0
                for row in table_reader:
                    row_counter += 1
                    record_id = row['id'].strip()

                    if record_id == '' and self.cfg.operation != 'create_and_update':
                        raise UserException(f"In {table.name} on the line {row_counter} is missing ID."
                                            " For upsert and delete operations, all records must have valid IDs")

                    if self.cfg.operation == 'create_and_update':
                        if record_id == '':
                            record_operation = 'create'
                        else:
                            record_operation = 'update'

                    else:
                        record_operation = self.cfg.operation

                    if record_operation != 'delete':
                        record_data = self.parse_json_from_string(row['data'])
                        record_keys = list(record_data.keys())
                        missing = [item for item in record_keys if item not in supported_attributes]

                        if missing:
                            raise UserException(f"In {table.name} on the line {row_counter} are"
                                                f" unsupported attributes: {missing}")

        logging.info("All attributes in input tables are supported.")

    @staticmethod
    def get_request_id(request):

        _reqid = request.headers.get('req_id')
        if _reqid is not None:
            _reqid = _reqid.split(',')[0].strip()

        return _reqid

    @staticmethod
    def parse_json_from_string(object_string):

        try:
            return json.loads(object_string)

        except ValueError:
            pass

        try:
            return eval(object_string)

        except SyntaxError:
            pass

        return None

    def make_request(self, operation, endpoint, record_id, record_data):

        if operation == 'delete':
            return self._client.delete_record(endpoint, record_id)

        elif operation == 'upsert':
            return self._client.upsert_record(endpoint, record_id, record_data)

        elif operation == 'update':
            return self._client.update_record(endpoint, record_id, record_data)

        elif operation == 'create':
            return self._client.create_record(endpoint, record_data)

    def parse_response(self, operation, request_object):

        status_code = request_object.status_code
        id_req = self.get_request_id(request_object)

        if status_code == 204:
            response = ''
            if operation == 'create':
                response = request_object.headers['OData-EntityId']

            return (True, id_req, {
                'operation_status': f"REQUEST_OK - {status_code}",
                'operation_response': response
            })

        elif status_code == 404:
            response = request_object.json()['error']['message']

            return (False, id_req, {
                'operation_status': f"REQUEST_ERROR - {status_code}",
                'operation_response': response
            })

        elif status_code == 401:
            return (False, id_req, {
                'operation_status': f"REQUEST_ERROR - {status_code}",
                'operation_response': request_object.reason
            })

        elif status_code == 400:
            response = request_object.json()['error']['message'].split('\r\n')[0]
            response = ' '.join(["Attribute you're trying to update most likely does not exist.",
                                 "Please, check all attributes are published in CRM.",
                                 f"\nReceived: {response}"])

            return (False, id_req, {
                'operation_status': f"REQUEST_ERROR - {status_code}",
                'operation_response': response
            })

        else:
            return (False, id_req, {
                'operation_status': f"UNKNOWN_ERROR - {status_code}",
                'operation_response': request_object.json()
            })


"""
        Main entrypoint
"""
if __name__ == "__main__":
    try:
        comp = Component()
        # this triggers the run method by default and is controlled by the configuration.action parameter
        comp.execute_action()
    except UserException as exc:
        logging.exception(exc)
        exit(1)
    except Exception as exc:
        logging.exception(exc)
        exit(1)
