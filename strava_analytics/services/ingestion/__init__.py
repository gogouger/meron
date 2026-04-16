"""Ingestion providers: Strava CSV, Strava API, Apple Health."""

from dataclasses import dataclass, field


@dataclass
class IngestReport:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }
