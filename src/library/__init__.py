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
from .paper_indexing import (
    IndexBatchResult,
    PaperIndexingService,
    build_library_chunks,
    load_parsed_paper,
)
from .paper_analysis import (
    DEFAULT_PAPER_REPORT_DIRECTORY,
    LOCAL_READING_VERSION,
    PaperAnalysisService,
    PaperReadingResult,
    render_reading_markdown,
    select_reading_evidence,
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
    "IndexBatchResult",
    "PaperIndexingService",
    "build_library_chunks",
    "load_parsed_paper",
    "DEFAULT_PAPER_REPORT_DIRECTORY",
    "LOCAL_READING_VERSION",
    "PaperAnalysisService",
    "PaperReadingResult",
    "render_reading_markdown",
    "select_reading_evidence",
]
