"""Repository abstractions for local paper metadata and evidence indexes."""

from .papers import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_METADATA_SEED_PATH,
    INGESTION_STATUSES,
    PaperCatalog,
    PaperRecord,
    WINDOWS_CATALOG_ALIAS,
    calculate_sha256,
    load_metadata_seed,
    sync_parsed_papers,
)
from .vector_index import EvidenceIndex

__all__ = [
    "DEFAULT_CATALOG_PATH",
    "DEFAULT_METADATA_SEED_PATH",
    "INGESTION_STATUSES",
    "PaperCatalog",
    "PaperRecord",
    "WINDOWS_CATALOG_ALIAS",
    "calculate_sha256",
    "load_metadata_seed",
    "sync_parsed_papers",
    "EvidenceIndex",
]
