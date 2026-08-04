"""Import a text-based PDF into the shared reference library.

Administrative developer tool. Reference documents are application-managed and
read-only through ordinary HTTP APIs; this script is the supported import path.

Usage:

    python scripts/import_reference_document.py --file /path/to/reference.pdf --title "Title"
"""

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.application.dependencies import get_embedding_provider  # noqa: E402
from app.application.reference import import_reference_document  # noqa: E402
from app.infrastructure.database import async_session_factory  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import a text-based PDF into the shared reference library."
    )
    parser.add_argument("--file", required=True, help="Path to a local text-based PDF file")
    parser.add_argument("--title", required=True, help="Human-readable reference title")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        print(f"ERROR: reference file not found: {path}", file=sys.stderr)
        return 1
    if path.suffix.lower() != ".pdf":
        print(f"ERROR: reference file must be a PDF: {path}", file=sys.stderr)
        return 1

    try:
        async with async_session_factory() as db:
            document, created = await import_reference_document(
                db, path, args.title, get_embedding_provider()
            )
    except Exception as exc:  # controlled CLI failure output, never credentials/embeddings
        print(f"ERROR: import failed: {exc}", file=sys.stderr)
        return 1

    if created:
        print(
            f"Imported reference document: {document.title} "
            f"(id={document.id}, pages={document.page_count})"
        )
    else:
        print(
            f"Skipped: identical content already exists as reference document "
            f"{document.title} (id={document.id})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
