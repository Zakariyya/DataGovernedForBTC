from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GovernanceVersions:
    schema_version: str = "0.1.0"
    feature_version: str = "0.1.0"
    regime_version: str = "0.1.0"
    governance_version: str = "0.1.0"
