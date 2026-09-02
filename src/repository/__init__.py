"""Repository abstractions for local paper metadata and evidence indexes."""

from .enterprise_versions import (
    DEFAULT_ENTERPRISE_VERSION_DIRECTORY,
    EnterpriseNeedVersionStore,
    new_need_id,
)

from .papers import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_METADATA_SEED_PATH,
    INGESTION_STATUSES,
    TAG_CATEGORIES,
    TAG_REVIEW_STATUSES,
    TAG_SOURCES,
    PaperCatalog,
    PaperRecord,
    PaperTag,
    WINDOWS_CATALOG_ALIAS,
    calculate_sha256,
    load_metadata_seed,
    sync_parsed_papers,
)
from .vector_index import EvidenceIndex

__all__ = [
    "DEFAULT_ENTERPRISE_VERSION_DIRECTORY",
    "EnterpriseNeedVersionStore",
    "DEFAULT_CATALOG_PATH",
    "DEFAULT_METADATA_SEED_PATH",
    "INGESTION_STATUSES",
    "TAG_CATEGORIES",
    "TAG_REVIEW_STATUSES",
    "TAG_SOURCES",
    "PaperCatalog",
    "PaperRecord",
    "PaperTag",
    "WINDOWS_CATALOG_ALIAS",
    "calculate_sha256",
    "load_metadata_seed",
    "sync_parsed_papers",
    "EvidenceIndex",
    "new_need_id",
]
