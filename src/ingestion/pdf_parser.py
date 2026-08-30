import sys
from pathlib import Path

import pymupdf


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAPERS_DIR = PROJECT_ROOT / "data" / "raw" / "papers"


def parse_pdf(pdf_path: Path) -> dict:
    """Extract page-level text from one PDF file."""
    pdf_path = Path(pdf_path)

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file: {pdf_path}")

    pages = []

    with pymupdf.open(pdf_path) as document:
        if document.needs_pass:
            raise ValueError(f"PDF is password-protected: {pdf_path.name}")

        for page_number, page in enumerate(document, start=1):
            pages.append(
                {
                    "page": page_number,
                    "text": page.get_text("text").strip(),
                }
            )

    return {
        "file_name": pdf_path.name,
        "total_pages": len(pages),
        "pages": pages,
    }


def parse_papers(papers_dir: Path = DEFAULT_PAPERS_DIR) -> list[dict]:
    """Parse every PDF in a directory in a stable filename order."""
    papers_dir = Path(papers_dir)

    if not papers_dir.is_dir():
        raise NotADirectoryError(f"Papers directory does not exist: {papers_dir}")

    pdf_paths = sorted(
        (path for path in papers_dir.iterdir() if path.suffix.lower() == ".pdf"),
        key=lambda path: path.name.casefold(),
    )

    if not pdf_paths:
        raise FileNotFoundError(f"No PDF files found in: {papers_dir}")

    return [parse_pdf(pdf_path) for pdf_path in pdf_paths]


def print_summary(parsed_pdf: dict) -> None:
    """Print a small human-readable extraction summary."""
    pages = parsed_pdf["pages"]
    total_characters = sum(len(page["text"]) for page in pages)
    first_page_preview = pages[0]["text"][:300].replace("\n", " ")

    print(f"论文：{parsed_pdf['file_name']}")
    print(f"页数：{parsed_pdf['total_pages']}")
    print(f"正文字符：{total_characters}")
    print("第一页前 300 字：")
    print(first_page_preview or "[第一页未提取到文本]")


def main() -> None:
    """Parse the default paper directory and print validation summaries."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parsed_papers = parse_papers()

    for index, parsed_pdf in enumerate(parsed_papers):
        if index > 0:
            print("-" * 60)
        print_summary(parsed_pdf)


if __name__ == "__main__":
    main()
