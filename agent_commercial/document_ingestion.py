"""
GSAS Document Ingestion Agent
=============================

Uses OCR and LLM logic to extract GSAS compliance data from unstructured documents
like utility bills, waste invoices, and maintenance logs.
"""

import logging
import json
import uuid
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Union

try:
    import pytesseract
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

logger = logging.getLogger("arvis.gsas.ingestion")

@dataclass
class ExtractionResult:
    """The structured output of an AI document extraction."""
    document_id: str
    document_type: str  # utility_bill, waste_invoice, maintenance_log
    confidence: float
    data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    extracted_at: datetime = field(default_factory=datetime.now)
    flagged_for_review: bool = False

class OCRProcessor:
    """OCR processor for PDF/Image to text conversion."""
    
    def process(self, file_path: str) -> str:
        """The document's text, or "" when it can't be read. Never made-up text: an
        unreadable document is flagged for review, not filled in."""
        logger.info(f"Processing OCR for {file_path}")
        if not os.path.exists(file_path):
            logger.warning(f"OCR: {file_path} does not exist")
            return ""
        if file_path.lower().endswith((".txt", ".csv")):
            with open(file_path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        if not HAS_OCR:
            logger.warning("OCR: pytesseract is not installed — document flagged for review")
            return ""
        try:
            return pytesseract.image_to_string(Image.open(file_path)) or ""
        except Exception as e:
            logger.warning(f"OCR failed for {file_path}: {e} — document flagged for review")
            return ""

_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                         "dec"], 1)}
_AMOUNT = r"([\d][\d,]*(?:\.\d+)?)"


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _regex_extract(text: str, document_type: str) -> Dict[str, Any]:
    """What a bill or invoice says, from its text: numbers next to their units. {} when unclear."""
    t = text or ""
    if document_type == "utility_bill":
        out: Dict[str, Any] = {}
        m = re.search(_AMOUNT + r"\s*kwh", t, re.IGNORECASE)
        if m:
            out["utility"], out["consumption_kwh"] = "electricity", _num(m.group(1))
        m = re.search(_AMOUNT + r"\s*(?:m3|m³|cubic)", t, re.IGNORECASE)
        if m:
            out.setdefault("utility", "water")
            out["consumption_m3"] = _num(m.group(1))
        m = re.search(_AMOUNT + r"\s*(?:qar|qr)\b", t, re.IGNORECASE) or \
            re.search(r"(?:qar|qr)\s*" + _AMOUNT, t, re.IGNORECASE)
        if m:
            out["cost_qar"] = _num(m.group(1))
        m = re.search(r"\b(20\d\d)[-/](0[1-9]|1[0-2])\b", t) or \
            re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(20\d\d)\b", t, re.IGNORECASE)
        if m:
            g = m.groups()
            out["period"] = f"{g[0]}-{g[1]}" if g[0].isdigit() else f"{g[1]}-{_MONTHS[g[0][:3].lower()]:02d}"
        return out if ("consumption_kwh" in out or "consumption_m3" in out) and "period" in out else {}
    if document_type == "waste_invoice":
        breakdown = {k.lower(): _num(v) for k, v in
                     re.findall(r"(general|recycling|organic|mixed|hazardous)[^\d\n]{0,20}?" + _AMOUNT + r"\s*kg",
                                t, re.IGNORECASE)}
        m = re.search(r"\b(20\d\d-\d\d-\d\d)\b", t)
        if not breakdown or not m:
            return {}
        return {"waste_type": "mixed" if len(breakdown) > 1 else next(iter(breakdown)),
                "quantity_kg": sum(breakdown.values()), "breakdown": breakdown, "date": m.group(1)}
    return {}


class GSASDataExtractor:
    """Uses LLM to extract structured data from OCR text."""
    
    def __init__(self, llm_agent=None):
        self.llm_agent = llm_agent

    async def extract(self, text: str, document_type: str) -> ExtractionResult:
        """Structured extraction from text."""
        doc_id = str(uuid.uuid4())[:8]
        
        # Simulate LLM call
        logger.info(f"Extracting structured data from {document_type} using LLM")
        
        extracted_data = {}
        confidence = 0.95
        
        if self.llm_agent:
            try:
                prompt = f"Extract structured data from this {document_type} OCR text. \nText: {text}\n"
                if document_type == "utility_bill":
                    prompt += "Return JSON with keys: utility (e.g. electricity), consumption_kwh (float), cost_qar (float), period (YYYY-MM), provider."
                elif document_type == "waste_invoice":
                    prompt += "Return JSON with keys: waste_type (mixed/general/recycling), quantity_kg (float), breakdown (dict of type to float), disposal_method (recycling/landfill), contractor, date (YYYY-MM-DD)."
                
                response = await self.llm_agent.generate(prompt) 
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    extracted_data = json.loads(json_match.group(0))
            except Exception as e:
                logger.warning(f"LLM extraction failed: {e}. Falling back to regex.")
        
        # Without the language model: read what the text actually says. These results
        # always go to review — a pattern match is not trusted on its own.
        if not extracted_data:
            confidence = 0.7
            extracted_data = _regex_extract(text, document_type)

        flagged = confidence < 0.85 or not extracted_data
        
        return ExtractionResult(
            document_id=doc_id,
            document_type=document_type,
            confidence=confidence,
            data=extracted_data,
            flagged_for_review=flagged
        )

class IngestionManager:
    """Orchestrates the document ingestion pipeline."""
    
    def __init__(self, waste_tracker=None, energy_analyzer=None, database=None, meter_id: str = "MAIN"):
        self.database = database             # confirmed bills become monthly meter points
        self.meter_id = meter_id
        self.ocr = OCRProcessor()
        self.extractor = GSASDataExtractor()
        self.waste_tracker = waste_tracker
        self.energy_analyzer = energy_analyzer
        self.processed_docs: List[ExtractionResult] = []

    async def ingest_document(self, file_path: str, doc_type: str) -> Dict[str, Any]:
        """Process a document and update the relevant tracker."""
        # 1. OCR
        text = self.ocr.process(file_path)
        
        # 2. LLM Extraction
        result = await self.extractor.extract(text, doc_type)
        self.processed_docs.append(result)
        
        # 3. Update Domain Modules
        if not result.flagged_for_review:
            if doc_type == "waste_invoice" and self.waste_tracker:
                from agent_commercial.waste_tracker import WasteRecord
                from datetime import date
                
                # Update waste tracker
                for w_type, qty in result.data.get("breakdown", {}).items():
                    record = WasteRecord(
                        waste_type=w_type,
                        quantity_kg=qty,
                        disposal_method="recycling" if w_type == "recycling" else "landfill",
                        contractor=result.data.get("contractor", "Unknown"),
                        period_end=date.fromisoformat(result.data["date"]) if "date" in result.data else date.today(),
                        source="ocr_extract"
                    )
                    self.waste_tracker.add_record(record)
                    
            elif doc_type == "utility_bill" and self.database is not None and result.data.get("period"):
                # The bill's consumption becomes a monthly meter point (importers.utility_bills), so
                # what the utility charged can be checked against what the meters measured.
                from agent_commercial.importers.utility_bills import record_bill
                await record_bill(self.database, self.meter_id, result.data["period"],
                                  kwh=result.data.get("consumption_kwh"), m3=result.data.get("consumption_m3"),
                                  cost=result.data.get("cost_qar"))
        
        return {
            "status": "success" if not result.flagged_for_review else "pending_review",
            "document_id": result.document_id,
            "confidence": result.confidence,
            "extracted_data": result.data
        }
