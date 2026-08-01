"""
RapidOCR Backend
================

Primary OCR backend. RapidOCR runs on onnxruntime (NOT torch), so it works where
Docling's torch-based layout model fails on this platform. Per-page image OCR of
the fitz-rendered pages: local, free, no API key. Cracks scanned equipment
manuals (validated on the 228-page scanned Otis Gen2 manual).

Exposes real per-segment recognition scores, so confidence here is measured, not
heuristic. Diagram-heavy pages score low and get escalated to the vision backend
by the extractor.
"""

from __future__ import annotations

import io
import logging

from agent_commercial.skills.backends.ocr_base import OCRBackend, PageOCRResult

logger = logging.getLogger("arvis.skills.ocr.rapidocr")


class RapidOCRBackend(OCRBackend):
    name = "rapidocr"

    def __init__(self) -> None:
        self._engine = None

    @property
    def available(self) -> bool:
        try:
            import rapidocr  # noqa: F401
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401
            return True
        except Exception:
            return False

    def _get_engine(self):
        if self._engine is None:
            from rapidocr import RapidOCR
            self._engine = RapidOCR()
        return self._engine

    def extract_page(self, png_bytes: bytes, page_no: int) -> PageOCRResult:
        if not self.available:
            return PageOCRResult(page_no=page_no, text="", backend=self.name, confidence=0.0)
        try:
            import numpy as np
            from PIL import Image
            img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            arr = np.array(img)
            res = self._get_engine()(arr)
        except Exception as e:
            logger.warning("RapidOCR failed on page %d: %s", page_no, e)
            return PageOCRResult(page_no=page_no, text="", backend=self.name, confidence=0.0)

        txts = getattr(res, "txts", None) or []
        scores = getattr(res, "scores", None) or []
        text = "\n".join(str(t) for t in txts if t)
        # Confidence = mean recognition score, weighted toward having real content.
        if scores:
            try:
                mean_score = sum(float(s) for s in scores) / len(scores)
            except Exception:
                mean_score = 0.0
        else:
            mean_score = 0.0
        conf = round(mean_score, 3)
        return PageOCRResult(page_no=page_no, text=text, backend=self.name, confidence=conf)
