"""Pure Phase 5 recommendation rules; Kafka and storage are added in later steps."""

from .rules import recommend, validate_result

__all__ = ["recommend", "validate_result"]
