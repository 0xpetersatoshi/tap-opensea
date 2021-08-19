import requests
import backoff

from singer import get_logger

LOGGER = get_logger()
BASE_URL = "https://api.opensea.io"


def retry_after_wait_gen():
    """
    Returns a generator that is passed to backoff decorator to indicate how long
    to backoff for in seconds.
    """
    while True:
        sleep_time = 60
        LOGGER.info("API rate limit exceeded -- sleeping for %s seconds", sleep_time)
        yield sleep_time


class OpenSeaClient:

    def __init__(self, asset_contract_address: str, api_key: str = None):
        self.asset_contract_address = asset_contract_address
        self._api_key = api_key
        self._base_url = BASE_URL
        self._session = requests.Session()
        self._headers = {}

    def _build_url(self, endpoint: str) -> str:
        """
        Builds the URL for the API request.

        :param endpoint: The API URI (resource)
        :return: The full API URL for the request
        """
        return f"{self._base_url}{endpoint}"

    def _get(self, url, headers=None, params=None, data=None):
        """
        Wraps the _make_request function with a 'GET' method
        """
        return self._make_request(url, method='GET', headers=headers, params=params, data=data)

    def _post(self, url, headers=None, params=None, data=None):
        """
        Wraps the _make_request function with a 'POST' method
        """
        return self._make_request(url, method='POST', headers=headers, params=params, data=data)

    # @backoff.on_exception(retry_after_wait_gen, Exception, jitter=None, max_tries=3)
    def _make_request(self, url, method, headers=None, params=None, data=None) -> dict:
        """
        Makes the API request.

        :param url: The full API url
        :param method: The API request method
        :param headers: The headers for the API request
        :param params: The querystring params passed to the API
        :param data: The data passed to the body of the request
        :return: A dictionary representing the response from the API
        """

        with self._session as session:
            response = session.request(method, url, headers=headers, params=params, data=data)

            response.raise_for_status()
            # if response.status_code != 200:
            #     raise_for_error(response)
            #     return None

            return response.json()

    def get(self, endpoint, params=None):
        """
        Takes the base_url and endpoint and builds and makes a 'GET' request
        to the API.
        """
        url = self._build_url(endpoint)
        return self._get(url, headers=self._headers, params=params)

    def get_contract_address(self):
        return self.asset_contract_address
