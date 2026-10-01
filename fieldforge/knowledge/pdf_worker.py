"""Disposable PDF-text worker. Parent controls deadline and consumes bounded JSON.

This is process isolation for reliability, NOT a security sandbox. No database
path is passed in. PDF actions, JavaScript, URLs and embedded files are not run.
"""

from __future__ import annotations

import io
import json
import logging
import sys

from fieldforge.knowledge.pdf_import import MAX_PAGES, MAX_PDF_BYTES, MAX_TEXT_CHARACTERS

MAX_STREAM_BYTES = 8 * 1024 * 1024


def _limits() -> bool:
    # POSIX-only limits; Windows still gets a disposable child and parent deadline
    # but not an equivalent peak-memory ceiling. Do not imply a universal sandbox.
    try:
        import resource
    except ImportError:
        return False
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    memory = 768 * 1024 * 1024
    hard = resource.getrlimit(resource.RLIMIT_AS)[1]
    if hard != resource.RLIM_INFINITY:
        memory = min(memory, hard)
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    return True


def extract(raw: bytes) -> dict[str, object]:
    import pypdf

    if not raw.startswith(b"%PDF-") or not 1 <= len(raw) <= MAX_PDF_BYTES:
        raise ValueError("invalid PDF input")
    reader = pypdf.PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported here. Use an authorized unencrypted copy; nothing imported.")
    count = len(reader.pages)
    if not 1 <= count <= MAX_PAGES:
        raise ValueError("PDF must contain 1–200 physical pages. Use a smaller document.")
    texts, total = [], 0
    for page in reader.pages:
        content = page.get_contents()
        if content is not None and len(content.get_data()) > MAX_STREAM_BYTES:
            raise ValueError("PDF page content exceeds the processing limit; nothing imported")
        text = page.extract_text() or ""
        if not isinstance(text, str) or "\x00" in text:
            raise ValueError("PDF returned unsupported text; nothing imported")
        total += len(text)
        if total > MAX_TEXT_CHARACTERS:
            raise ValueError("PDF text exceeds 1,500,000 characters; use a smaller document")
        texts.append(text)
    return {"pages": texts, "version": pypdf.__version__}


def main() -> int:
    logging.disable(logging.CRITICAL)
    try:
        limited = _limits()
        raw = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
        result = {**extract(raw), "memory_limited": limited}
    except ImportError:
        result = {"error": 'PDF dependency unavailable. Install the optional package with: py -m pip install ".[pdf]"'}
    except ValueError as exc:
        result = {"error": str(exc)[:500]}
    except Exception:
        result = {"error": "Could not extract this PDF safely within current limits. It may be malformed or unsupported. Nothing imported."}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
