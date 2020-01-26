import csv
import glob
import logging
import json
import os
import sys
from kbc.env_handler import KBCEnvHandler
from dynamics.client import DynamicsClient
from dynamics.result import DynamicsResultsWriter

APP_VERSION = '0.1.0'

KEY_ORGANIZATIONURL = 'organization_url'
KEY_API_VERSION = 'api_version'
KEY_OPERATION = 'operation'
KEY_CONTINUEONERROR = 'continue_on_error'

MANDATORY_PARAMS = [KEY_ORGANIZATIONURL, KEY_API_VERSION, KEY_OPERATION]

AUTH_APPKEY = 'appKey'
AUTH_APPSECRET = '#appSecret'
AUTH_APPDATA = '#data'
AUTH_APPDATA_REFRESHTOKEN = 'refresh_token'

SUPPORTED_OPERATIONS = ['delete', 'create_and_update', 'upsert']
MANDATORYFIELDS_UPSERT = ['id', 'data']
MANDATORYFIELDS_DELETE = ['id']


class DynamicsComponent(KBCEnvHandler):

    def __init__(self):

        super().__init__(mandatory_params=MANDATORY_PARAMS, log_level='DEBUG')
        logging.info("Running component version %s..." % APP_VERSION)
        self.validate_config(MANDATORY_PARAMS)

        auth = self.get_authorization()
        self.parClientId = auth[AUTH_APPKEY]
        self.parClientSecret = auth[AUTH_APPSECRET]

        authData = json.loads(auth[AUTH_APPDATA])
        self.parRefreshToken = authData[AUTH_APPDATA_REFRESHTOKEN]

        self.parApiVersion = self.cfg_params[KEY_API_VERSION]
        self.parResourceUrl = self.cfg_params[KEY_ORGANIZATIONURL]
        self.parOperation = self.cfg_params[KEY_OPERATION]
        self.parContinueOnError = self.cfg_params.get(KEY_CONTINUEONERROR, True)

        self.client = DynamicsClient(self.parClientId, self.parClientSecret,
                                     self.parResourceUrl, self.parRefreshToken, self.parApiVersion)

        self.writer = DynamicsResultsWriter(self.tables_out_path)

        self.checkInputTables()
        self.checkInputEndpoints()
        self.checkOperation()

    def checkInputTables(self):

        globPattern = os.path.join(self.tables_in_path, '*.csv')
        inputTables = glob.glob(globPattern)

        if len(inputTables) == 0:
            logging.error("No input tables specified. At least one input table is required.")
            sys.exit(1)

        else:
            self.varInputTables = {os.path.splitext(os.path.basename(e))[0]: e for e in inputTables}

        if self.parOperation == 'delete':
            _mandFields = MANDATORYFIELDS_DELETE

        else:
            _mandFields = MANDATORYFIELDS_UPSERT

        mandFieldsSet = set(_mandFields)
        tablesWithMissingFields = []

        for tableName, tablePath in self.varInputTables.items():
            with open(tablePath) as inTable:

                _rdr = csv.DictReader(inTable)
                _tableCols = set(_rdr.fieldnames if _rdr.fieldnames is not None else [])
                colDiff = list(mandFieldsSet - _tableCols)

                if len(colDiff) != 0:
                    tablesWithMissingFields += [tableName]

        if len(tablesWithMissingFields) != 0:
            logging.error(f"Mandatory fields {mandFieldsSet} missing in tables {tablesWithMissingFields}.")
            sys.exit(1)

    def checkInputEndpoints(self):

        unsupportedEndpoints = []

        for endpoint in self.varInputTables:
            if endpoint not in self.client.varApiObjects:

                unsupportedEndpoints += [endpoint]

        if len(unsupportedEndpoints) > 0:
            urlEndpoints = os.path.join(self.parResourceUrl,
                                        f'api/data/{self.parApiVersion}/EntityDefinitions?%24select=EntitySetName')
            logging.error(' '.join(["Some endpoints are not available in the Dynamics CRM API instance.",
                                    f"Unsupported endpoints: {unsupportedEndpoints}. For the list of available",
                                    f"endpoints, please visit: {urlEndpoints},",
                                    "or refer to your Dynamics CRM settings."]))
            sys.exit(1)

    def checkOperation(self):

        if self.parOperation not in SUPPORTED_OPERATIONS:
            logging.error(' '.join([f"Unsupported operation {self.parOperation}.",
                                    f"Operation must be one of {SUPPORTED_OPERATIONS}."]))
            sys.exit(1)

    @staticmethod
    def getRequestId(request):

        _reqid = request.headers.get('req_id')
        if _reqid is not None:
            _reqid = _reqid.split(',')[0].strip()

        return _reqid

    @staticmethod
    def parseJsonFromString(objectString):

        try:
            return json.loads(objectString)

        except ValueError:
            pass

        try:
            return eval(objectString)

        except SyntaxError:
            pass

        return None

    def makeRequest(self, operation, endpoint, recordId, recordData):

        if operation == 'delete':
            return self.client.deleteRecord(endpoint, recordId)

        elif operation == 'upsert':
            return self.client.upsertRecord(endpoint, recordId, recordData)

        elif operation == 'update':
            return self.client.updateRecord(endpoint, recordId, recordData)

        elif operation == 'create':
            return self.client.createRecord(endpoint, recordData)

    def parseResponse(self, operation, requestObject):

        scReq = requestObject.status_code
        idReq = self.getRequestId(requestObject)

        if scReq == 204:
            rspReq = ''
            if operation == 'create':
                rspReq = requestObject.headers['OData-EntityId']

            return (True, idReq, {
                'operation_status': f"REQUEST_OK - {scReq}",
                'operation_response': rspReq
            })

        elif scReq == 404:
            rspReq = requestObject.json()['error']['message']

            return (False, idReq, {
                'operation_status': f"REQUEST_ERROR - {scReq}",
                'operation_response': rspReq
            })

        elif scReq == 400:
            rspReq = requestObject.json()['error']['message'].split('\r\n')[0]
            rspReq = ' '.join(["Attribute you're trying to update most likely does not exist.",
                               "Please, check all attributes are published in CRM.",
                               f"\nReceived: {rspReq}"])

            return (False, idReq, {
                'operation_status': f"REQUEST_ERROR - {scReq}",
                'operation_response': rspReq
            })

        else:
            return (False, idReq, {
                'operation_status': f"UNKNOWN_ERROR - {scReq}",
                'operation_response': requestObject.json()
            })

    def run(self):

        for endpoint, path in self.varInputTables.items():

            logging.info(f"Writing data to {endpoint}.")
            errorCounter = 0

            with open(path) as inTable:

                tableReader = csv.DictReader(inTable)

                for row in tableReader:

                    recordId = row['id'].strip()
                    recordData = None

                    if recordId == '' and self.parOperation != 'create_and_update':
                        if self.parContinueOnError is False:
                            logging.error("For upsert and delete operations, all records must have valid IDs provided.")
                            sys.exit(1)

                        self.writer.writerow({
                            **row,
                            **{
                                'operation_status': "MISSING_ID_ERROR",
                                'operation_response': "For upsert and delete operations, an ID must to be provided" +
                                                      " for all records."
                            }
                        }, endpoint, self.parOperation)
                        errorCounter += 1
                        continue

                    if self.parOperation == 'create_and_update':
                        if recordId == '':
                            recordOperation = 'create'
                        else:
                            recordOperation = 'update'

                    else:
                        recordOperation = self.parOperation

                    if recordOperation != 'delete':
                        recordData = self.parseJsonFromString(row['data'])

                        if recordData is None:
                            if self.parContinueOnError is False:
                                logging.error(''.join([f"Invalid data provided. {row['data']} is not a valid",
                                                       " JSON or Python Dictionary representation."]))
                                sys.exit(1)

                            else:
                                self.writer.writerow({**row, **{
                                    'operation_status': "DATA_ERROR",
                                    'operation_message': "Data provided is not a valid JSON or Python Dict object."
                                }}, endpoint, recordOperation)

                                errorCounter += 1
                                continue

                    reqRecord = self.makeRequest(recordOperation, endpoint, recordId, recordData)
                    if reqRecord.status_code == 401:
                        self.client.refreshToken()
                        reqRecord = self.makeRequest(recordOperation, endpoint, recordId, recordData)

                    success, requestId, requestStatusDict = self.parseResponse(recordOperation, reqRecord)

                    if (success is False and self.parContinueOnError is False):
                        logging.error(f"There was an error during {recordOperation} operation on {endpoint} endpoint.")
                        logging.error(f"Received: {requestStatusDict}.")
                        sys.exit(1)

                    else:
                        errorCounter += int(not success)
                        self.writer.writerow({**row, **requestStatusDict}, endpoint, recordOperation, requestId)

            if errorCounter != 0:
                logging.warn(''.join([f"There were {errorCounter} errors during {self.parOperation} operation on",
                                      f" {endpoint} endpoint."]))
