"""Signal Recommendation owns only its DynamoDB recommendation table."""

import os

from traffic_contracts.dynamo_store import WindowStore, RecordConflict


class RecommendationRepository:
    def __init__(self, *, resource=None, table_name=None):
        self.store = WindowStore(table_name or os.getenv("RECOMMENDATIONS_TABLE", "traffic_recommendations"),
                                 resource=resource)

    def put(self, recommendation):
        if (recommendation.get("recommendation_id")
                != recommendation.get("window_id", "") + "/recommendation/v1"):
            raise ValueError("recommendation_id does not match window_id")
        return self.store.put(recommendation)

    def get(self, intersection_id, recommendation_id):
        suffix = "/recommendation/v1"
        if not isinstance(recommendation_id, str) or not recommendation_id.endswith(suffix):
            raise ValueError("invalid recommendation_id")
        return self.store.get(intersection_id, recommendation_id[:-len(suffix)])

    def query(self, intersection_id, **kwargs):
        return self.store.query(intersection_id, **kwargs)
