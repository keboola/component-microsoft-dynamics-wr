import csv
import hashlib
import json
import os
import time

FIELDS_RESULTS = ['request_id', 'timestamp', 'endpoint', 'operation',
                  'id', 'data', 'operation_status', 'operation_response']
PK_RESULTS = ['request_id']


class DynamicsResultsWriter:

    def __init__(self, dataOutPath):

        self.parDataOutPath = dataOutPath
        self.parTablePath = os.path.join(self.parDataOutPath, 'results.csv')

        self._createManifest()
        self._createWriter()

    def _createManifest(self):

        _template = {
            'incremental': True,
            'primary_key': PK_RESULTS,
            'columns': FIELDS_RESULTS
        }

        with open(self.parTablePath + '.manifest', 'w') as manFile:
            json.dump(_template, manFile)

    def _createWriter(self):

        self.writer = csv.DictWriter(open(self.parTablePath, 'w'), fieldnames=FIELDS_RESULTS, restval='',
                                     extrasaction='ignore', quotechar='\"', quoting=csv.QUOTE_ALL)

    def writerow(self, rowDict, endpoint, operation, requestId=None):

        writeTime = str(int(time.time() * 1000))

        if requestId is None:
            encodeString = '|'.join([writeTime, endpoint, operation, str(rowDict)])
            requestId = hashlib.md5(encodeString.encode()).hexdigest()

        writeDict = {
            **rowDict,
            **{
                'request_id': requestId,
                'endpoint': endpoint,
                'operation': operation,
                'timestamp': writeTime
            }
        }

        self.writer.writerow(writeDict)
