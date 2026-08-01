"""
Manual Extractor
================

Stage 1 of the manual→skill compiler. Converts an equipment manual PDF into
clean, page-marked text ready for structural analysis.

Policy (per page):
  1. If the PDF page has an embedded text layer (born-digital), use it directly
     via fitz — fastest and lossless.
  2. Otherwise render the page and OCR it with the primary backend (RapidOCR,
     onnxruntime-based, local, free). Validated on the scanned Otis Gen2 manual.
  3. If the page's yield is below the density threshold or its OCR confidence is
     low (diagrams, poor scans) AND a vision backend is configured, escalate that
     page to the LLM-vision backend and keep whichever result is richer.

Emit ExtractedManual: per-page text with source-page markers, plus metadata
(page count, char/token estimates, per-page backend + confidence, flagged pages).

Page markers are load-bearing: the grounding gate downstream requires every
extracted framework to cite a source page, so the extractor must preserve which
page each span of text came from.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agent_commercial.skills.backends.ocr_base import OCRBackend
from agent_commercial.skills.backends.rapidocr_backend import RapidOCRBackend
from agent_commercial.skills.backends.vision_backend import VisionBackend

logger = logging.getLogger("arvis.skills.extractor")

# A page yielding fewer usable chars than this is escalated to vision OCR.
DENSITY_ESCALATE_CHARS = 120
# OCR confidence below this also escalates, even if char count is ok.
CONFIDENCE_ESCALATE = 0.55
# Embedded text layer with at least this many chars = candidate born-digital.
EMBEDDED_TEXT_MIN = 60
# Minimum voweled-token ratio for embedded text to be trusted. Scanned PDFs
# often carry a GARBAGE embedded OCR layer (e.g. "CIFAR HOISTWAY .8/4 4−.5");
# real prose scores ~0.9, garbage scores low. Below this, we OCR the page fresh.
EMBEDDED_QUALITY_MIN = 0.6
# Need at least this many alpha tokens to judge quality at all.
EMBEDDED_MIN_TOKENS = 15
# Approx chars per token, for a cheap token estimate without a tokenizer.
CHARS_PER_TOKEN = 4
# Render resolution for OCR.
RENDER_DPI = 200


@dataclass
class ExtractedPage:
    page_no: int
    text: str
    backend: str
    confidence: float
    escalated: bool = False


@dataclass
class ExtractedManual:
    source_file: str
    source_hash: str
    page_count: int
    pages: list[ExtractedPage] = field(default_factory=list)
    char_count: int = 0
    token_estimate: int = 0
    backends_used: dict[str, int] = field(default_factory=dict)
    flagged_pages: list[int] = field(default_factory=list)  # low-confidence/empty

    def page_marked_text(self) -> str:
        """Full text with explicit page markers for the analyzer/grounding gate."""
        parts = []
        for p in self.pages:
            if p.text.strip():
                parts.append(f"\n\n===== PAGE {p.page_no} =====\n{p.text.strip()}")
        return "".join(parts).strip()

    def summary(self) -> dict:
        return {
            "source_file": self.source_file,
            "source_hash": self.source_hash[:12],
            "page_count": self.page_count,
            "char_count": self.char_count,
            "token_estimate": self.token_estimate,
            "backends_used": self.backends_used,
            "flagged_pages": len(self.flagged_pages),
            "pages_with_text": sum(1 for p in self.pages if p.text.strip()),
        }


class ManualExtractor:
    def __init__(
        self,
        primary: Optional[OCRBackend] = None,
        vision: Optional[VisionBackend] = None,
        render_dpi: int = RENDER_DPI,
    ) -> None:
        self.primary = primary if primary is not None else RapidOCRBackend()
        self.vision = vision if vision is not None else VisionBackend()
        self.render_dpi = render_dpi

    def extract(self, pdf_path: str, max_pages: Optional[int] = None) -> ExtractedManual:
        """Extract a manual. `max_pages` caps work for quick validation runs."""
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(pdf_path)

        source_hash = self._hash_file(path)

        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        page_count = doc.page_count
        limit = min(page_count, max_pages) if max_pages else page_count

        pages: list[ExtractedPage] = []
        backends_used: dict[str, int] = {}
        flagged: list[int] = []

        for i in range(limit):
            page_no = i + 1
            chosen = self._extract_page(doc, i, page_no)
            pages.append(chosen)
            backends_used[chosen.backend] = backends_used.get(chosen.backend, 0) + 1
            if not chosen.text.strip() or chosen.confidence < CONFIDENCE_ESCALATE:
                flagged.append(page_no)

        doc.close()

        char_count = sum(len(p.text) for p in pages)
        manual = ExtractedManual(
            source_file=str(path),
            source_hash=source_hash,
            page_count=page_count,
            pages=pages,
            char_count=char_count,
            token_estimate=char_count // CHARS_PER_TOKEN,
            backends_used=backends_used,
            flagged_pages=flagged,
        )
        logger.info("Extracted %s: %s", path.name, manual.summary())
        return manual

    def _extract_page(self, doc, index: int, page_no: int) -> ExtractedPage:
        # 1. Embedded text layer (born-digital) — lossless, no OCR — but ONLY if
        #    it passes a quality check. Scanned manuals frequently ship a garbage
        #    embedded OCR layer that must be ignored in favor of fresh OCR.
        embedded = ""
        try:
            embedded = doc[index].get_text().strip()
        except Exception:
            embedded = ""
        if len(embedded) >= EMBEDDED_TEXT_MIN and self._embedded_quality(embedded) >= EMBEDDED_QUALITY_MIN:
            return ExtractedPage(page_no, embedded, "embedded", 1.0)

        # 2. Primary OCR on the rendered page.
        png = self._render_page(doc, index)
        base = self.primary.extract_page(png, page_no) if self.primary.available else None
        base_text = base.text if base else ""
        base_conf = base.confidence if base else 0.0
        base_backend = base.backend if base else "none"

        needs_escalation = (
            len(base_text.strip()) < DENSITY_ESCALATE_CHARS
            or base_conf < CONFIDENCE_ESCALATE
        )
        # 3. Vision escalation (optional; only if a key is configured).
        if needs_escalation and self.vision.available:
            v = self.vision.extract_page(png, page_no)
            if len(v.text.strip()) > len(base_text.strip()):
                return ExtractedPage(page_no, v.text, v.backend, v.confidence, escalated=True)

        return ExtractedPage(page_no, base_text, base_backend, base_conf)

    @staticmethod
    def _embedded_quality(text: str) -> float:
        """Fraction of alpha tokens that contain a vowel — a cheap gibberish
        detector. Real English prose ~0.9; garbage OCR layers score far lower.
        Returns 0.0 when there are too few tokens to judge (forces OCR)."""
        import re
        toks = re.findall(r"[A-Za-z]{2,}", text)
        if len(toks) < EMBEDDED_MIN_TOKENS:
            return 0.0
        voweled = sum(1 for t in toks if re.search(r"[aeiouAEIOU]", t))
        return voweled / len(toks)

    def _render_page(self, doc, index: int) -> bytes:
        import fitz
        page = doc[index]
        zoom = self.render_dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return pix.tobytes("png")

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
