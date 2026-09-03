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
from .paper_figures import (
    DEFAULT_PAPER_ASSET_DIRECTORY,
    FIGURE_EXTRACTION_VERSION,
    FigureAsset,
    FigureExtractionResult,
    PaperFigureService,
)
from .paper_deep_reading import (
    DEEP_READING_VERSION,
    DEFAULT_DEEP_REPORT_DIRECTORY,
    DEFAULT_PAPER_ROUTE_DIRECTORY,
    DeepReadingResult,
    PaperDeepReadingService,
    build_deep_reading_prompt,
    render_deep_reading_markdown,
    select_formula_sources,
    validate_deep_reading,
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
    "DEFAULT_PAPER_ASSET_DIRECTORY",
    "FIGURE_EXTRACTION_VERSION",
    "FigureAsset",
    "FigureExtractionResult",
    "PaperFigureService",
    "DEEP_READING_VERSION",
    "DEFAULT_DEEP_REPORT_DIRECTORY",
    "DEFAULT_PAPER_ROUTE_DIRECTORY",
    "DeepReadingResult",
    "PaperDeepReadingService",
    "build_deep_reading_prompt",
    "render_deep_reading_markdown",
    "select_formula_sources",
    "validate_deep_reading",
]
