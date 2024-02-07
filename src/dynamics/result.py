import csv
import hashlib
import json
import os
import time

FIELDS_RESULTS = ['request_id', 'timestamp', 'endpoint', 'operation',
                  'id', 'data', 'operation_status', 'operation_response']
PK_RESULTS = ['request_id']


class DynamicsResultsWriter:

    def __init__(self, data_out_path):

        self.parDataOutPath = data_out_path
        self.parTablePath = os.path.join(self.parDataOutPath, 'results.csv')

        self._create_manifest()
        self._create_writer()

    def _create_manifest(self):

        _template = {
            'incremental': True,
            'primary_key': PK_RESULTS,
            'columns': FIELDS_RESULTS
        }

        with open(self.parTablePath + '.manifest', 'w') as manFile:
            json.dump(_template, manFile)

    def _create_writer(self):

        self.writer = csv.DictWriter(open(self.parTablePath, 'w'), fieldnames=FIELDS_RESULTS, restval='',
                                     extrasaction='ignore', quotechar='\"', quoting=csv.QUOTE_ALL)

    def writerow(self, row_dict, endpoint, operation, request_id=None):

        write_time = str(int(time.time() * 1000))

        if request_id is None:
            encode_string = '|'.join([write_time, endpoint, operation, str(row_dict)])
            request_id = hashlib.md5(encode_string.encode()).hexdigest()

        write_dict = {
            **row_dict,
            **{
                'request_id': request_id,
                'endpoint': endpoint,
                'operation': operation,
                'timestamp': write_time
            }
        }

        self.writer.writerow(write_dict)
