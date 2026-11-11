"""Traffic Analytics owns only its DynamoDB summary table."""

import os

from traffic_contracts.dynamo_store import WindowStore, RecordConflict


class SummaryRepository:
    def __init__(self, *, resource=None, table_name=None):
        self.store = WindowStore(table_name or os.getenv("SUMMARIES_TABLE", "traffic_window_summaries"),
                                 resource=resource)

    def put(self, summary):
        return self.store.put(summary)

    def get(self, intersection_id, window_id):
        return self.store.get(intersection_id, window_id)

    def query(self, intersection_id, **kwargs):
        return self.store.query(intersection_id, **kwargs)
