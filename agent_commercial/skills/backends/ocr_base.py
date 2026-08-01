"""
OCR Backend Interface
=====================

Pluggable OCR backends for the manual extractor. Each backend converts a single
rendered page image (PNG bytes) into text. The extractor decides per-page which
backend to use based on a text-density policy: Docling first (local, free), then
escalate low-yield pages to the LLM-vision backend.

Contract: a backend is a callable object exposing `.name`, `.available`, and
`extract_page(png_bytes, page_no) -> PageOCRResult`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PageOCRResult:
    """Result of OCR on one page."""
    page_no: int          # 1-indexed
    text: str
    backend: str          # which backend produced this
    confidence: float     # 0-1, backend's self-reported / heuristic confidence
    char_count: int = 0

    def __post_init__(self) -> None:
        if not self.char_count:
            self.char_count = len(self.text.strip())


class OCRBackend:
    """Base class for OCR backends. Subclasses override extract_page."""

    name: str = "base"

    @property
    def available(self) -> bool:
        """Whether this backend's dependencies are importable/usable."""
        return False

    def extract_page(self, png_bytes: bytes, page_no: int) -> PageOCRResult:
        raise NotImplementedError

    # Optional whole-document fast path. Backends that can process a PDF in one
    # shot (e.g. Docling) override this; returns None to signal "no batch path,
    # use per-page extract_page instead".
    def extract_document(self, pdf_path: str) -> Optional[list[PageOCRResult]]:
        return None
