# import json
import logging
import os
import requests
import sys
from urllib.parse import urljoin
from kbc.client_base import HttpClientBase


BASE_URL_REFRESH = 'https://login.microsoftonline.com/common/oauth2/token'


class DynamicsClientRefresh(HttpClientBase):

    def __init__(self):

        super().__init__(base_url=BASE_URL_REFRESH)

    def refreshAccessToken(self, clientId, clientSecret, resourceUrl, refreshToken):

        logging.debug("Refreshing access token.")

        headersRefresh = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }

        bodyRefresh = {
            'client_id': clientId,
            'grant_type': 'refresh_token',
            'client_secret': clientSecret,
            'resource': resourceUrl,
            'refresh_token': refreshToken
        }

        reqRefresh = self.post_raw(url=self.base_url, headers=headersRefresh, data=bodyRefresh)
        scRefresh, jsRefresh = reqRefresh.status_code, reqRefresh.json()

        if scRefresh == 200:

            logging.debug("Token refreshed successfully.")
            return jsRefresh['access_token']

        else:

            logging.error(f"Could not refresh access token. Received {scRefresh} - {jsRefresh}.")
            sys.exit(1)


class DynamicsClient(HttpClientBase):

    def __init__(self, clientId, clientSecret, resourceUrl, refreshToken, apiVersion):

        self.parClientId = clientId
        self.parClientSecret = clientSecret

        self.parAccessToken = self.refreshToken(self.parClientId, self.parClientSecret,
                                                os.path.join(resourceUrl, ''), refreshToken)

        _defHeader = {
            'Authorization': f'Bearer {self.parAccessToken}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        self.parResourceUrl = urljoin(resourceUrl, f'api/data/{apiVersion}/')

        super().__init__(base_url=self.parResourceUrl, default_http_header=_defHeader,
                         backoff_factor=0.1, max_retries=7)
        self.getEntityMetadata()

    def patch_raw(self, *args, **kwargs):

        s = requests.Session()
        headers = kwargs.pop('headers', {})
        headers.update(self._auth_header)
        s.headers.update(headers)
        s.auth = self._auth

        r = self.requests_retry_session(session=s).request('PATCH', *args, **kwargs)
        return r

    def delete_raw(self, *args, **kwargs):

        s = requests.Session()
        headers = kwargs.pop('headers', {})
        headers.update(self._auth_header)
        s.headers.update(headers)
        s.auth = self._auth

        r = self.requests_retry_session(session=s).request('DELETE', *args, **kwargs)
        return r

    def refreshToken(self, clientId, clientSecret, resourceUrl, refreshToken):

        return DynamicsClientRefresh().refreshAccessToken(clientId, clientSecret, resourceUrl, refreshToken)

    def getEntityMetadata(self):

        urlMeta = os.path.join(self.base_url, 'EntityDefinitions')
        paramsMeta = {
            '$select': 'EntitySetName'
        }

        try:
            reqMeta = self.get_raw(url=urlMeta, params=paramsMeta)

        except requests.exceptions.ConnectionError as e:
            logging.error(' '.join(["Could not obtain logical object definitions. Please, check the",
                                    f"organization URL or authorization. \n{e}"]))
            sys.exit(1)

        except requests.exceptions.RetryError as e:
            logging.error(' '.join(["Could not obtain logical object definitions. Please, check the",
                                    "the supported API version in correct format (v9.0, v9.1, etc.) is specified.",
                                    f"\n{e}"]))
            sys.exit(1)

        scMeta = reqMeta.status_code
        jsMeta = reqMeta.json()
        if scMeta == 200:

            logging.debug("Obtained logical definitions of entities.")
            self.varApiObjects = [e['EntitySetName'].lower() for e in jsMeta['value'] if e['EntitySetName'] is not None]

        else:

            logging.error("Could not obtain entity metadata for resource.")
            logging.error(f"Received: {scMeta} - {jsMeta}.")
            sys.exit(1)

    def createRecord(self, endpoint, data):

        urlCreate = urljoin(self.base_url, endpoint)
        dataCreate = data

        return self.post_raw(url=urlCreate, json=dataCreate)

    def updateRecord(self, endpoint, recordId, data):

        urlUpdate = urljoin(self.base_url, f'{endpoint}({recordId})')
        headersUpdate = {
            'If-Match': '*'
        }
        dataUpdate = data

        return self.patch_raw(url=urlUpdate, json=dataUpdate, headers=headersUpdate)

    def upsertRecord(self, endpoint, recordId, data):

        urlUpdate = urljoin(self.base_url, f'{endpoint}({recordId})')
        dataUpdate = data

        return self.patch_raw(url=urlUpdate, json=dataUpdate)

    def deleteRecord(self, endpoint, recordId):

        urlDelete = urljoin(self.base_url, f'{endpoint}({recordId})')

        return self.delete_raw(urlDelete)
