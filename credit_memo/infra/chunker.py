"""Convert a Document Intelligence result into flat chunk records."""

from __future__ import annotations

import re

TARGET_CHARS = 500


def _sanitize_id(value: str) -> str:
    """AI Search keys allow letters, digits, _ , - and = only."""
    return re.sub(r"[^A-Za-z0-9_\-=]", "_", value)


def chunk_di_result(di_result: dict, *, ticker: str, accession: str,
                    form: str, filing_date: str) -> list[dict]:
    chunks: list[dict] = []
    seq = 0

    # --- text chunks (flush on heading/title) --------------------------
    buffer: list[str] = []
    cur_heading = ""
    cur_page = None

    def flush() -> None:
        nonlocal buffer, seq
        if not buffer:
            return
        content = "\n".join(buffer).strip()
        if content:
            chunks.append({
                "id": _sanitize_id(f"{ticker}_{accession}_txt_{seq}"),
                "ticker": ticker,
                "accession": accession,
                "form": form,
                "filing_date": filing_date,
                "content": content,
                "content_type": "text",
                "page_number": cur_page,
            })
            seq += 1
        buffer = []

    for para in di_result.get("paragraphs", []):
        role = para.get("role")
        text = (para.get("content") or "").strip()
        if not text:
            continue
        if role in ("sectionHeading", "title"):
            flush()
            cur_heading = text
            cur_page = para.get("page_number")
            buffer = [cur_heading]
            continue
        if cur_page is None:
            cur_page = para.get("page_number")
        buffer.append(text)
        if sum(len(b) for b in buffer) >= TARGET_CHARS:
            flush()
            if cur_heading:
                buffer = [cur_heading]

    flush()

    # If DI produced no paragraphs (rare), chunk full_text directly.
    if not chunks and di_result.get("full_text"):
        full = di_result["full_text"]
        for i in range(0, len(full), TARGET_CHARS):
            piece = full[i:i + TARGET_CHARS].strip()
            if piece:
                chunks.append({
                    "id": _sanitize_id(f"{ticker}_{accession}_txt_{seq}"),
                    "ticker": ticker, "accession": accession, "form": form,
                    "filing_date": filing_date, "content": piece,
                    "content_type": "text", "page_number": None,
                })
                seq += 1

    # --- table chunks --------------------------------------------------
    tseq = 0
    for tbl in di_result.get("tables", []):
        rows: dict[int, dict[int, str]] = {}
        for cell in tbl.get("cells", []):
            rows.setdefault(cell["row"], {})[cell["col"]] = cell.get("content", "")
        lines = []
        for r in sorted(rows):
            cols = rows[r]
            lines.append(" | ".join(cols.get(c, "") for c in sorted(cols)))
        content = "\n".join(lines).strip()
        if content:
            chunks.append({
                "id": _sanitize_id(f"{ticker}_{accession}_tbl_{tseq}"),
                "ticker": ticker, "accession": accession, "form": form,
                "filing_date": filing_date, "content": content,
                "content_type": "table",
                "page_number": tbl.get("page_number"),
            })
            tseq += 1

    return chunks
