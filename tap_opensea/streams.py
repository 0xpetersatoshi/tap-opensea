import csv
from datetime import date, datetime
import time
from typing import Any, Iterator

import requests
import singer
from singer import Transformer, metrics

from tap_opensea.client import OpenSeaClient


LOGGER = singer.get_logger()
DEFAULT_EVENT_TYPE = "successful"

class BaseStream:
    """
    A base class representing singer streams.

    :param client: The API client used extract records from the external source
    """
    tap_stream_id = None
    replication_method = None
    replication_key = None
    key_properties = []
    valid_replication_keys = []
    params = {}
    parent = None
    endpoint = None

    def __init__(self, client: OpenSeaClient):
        self.client = client

    def get_records(self, config: dict = None, is_parent: bool = False) -> list:
        """
        Returns a list of records for that stream.

        :param config: The tap config file
        :param is_parent: If true, may change the type of data
            that is returned for a child stream to consume
        :return: list of records
        """
        raise NotImplementedError("Child classes of BaseStream require implementation")

    def set_parameters(self, params: dict) -> None:
        """
        Sets or updates the `params` attribute of a class.

        :param params: Dictionary of parameters to set or update the class with
        """
        self.params = params

    def get_parent_data(self, config: dict = None) -> list:
        """
        Returns a list of records from the parent stream.

        :param config: The tap config file
        :return: A list of records
        """
        parent = self.parent(self.client)
        return parent.get_records(config, is_parent=True)


class IncrementalStream(BaseStream):
    """
    A child class of a base stream used to represent streams that use the
    INCREMENTAL replication method.

    :param client: The API client used extract records from the external source
    """
    replication_method = 'INCREMENTAL'
    batched = False
    auction_types = ["dutch"]
    event_type = DEFAULT_EVENT_TYPE

    def __init__(self, client):
        super().__init__(client)

    def sync(self, state: dict, stream_schema: dict, stream_metadata: dict, config: dict, transformer: Transformer) -> dict:
        """
        The sync logic for an incremental stream.

        :param state: A dictionary representing singer state
        :param stream_schema: A dictionary containing the stream schema
        :param stream_metadata: A dictionnary containing stream metadata
        :param config: A dictionary containing tap config data
        :param transformer: A singer Transformer object
        :return: State data in the form of a dictionary
        """
        if config.get("auction_types"):
            self.set_auction_types(config.get("auction_types"))

        self.set_event_type(config.get("event_type"))

        start_date = singer.get_bookmark(state, self.tap_stream_id, self.replication_key, config['start_date'])
        bookmark_datetime = singer.utils.strptime_to_utc(start_date)
        max_datetime = bookmark_datetime

        with metrics.record_counter(self.tap_stream_id) as counter:
            for record in self.get_records(bookmark_datetime, config):
                transformed_record = transformer.transform(record, stream_schema, stream_metadata)
                record_datetime = singer.utils.strptime_to_utc(transformed_record[self.replication_key])
                if record_datetime >= bookmark_datetime:
                    singer.write_record(self.tap_stream_id, transformed_record)
                    counter.increment()
                    max_datetime = max(record_datetime, max_datetime)

            bookmark_date = singer.utils.strftime(max_datetime)

        state = singer.write_bookmark(state, self.tap_stream_id, self.replication_key, bookmark_date)
        singer.write_state(state)
        return state

    def set_auction_types(self, auction_types: str):
        try:
            self.auction_types = list(map(str.strip, auction_types.split(",")))
        except Exception as e:
            LOGGER.critical(f"Error setting auction types: {e}")

    def get_auction_types(self):
        return self.auction_types

    def set_event_type(self, event_type: str):
        self.event_type = event_type

    def get_event_type(self) -> str:
        return self.event_type


class FullTableStream(BaseStream):
    """
    A child class of a base stream used to represent streams that use the
    FULL_TABLE replication method.

    :param client: The API client used extract records from the external source
    """
    replication_method = 'FULL_TABLE'

    def __init__(self, client):
        super().__init__(client)

    def sync(self, state: dict, stream_schema: dict, stream_metadata: dict, config: dict, transformer: Transformer) -> dict:
        """
        The sync logic for an full table stream.

        :param state: A dictionary representing singer state
        :param stream_schema: A dictionary containing the stream schema
        :param stream_metadata: A dictionnary containing stream metadata
        :param config: A dictionary containing tap config data
        :param transformer: A singer Transformer object
        :return: State data in the form of a dictionary
        """
        with metrics.record_counter(self.tap_stream_id) as counter:
            for record in self.get_records():
                transformed_record = transformer.transform(record, stream_schema, stream_metadata)
                singer.write_record(self.tap_stream_id, transformed_record)
                counter.increment()

        singer.write_state(state)
        return state


class Assets(FullTableStream):
    """
    Gets records for a sample stream.
    """
    tap_stream_id = 'assets'
    key_properties = ['id']
    endpoint = "/api/v1/assets"

    def get_records(self):
        asset_contract_address = self.client.get_contract_address()

        # offset limit is 10,000
        for offest in range(10_001):
            params = {
                'asset_contract_address': asset_contract_address,
                'limit': 50,
                'offset': offest,
            }

            LOGGER.info(f"offest: {offest}")
            response = self.client.get(self.endpoint, params)

            assets = response.get('assets')
            for asset in assets:
                asset['offset'] = offest

            yield from assets


class Stats(FullTableStream):
    """
    Gets records for a sample stream.
    """
    tap_stream_id = 'stats'
    key_properties = ['date']
    endpoint = "/api/v1/asset/{contract_address}/1"

    def get_records(self) -> list:
        asset_contract_address = self.client.get_contract_address()
        endpoint = self.endpoint.format(contract_address=asset_contract_address)

        response = self.client.get(endpoint)

        stats = response.get("collection").get("stats")
        stats['date'] = singer.utils.now().isoformat()

        yield stats


class Events(IncrementalStream):
    """
    Gets events from OpenSea.
    """
    tap_stream_id = 'events'
    replication_key = 'created_date'
    key_properties = ['id']
    valid_replication_keys = ['created_date']
    endpoint = '/api/v1/events'

    def get_records(self, bookmark_datetime: datetime, config: dict = None, is_parent: bool = None) -> list:
        unix_seconds = bookmark_datetime.timestamp()
        asset_contract_address = self.client.get_contract_address()
        event_type = self.event_type or DEFAULT_EVENT_TYPE

        offset = 0
        response_length = 300
        while response_length > 0 and offset <= 10_000:
            params = {
                'asset_contract_address': asset_contract_address,
                'event_type': event_type,
                # 'auction_type': 'dutch',
                'limit': 300,
                'occurred_after': unix_seconds,
                'offset': offset,
            }

            response = self.client.get(self.endpoint, params)
            events = response.get('asset_events')
            response_length = len(events)
            offset += 1

            yield from events


STREAMS = {
    'assets': Assets,
    'stats': Stats,
    'events': Events,
}
