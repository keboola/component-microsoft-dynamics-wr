import logging
import os

import requests
from keboola.component import UserException
from keboola.http_client import HttpClient
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class DynamicsClient(HttpClient):
    DEFAULT_AUTHORITY_URL = "https://login.microsoftonline.com/common"
    # Azure AD v1 token endpoint, because refresh_token() sends the `resource` parameter.
    TOKEN_ENDPOINT = "/oauth2/token"
    MSFT_LOGIN_URL = DEFAULT_AUTHORITY_URL + TOKEN_ENDPOINT
    MAX_RETRIES = 7
    PAGE_SIZE = 2000

    def __init__(
        self,
        client_id,
        client_secret,
        resource_url,
        refresh_token,
        api_version,
        max_page_size: int = PAGE_SIZE,
        authority_url: str | None = None,
    ):

        self.client_id = client_id
        self.client_secret = client_secret
        self.resource_url = os.path.join(resource_url, "")
        self._refresh_token = refresh_token
        self._max_page_size = max_page_size
        self.supported_endpoints = []
        self.msft_login_url = self.build_token_url(authority_url)
        _accessToken = self.refresh_token()
        super().__init__(
            base_url=os.path.join(resource_url, "api/data/", api_version),
            max_retries=self.MAX_RETRIES,
            auth_header={"Authorization": f"Bearer {_accessToken}"},
        )

    @classmethod
    def build_token_url(cls, authority_url: str | None = None) -> str:
        """Builds the Microsoft identity platform token endpoint.

        authority_url is the optional per stack override
        (image_parameters.microsoftAuthorityUrl), for example
        https://login.microsoftonline.com/<tenant-id>. Microsoft rejects the shared
        /common endpoint for single tenant app registrations (AADSTS50194), so a
        stack with such a registration must call its own tenant instead.

        When the override is not set, the default /common endpoint is used and the
        behaviour is unchanged.
        """
        if not authority_url:
            return cls.MSFT_LOGIN_URL
        return authority_url.rstrip("/") + cls.TOKEN_ENDPOINT

    def refresh_token(self):

        headers_refresh = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}

        body_refresh = {
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "client_secret": self.client_secret,
            "resource": self.resource_url,
            "refresh_token": self._refresh_token,
        }

        resp = requests.post(self.msft_login_url, headers=headers_refresh, data=body_refresh)
        code, response_json = resp.status_code, resp.json()

        if code == 200:
            logging.debug("Access token refreshed successfully.")
            return response_json["access_token"]

        else:
            raise UserException(f"Could not refresh access token. Received {code} - {response_json}.")

    def __response_hook(self, res, *args, **kwargs):

        if res.status_code == 401:
            token = self._refresh_token()
            self.update_auth_header({"Authorization": f"Bearer {token}"})

            res.request.headers["Authorization"] = f"Bearer {token}"
            s = requests.Session()
            return self.requests_retry_session(session=s).send(res.request)

    def requests_retry_session(self, session=None):

        session = session or requests.Session()
        retry = Retry(
            total=self.max_retries,
            read=self.max_retries,
            connect=self.max_retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=self.status_forcelist,
            allowed_methods=("GET", "POST", "PATCH", "UPDATE", "DELETE"),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        # append response hook
        session.hooks["response"].append(self.__response_hook)
        return session

    def get_entity_metadata(self) -> None:

        url = os.path.join(self.base_url, "EntityDefinitions")

        params_meta = {"$select": "EntitySetName,LogicalName"}

        response = self.get_raw(url, is_absolute_path=True, params=params_meta)
        try:
            response.raise_for_status()
            json_data = response.json()
            self.supported_endpoints = {
                entity["EntitySetName"].lower(): entity["LogicalName"].lower()
                for entity in json_data["value"]
                if entity["EntitySetName"] is not None
            }

        except requests.HTTPError as e:
            raise e

    def get_endpoint_attributes(self, entity_name: str) -> list:

        url = os.path.join(self.base_url, f"EntityDefinitions(LogicalName='{entity_name}')/Attributes")

        response = self.get_raw(url, is_absolute_path=True)

        try:
            response.raise_for_status()
            json_data = response.json()

            attributes = [
                attr.get("LogicalName")
                for attr in json_data.get("value")
                if attr.get("IsValidForCreate") or attr.get("IsValidForUpdate")
            ]

            return attributes

        except requests.HTTPError as e:
            raise e

    def get_endpoint_navigation_properties(self, entity_name: str) -> list:

        url = os.path.join(
            self.base_url,
            f"EntityDefinitions(LogicalName='{entity_name}')/ManyToOneRelationships",
        )

        params = {"$select": "ReferencingEntityNavigationPropertyName"}

        response = self.get_raw(url, is_absolute_path=True, params=params)

        try:
            response.raise_for_status()
            json_data = response.json()

            nav_properties = [
                rel.get("ReferencingEntityNavigationPropertyName")
                for rel in json_data.get("value", [])
                if rel.get("ReferencingEntityNavigationPropertyName")
            ]

            return nav_properties

        except requests.HTTPError as e:
            raise e

    def create_record(self, endpoint, data):
        url_create = os.path.join(self.base_url, endpoint)
        data_create = data
        return self.post_raw(endpoint_path=url_create, json=data_create)

    def update_record(self, endpoint, record_id, data):
        url_update = os.path.join(self.base_url, f"{endpoint}({record_id})")
        headers_update = {"If-Match": "*"}
        data_update = data
        return self.patch_raw(endpoint_path=url_update, json=data_update, headers=headers_update, is_absolute_path=True)

    def upsert_record(self, endpoint, record_id, data):
        url_update = os.path.join(self.base_url, f"{endpoint}({record_id})")
        data_update = data
        return self.patch_raw(endpoint_path=url_update, json=data_update)

    def delete_record(self, endpoint, record_id):
        url_delete = os.path.join(self.base_url, f"{endpoint}({record_id})")
        return self.delete_raw(url_delete)
