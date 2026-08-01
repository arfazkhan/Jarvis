"""
Docling OCR Backend
===================

Structure-aware extraction via Docling. Runs locally, free per page, and
preserves tables/headings as markdown — the right primary backend for technical
equipment manuals. Docling processes the whole PDF in one pass, so this backend
implements the `extract_document` batch fast path rather than per-page OCR.

If docling is not installed, `available` is False and the extractor skips it.
"""

from __future__ import annotations

import logging
from typing import Optional

from agent_commercial.skills.backends.ocr_base import OCRBackend, PageOCRResult

logger = logging.getLogger("arvis.skills.ocr.docling")


class DoclingBackend(OCRBackend):
    name = "docling"

    def __init__(self) -> None:
        self._converter = None

    @property
    def available(self) -> bool:
        try:
            import docling  # noqa: F401
            return True
        except Exception:
            return False

    def _get_converter(self):
        if self._converter is None:
            from docling.document_converter import DocumentConverter
            self._converter = DocumentConverter()
        return self._converter

    def extract_document(self, pdf_path: str) -> Optional[list[PageOCRResult]]:
        """Convert the whole PDF, then split markdown back into per-page results.

        Docling emits one document; we map its page-level provenance to
        PageOCRResult where available, else fall back to a single combined page.
        """
        if not self.available:
            return None
        try:
            conv = self._get_converter()
            result = conv.convert(pdf_path)
            doc = result.document
        except Exception as e:
            logger.warning("Docling conversion failed for %s: %s", pdf_path, e)
            return None

        # Preferred: per-page export if the installed docling version supports it.
        pages: list[PageOCRResult] = []
        try:
            n_pages = len(getattr(doc, "pages", []) or [])
        except Exception:
            n_pages = 0

        if n_pages:
            for i in range(n_pages):
                page_no = i + 1
                try:
                    md = doc.export_to_markdown(page_no=page_no)
                except TypeError:
                    md = ""  # version without page_no kwarg; handled below
                except Exception as e:
                    logger.debug("Docling page %d export failed: %s", page_no, e)
                    md = ""
                if md:
                    pages.append(PageOCRResult(
                        page_no=page_no, text=md, backend=self.name,
                        confidence=self._heuristic_confidence(md),
                    ))
            if pages:
                return pages

        # Fallback: whole-document markdown as a single logical page. The
        # extractor will still render/escalate individual pages via fitz+vision
        # when it detects low density, so this remains useful.
        try:
            full_md = doc.export_to_markdown()
        except Exception as e:
            logger.warning("Docling full export failed: %s", e)
            return None
        return [PageOCRResult(
            page_no=0, text=full_md, backend=self.name,
            confidence=self._heuristic_confidence(full_md),
        )]

    def extract_page(self, png_bytes: bytes, page_no: int) -> PageOCRResult:
        # Docling works on documents, not loose page images. Signal "no result"
        # so the extractor escalates this page to the vision backend.
        return PageOCRResult(page_no=page_no, text="", backend=self.name, confidence=0.0)

    @staticmethod
    def _heuristic_confidence(text: str) -> float:
        """Cheap confidence proxy: printable-ratio and length.

        Real OCR confidence needs the engine's per-token scores; Docling does not
        surface those uniformly, so we use a density heuristic. Pages below the
        extractor's threshold get escalated to vision regardless.
        """
        t = text.strip()
        if not t:
            return 0.0
        printable = sum(c.isprintable() or c.isspace() for c in t)
        ratio = printable / max(len(t), 1)
        length_factor = min(len(t) / 400.0, 1.0)  # ~400 chars = a full page
        return round(0.5 * ratio + 0.5 * length_factor, 3)
