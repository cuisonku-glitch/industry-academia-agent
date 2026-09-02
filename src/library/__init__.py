"""Local-first paper library services."""

from .paper_library import (
    DEFAULT_LIBRARY_ROOT,
    DEFAULT_TAG_TAXONOMY_PATH,
    MAX_UPLOAD_BYTES,
    LibrarySyncResult,
    PaperLibraryService,
    UploadImportResult,
)
from .paper_ingestion import (
    DEFAULT_PARSED_PAPER_DIRECTORY,
    LIBRARY_PARSE_PIPELINE_VERSION,
    PaperIngestionService,
    ParseBatchResult,
)

__all__ = [
    "DEFAULT_LIBRARY_ROOT",
    "DEFAULT_TAG_TAXONOMY_PATH",
    "MAX_UPLOAD_BYTES",
    "LibrarySyncResult",
    "PaperLibraryService",
    "UploadImportResult",
    "DEFAULT_PARSED_PAPER_DIRECTORY",
    "LIBRARY_PARSE_PIPELINE_VERSION",
    "PaperIngestionService",
    "ParseBatchResult",
]
