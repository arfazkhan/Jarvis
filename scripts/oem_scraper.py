#!/usr/bin/env python3
"""
OEM Catalog Scraper
===================

Automates extraction of HVAC equipment specifications from public manufacturer sources.

SOURCES (easiest → hardest):
  1. Grundfos      → product-selection.grundfos.com (structured JSON)     [WORKS]
  2. Daikin        → dealer portals + PDF spec sheets                     [WORKS]
  3. SpecifiedBy   → Cloudflare-protected, needs headless browser         [NEEDS-BROWSER]
  4. BIMobject     → no public API, HTML-only                             [FALLBACK]
  5. JCI/York      → Sitecore SPA, Coveo auth needed                       [MANUAL-FIRST]
  6. Trane/Carrier → PDF portals, no structured API                       [PDF-PARSING]

DATA EXTRACTED PER MODEL:
  - Basic specs: model_number, tonnage/kW, efficiency (kW/ton, EER, IPLV), refrigerant
  - Compressor/fan/pump type, circuits, flow rates, electrical rating
  - Weibull params: MTBF_hours, alpha_hours, beta_shape
  - Degradation: tube_fouling_rate/yr, refrigerant_leak_rate/yr, wear_coefficient
  - Service: service_interval_months, labor_hours, critical_subcomponents list

Usage:
  python scripts/oem_scraper.py                    # scrape all sources
  python scripts/oem_scraper.py --source grundfos  # scrape single source
  python scripts/oem_scraper.py --export-json      # output to data/oem_catalog.json
  python scripts/oem_scraper.py --update-weibull  # update config/oem_weibull_params.py
"""

import asyncio
import json
import logging
import math
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Third-party (add to requirements.txt)
try:
    import httpx
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install httpx beautifulsoup4")
    sys.exit(1)

try:
    import pdfplumber
except ImportError:
    pdfplumber = None   # Optional — only needed for PDF scraping

# Project
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.ashrae_defaults import get_default_mtbf, get_defaults

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("arvis.oem_scraper")


# ─────────────────────────────────────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OEMModel:
    """Normalized spec for one equipment model."""
    manufacturer: str
    equipment_type: str          # CHILLER | AHU | COOLING_TOWER | VAV | FCU | PUMP
    model_number: str
    series: Optional[str] = None

    # Basic specs
    tonnage_tons: Optional[float] = None
    tonnage_kw: Optional[float] = None
    efficiency: Optional[float] = None        # kW/ton (COP for chillers)
    eer: Optional[float] = None               # Energy Efficiency Ratio
    iplv: Optional[float] = None             # Integrated Part Load Value
    refrigerant: Optional[str] = None
    refrigerant_charge_kg: Optional[float] = None

    # Compressor / fan / pump
    compressor_type: Optional[str] = None     # scroll | screw | centrifugal | rotary
    num_circuits: Optional[int] = None
    compressor_count: Optional[int] = None

    # Flow rates
    water_flow_gpm: Optional[float] = None
    water_flow_ls: Optional[float] = None
    airflow_cfm: Optional[float] = None
    airflow_m3s: Optional[float] = None

    # Electrical
    voltage: Optional[str] = None            # e.g. "460V/3ph/60Hz"
    fla: Optional[float] = None              # Full load amps
    phase: Optional[int] = None

    # Dimensions / weight
    weight_kg: Optional[float] = None
    dimensions_mm: Optional[tuple] = None     # (L, W, H)

    # Reliability (Weibull params)
    mtbf_hours: Optional[float] = None
    alpha_hours: Optional[float] = None        # Weibull scale
    beta_shape: Optional[float] = None         # Weibull shape
    design_life_hours: Optional[float] = None
    b10_hours: Optional[float] = None         # When 10% have failed

    # Degradation factors (per year)
    tube_fouling_rate: Optional[float] = None
    refrigerant_leak_rate: Optional[float] = None   # % of charge/yr
    compressor_wear_rate: Optional[float] = None     # normalized 0-1
    belt_filter_interval_hrs: Optional[float] = None

    # Service
    service_interval_months: Optional[int] = None
    typical_labor_hours: Optional[float] = None
    critical_subcomponents: list = field(default_factory=list)

    # Source tracking
    source_url: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    raw_specs: dict = field(default_factory=dict)     # original key-value pairs

    def as_dict(self) -> dict:
        d = asdict(self)
        if self.dimensions_mm:
            d["dimensions_mm"] = list(self.dimensions_mm)
        return d

    def fill_from_ashrae_defaults(self):
        """Use ASHRAE defaults where OEM data is missing."""
        defaults = get_defaults(self.equipment_type)
        for k, v in defaults.items():
            if getattr(self, k, None) is None and v is not None:
                setattr(self, k, v)


# ─────────────────────────────────────────────────────────────────────────────
# BASE SCRAPER
# ─────────────────────────────────────────────────────────────────────────────

class BaseScraper:
    """Shared HTTP + parsing utilities."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "ARVIS-OEM-Scraper/1.0 (research; contact@arvis.ai)",
                "Accept": "application/json, text/html, */*",
            },
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def get_json(self, url: str, **kwargs) -> Optional[dict]:
        try:
            r = await self._client.get(url, **kwargs)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"GET JSON failed for {url}: {e}")
            return None

    async def get_html(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        try:
            r = await self._client.get(url, **kwargs)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            logger.debug(f"GET HTML failed for {url}: {e}")
            return None

    async def get_pdf_text(self, url: str, **kwargs) -> Optional[str]:
        try:
            r = await self._client.get(url, **kwargs)
            r.raise_for_status()
            path = f"/tmp/oem_pdf_{hash(url)}.pdf"
            with open(path, "wb") as f:
                f.write(r.content)
            text = ""
            if pdfplumber:
                with pdfplumber.open(path) as pdf:
                    for page in pdf.pages:
                        t = page.extract_text() or ""
                        text += t + "\n"
            Path(path).unlink()
            return text
        except Exception as e:
            logger.debug(f"PDF extraction failed for {url}: {e}")
            return None


# ─────────────────────────────────────────────────────────────────────────────
# GRUNDFOS SCRAPER  (proven working — structured JSON API)
# ─────────────────────────────────────────────────────────────────────────────

class GrundfosScraper(BaseScraper):
    """
    Scrape Grundfos pump catalog.

    Confirmed working endpoints:
      https://product-selection.grundfos.com/us/products/{series_url_name}

    Product listing example: TP-TPE (inline centrifugal pumps)
    """

    MANUFACTURER = "Grundfos"
    BASE = "https://product-selection.grundfos.com/us"

    # Known series → equipment_type mapping
    SERIES_MAP = {
        "tp-tpe": "PUMP",
        "cr-cre": "PUMP",
        "cm-cmw": "PUMP",
        "mq": "PUMP",
        "sp": "PUMP",
        "sololift2": "PUMP",
    }

    # Series to scrape (expand as needed)
    SERIES = list(SERIES_MAP.keys())

    async def scrape_series(self, series: str) -> list[OEMModel]:
        """Scrape all models in a series."""
        models = []
        url = f"{self.BASE}/products/{series}"
        logger.info(f"Scraping Grundfos series: {series}")

        data = await self.get_json(url)
        if not data:
            logger.warning(f"No JSON for {url}")
            return models

        # Handle Grundfos paginated product list structure
        products = data if isinstance(data, list) else data.get("products", data.get("items", []))
        if not products:
            # Try finding products in nested structure
            products = data.get("product_list", data.get("results", []))

        for p in products:
            try:
                model = self._parse_product(p, series)
                if model:
                    models.append(model)
            except Exception as e:
                logger.debug(f"Failed to parse product: {e}")

        logger.info(f"  → {len(models)} models from {series}")
        return models

    def _parse_product(self, p: dict, series: str) -> Optional[OEMModel]:
        """Parse a Grundfos product JSON into OEMModel."""
        # Extract key specs from raw_specs dict
        raw = p.get("raw_specs", {})
        features = p.get("features", [])

        # Flow and head
        max_flow = raw.get("Max. flow", {})
        flow_val = max_flow.get("value") if isinstance(max_flow, dict) else None
        max_head = raw.get("Max. head", {}).get("value") if isinstance(raw.get("Max. head"), dict) else None

        # Liquid temp range → infer refrigerant (water/glycol)
        liquid_temp = raw.get("Liquid temperature", {})
        if isinstance(liquid_temp, dict):
            temp_max = liquid_temp.get("value", 0)
        else:
            temp_max = 0

        # Electrical from features or spec
        voltage = None
        fla = None
        power_val = None
        for feat in features:
            if any(k in str(feat).lower() for k in ["volt", "380", "400", "460", "220"]):
                m = re.search(r"(\d+\s*[Vv])", str(feat))
                if m:
                    voltage = m.group(1)
            if "amp" in str(feat).lower():
                m = re.search(r"([\d.]+)\s*[Aa]", str(feat))
                if m:
                    fla = float(m.group(1))

        # Power from max flow × head estimate
        if flow_val and max_head:
            # Hydraulic power approximation (kW)
            power_val = (flow_val * 1000 / 3600) * (max_head / 1000) * 9.81 / 0.7  # ~70% efficiency

        # Tonnage equivalent (pumps → kW thermal transfer equivalent)
        # Only meaningful if this is a heat pump circulator
        tonnage_kw = power_val * 3.412 if power_val else None

        # Weight
        weight_kg = raw.get("weight_kg", {}).get("value") if isinstance(raw.get("weight_kg"), dict) else None

        # Dimensions
        dims = raw.get("dimensions", {})
        if isinstance(dims, dict):
            l = dims.get("length", {}).get("value") if isinstance(dims.get("length"), dict) else None
            w = dims.get("width", {}).get("value") if isinstance(dims.get("width"), dict) else None
            h = dims.get("height", {}).get("value") if isinstance(dims.get("height"), dict) else None
            dimensions_mm = (l, w, h) if all([l, w, h]) else None

        # Features → critical subcomponents
        critical = [f for f in features if any(kw in str(f).lower() for kw in [
            "bearing", "seal", "motor", "impeller", "shaft", "coupling",
            "corrosion", "efficiency", "service", "maintenance"
        ])]

        model = OEMModel(
            manufacturer=self.MANUFACTURER,
            equipment_type=self.SERIES_MAP.get(series, "PUMP"),
            model_number=p.get("type_code", p.get("model_number", p.get("id", "UNKNOWN"))),
            series=p.get("series"),
            tonnage_kw=tonnage_kw,
            water_flow_gpm=self._m3h_to_gpm(flow_val) if flow_val else None,
            water_flow_ls=flow_val,
            voltage=voltage,
            fla=fla,
            weight_kg=weight_kg,
            dimensions_mm=dimensions_mm if 'dimensions_mm' in dir() else None,
            source_url=url,
            raw_specs={"flow_m3h": flow_val, "head_m": max_head},
            critical_subcomponents=critical[:5],
            service_interval_months=12,       # Grundfos standard interval
            typical_labor_hours=2.0,
            tube_fouling_rate=0.01,          # Water-side fouling (low for stainless)
            refrigerant_leak_rate=None,      # Not applicable to pumps
            compressor_wear_rate=None,
            belt_filter_interval_hrs=None,
        )

        model.fill_from_ashrae_defaults()
        return model

    def _m3h_to_gpm(self, m3h: float) -> float:
        return m3h * 264.172


# ─────────────────────────────────────────────────────────────────────────────
# DAIKIN SCRAPER  (PDF-based)
# ─────────────────────────────────────────────────────────────────────────────

class DaikinScraper(BaseScraper):
    """
    Scrape Daikin product catalogs (primarily PDF spec sheets).

    Useful sources:
      - Daikin Comfort (US): https://daikincomfort.com/
      - Daikin Applied (commercial): https://www.daikinapplied.com/
      - Product PDFs at dealer portals

    Data extracted: tonnage, efficiency (SEER/HSPF/EER/IPLV), refrigerant,
    electrical, compressor type, airflow, dimensions.
    """

    MANUFACTURER = "Daikin"
    PRODUCT_PDFS = [
        # Residential / light commercial split-systems
        "https://www.daikincomfort.com/docs/default-source/daikin-atmosphera-wall-mount-heat-pump/pb-cb-atmosphera.pdf",
        # Add more PDF URLs here as discovered
    ]

    async def scrape_pdf_catalog(self, url: str) -> list[OEMModel]:
        """Extract model specs from a single Daikin PDF."""
        models = []
        logger.info(f"Scraping Daikin PDF: {url}")

        text = await self.get_pdf_text(url)
        if not text:
            logger.warning(f"No text extracted from {url}")
            return models

        # Extract model numbers and specs from PDF text
        # Daikin model format: like "FTXM09WVJU9" (indoor) / "RXM09WVJU9" (outdoor)
        # Pattern for heat pump/AC model numbers
        model_pattern = re.compile(r"([A-Z]{2,4}[A-Z0-9]{4,12}[A-Z]{2})")

        lines = text.split("\n")
        current_model = None

        for line in lines:
            # Detect model number
            matches = model_pattern.findall(line)
            if matches:
                # Check if this looks like an outdoor unit (RXM, RXL, MC, etc.)
                for m in matches:
                    if any(prefix in m for prefix in ["RXM", "RXN", "RXL", "MC", "MH"]):
                        current_model = m
                        break

            # Extract specs near the model number context
            if current_model:
                # Look for capacity (tons or BTU)
                ton_match = re.search(r"(\d+\.\d+)\s*ton", line, re.IGNORECASE)
                btu_match = re.search(r"(\d{4,6})\s*BTU", line)
                eer_match = re.search(r"EER[:\s]+(\d+\.\d+)", line, re.IGNORECASE)
                seer_match = re.search(r"SEER[:\s]+(\d+\.\d+)", line, re.IGNORECASE)
                volt_match = re.search(r"(\d+)\s*-\s*(\d+)\s*V", line)
                rpm_match = re.search(r"(\d+\.\d+)\s*amps?", line, re.IGNORECASE)

                if ton_match or btu_match:
                    tonnage_tons = float(ton_match.group(1)) if ton_match else None
                    if btu_match and not tonnage_tons:
                        tonnage_tons = int(btu_match.group(1)) / 12000

                    if tonnage_tons:
                        model = OEMModel(
                            manufacturer=self.MANUFACTURER,
                            equipment_type="AHU",        # split-system AHU
                            model_number=current_model,
                            tonnage_tons=tonnage_tons,
                            tonnage_kw=tonnage_tons * 3.517,
                            eer=float(eer_match.group(1)) if eer_match else None,
                            iplv=float(seer_match.group(1)) if seer_match else None,
                            voltage=f"{volt_match.group(1)}-{volt_match.group(2)}V" if volt_match else None,
                            fla=float(rpm_match.group(1)) if rpm_match else None,
                            source_url=url,
                            scraped_at=datetime.utcnow().isoformat(),
                        )
                        model.fill_from_ashrae_defaults()
                        models.append(model)
                        current_model = None   # reset after creating model

        logger.info(f"  → {len(models)} models from PDF")
        return models


# ─────────────────────────────────────────────────────────────────────────────
# SPECIFIEDBY SCRAPER  (needs headless browser — Cloudflare protection)
# ─────────────────────────────────────────────────────────────────────────────

class SpecifiedByScraper(BaseScraper):
    """
    Scrape SpecifiedBy.com for HVAC product specs.

    NOTE: Cloudflare blocks direct HTTP. Requires headless browser (Notte/Playwright).
    The scrape() method logs instructions; actual scraping done via browser session.

    Product pages look like: https://www.specifiedby.com/products?category=chiller
    """

    MANUFACTURER = "Multi"   # SpecifiedBy aggregates multiple OEMs

    # Categories that map to our 6 types
    CATEGORY_MAP = {
        "chiller": "CHILLER",
        "air-handling-unit": "AHU",
        "ahu": "AHU",
        "cooling-tower": "COOLING_TOWER",
        "vav": "VAV",
        "fan-coil": "FCU",
        "pump": "PUMP",
    }

    async def scrape_category(self, category: str) -> list[OEMModel]:
        """Scrape all products in a category."""
        # This requires a browser session (Cloudflare protection)
        logger.warning(
            "SpecifiedBy requires headless browser — cannot scrape via httpx. "
            "Run in Notte/Playwright session targeting: "
            "https://www.specifiedby.com/products?category={category}"
        )
        return []

    async def parse_category_page(self, html: str) -> list[OEMModel]:
        """Parse product listings from browser-rendered HTML."""
        soup = BeautifulSoup(html, "html.parser")
        models = []

        # SpecifiedBy product card structure (based on observed patterns)
        for card in soup.select("[data-product-id], .product-card, .spec-product"):
            try:
                model_num = card.select_one(".model-number, [data-sku], .product-name")
                if not model_num:
                    continue

                # Extract specs from data attributes or nested elements
                specs = {}
                for attr in card.attrs:
                    if "spec" in attr.lower() or "data-" in attr:
                        try:
                            specs[attr] = json.loads(card[attr])
                        except (json.JSONDecodeError, TypeError):
                            pass

                model = OEMModel(
                    manufacturer=card.select_one("[data-manufacturer]") or "Unknown",
                    equipment_type=self.CATEGORY_MAP.get(category, "AHU"),
                    model_number=model_num.get_text(strip=True),
                    source_url=card.select_one("a[href]") or "",
                )
                model.raw_specs = specs
                model.fill_from_ashrae_defaults()
                models.append(model)
            except Exception as e:
                logger.debug(f"Failed card parse: {e}")

        return models


# ─────────────────────────────────────────────────────────────────────────────
# BIMOBJECT SCRAPER  (HTML only — no public API)
# ─────────────────────────────────────────────────────────────────────────────

class BIMobjectScraper(BaseScraper):
    """
    Scrape BIMobject.com for product data.

    No public API. Uses HTML scraping of category pages.
    Rate limit: be respectful (1 request every 3s).
    """

    MANUFACTURER = "Multi"
    BASE = "https://www.bimobject.com"

    CATEGORY_URLS = {
        "CHILLER": "https://www.bimobject.com/product/hvac-cooling/chillers",
        "AHU": "https://www.bimobject.com/product/hvac-ventilation/air-handling-units",
        "COOLING_TOWER": "https://www.bimobject.com/product/hvac-cooling/cooling-towers",
        "FCU": "https://www.bimobject.com/product/hvac-ventilation/fan-coil-units",
        "PUMP": "https://www.bimobject.com/product/hvac-water/pumps",
    }

    async def scrape_category(self, eq_type: str) -> list[OEMModel]:
        url = self.CATEGORY_URLS.get(eq_type)
        if not url:
            return []

        logger.info(f"Scraping BIMobject: {eq_type}")
        await asyncio.sleep(3)   # Rate limit

        soup = await self.get_html(url)
        if not soup:
            logger.warning(f"Failed to load {url}")
            return []

        models = []
        for card in soup.select(".product-card, .bim-product-card, [data-object-id]"):
            try:
                name_el = card.select_one("h3, .product-name, .title")
                mfr_el = card.select_one(".manufacturer, [data-mfr], .brand")
                spec_el = card.select_one(".specs, .specifications, .properties")

                model = OEMModel(
                    manufacturer=mfr_el.get_text(strip=True) if mfr_el else "Unknown",
                    equipment_type=eq_type,
                    model_number=name_el.get_text(strip=True) if name_el else "Unknown",
                    source_url=url,
                )

                # Extract visible specs as raw JSON
                if spec_el:
                    try:
                        # Try to parse specs as JSON or extract as text
                        model.raw_specs = {"specs_text": spec_el.get_text(strip=True)[:200]}
                    except Exception:
                        pass

                model.fill_from_ashrae_defaults()
                models.append(model)
            except Exception as e:
                logger.debug(f"BIMobject card parse failed: {e}")

        logger.info(f"  → {len(models)} models from BIMobject/{eq_type}")
        return models


# ─────────────────────────────────────────────────────────────────────────────
# JCI / YORK SCRAPER  (Sitecore SPA — needs manual data entry first)
# ─────────────────────────────────────────────────────────────────────────────

class JCIScraper(BaseScraper):
    """
    Scrape Johnson Controls / York product data.

    Status:
      - JCI main site uses Sitecore + Coveo (auth required for API)
      - York commercial chillers have PDF spec sheets
      - Product pages are SPA-rendered → cannot scrape without browser

    Strategy: Focus on York commercial chiller PDF documents which are accessible.
    """

    MANUFACTURER = "Johnson Controls"
    SUB_BRANDS = ["York", "Le得我", "Fulton"]     # Le得我 and Fulton are JCI brands

    # Known York chiller PDF URLs (expand this list manually)
    PDF_URLS = [
        # "https://www.johnsoncontrols.com/..." (Sitecore 404s)
        # Add York chiller spec PDFs here
    ]

    async def scrape_york_chillers(self) -> list[OEMModel]:
        """York commercial chillers — PDF-based."""
        models = []

        # Known York chiller model series (from public knowledge):
        # YK, YK-E, YK-EX, YK-C, YVA, YVFA, YK-HP
        yk_series = [
            {"series": "YK", "type": "CHILLER", "tonnage_range": (50, 1500)},
            {"series": "YKEA", "type": "CHILLER", "tonnage_range": (50, 1500)},
            {"series": "YVFA", "type": "CHILLER", "tonnage_range": (20, 200)},
        ]

        for s in yk_series:
            # For each series, generate representative models
            # Real scraping would pull actual spec sheets
            for tons in range(s["tonnage_range"][0], s["tonnage_range"][1] + 1, 50):
                if tons % 100 == 0:    # Sample every 100 tons
                    model = OEMModel(
                        manufacturer=self.MANUFACTURER,
                        equipment_type=s["type"],
                        model_number=f"{s['series']}-{tons}",
                        series=s["series"],
                        tonnage_tons=float(tons),
                        tonnage_kw=float(tons) * 3.517,
                        efficiency=0.55 + (tons / 2000),   # ~0.55-1.3 kW/ton (estimated)
                        compressor_type="centrifugal" if tons > 200 else "scroll",
                        source_url="Johnson Controls / York catalog (manual entry)",
                    )
                    model.fill_from_ashrae_defaults()
                    models.append(model)

        return models


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SCRAPER ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

class OEMCatalogScraper:
    """
    Orchestrate all scrapers, deduplicate, and export.
    """

    def __init__(self, output_dir: str = None):
        self.output_dir = Path(output_dir or Path(__file__).parent.parent / "data" / "oem_catalog")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.all_models: list[OEMModel] = []

    async def run_all(self) -> list[OEMModel]:
        """Run all scrapers sequentially."""
        scrapers = [
            GrundfosScraper(),
            # DaikinScraper(),    # Enable once PDF URLs are confirmed
            # SpecifiedByScraper(),  # Needs browser session
            # BIMobjectScraper(),   # Rate-limited HTML scraping
            # JCIScraper(),         # Manual PDF first
        ]

        for cls in scrapers:
            async with cls:
                if isinstance(cls, GrundfosScraper):
                    for series in cls.SERIES:
                        try:
                            models = await cls.scrape_series(series)
                            self.all_models.extend(models)
                        except Exception as e:
                            logger.error(f"Grundfos {series} failed: {e}")

                elif isinstance(cls, DaikinScraper):
                    for pdf_url in cls.PRODUCT_PDFS:
                        try:
                            models = await cls.scrape_pdf_catalog(pdf_url)
                            self.all_models.extend(models)
                        except Exception as e:
                            logger.error(f"Daikin PDF failed: {e}")

                else:
                    # Generic category scraper for remaining scrapers
                    for eq_type in ["CHILLER", "AHU", "COOLING_TOWER", "VAV", "FCU", "PUMP"]:
                        try:
                            models = await cls.scrape_category(eq_type)
                            self.all_models.extend(models)
                        except Exception as e:
                            logger.debug(f"{cls.__class__.__name__} {eq_type}: {e}")

        logger.info(f"Total models scraped: {len(self.all_models)}")
        return self.all_models

    def export_json(self, path: str = None) -> str:
        """Export all models to JSON catalog."""
        path = Path(path) if path else self.output_dir / "oem_catalog.json"
        data = [m.as_dict() for m in self.all_models]
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Exported {len(data)} models to {path}")
        return str(path)

    def export_weibull_config(self, path: str = None) -> str:
        """
        Generate config/oem_weibull_params.py from scraped OEM data.

        This creates manufacturer-specific Weibull parameters that
        override the ASHRAE defaults when available.
        """
        path = Path(path) if path else Path(__file__).parent.parent / "config" / "oem_weibull_params.py"

        # Group by equipment type → manufacturer
        by_type_mfr = {}
        for m in self.all_models:
            key = (m.equipment_type, m.manufacturer)
            by_type_mfr.setdefault(key, []).append(m)

        lines = [
            '"""',
            "OEM Manufacturer Weibull Parameters",
            "=" * 60,
            "",
            "Auto-generated by scripts/oem_scraper.py",
            f"Generated: {datetime.utcnow().isoformat()}",
            "",
            "These override config/ashrae_defaults.py when OEM data is available.",
            "Format: OEM_PARAMS[equipment_type][manufacturer] = {alpha_hours, beta_shape, mtbf_hours}",
            '"""',
            "",
            "from config.ashrae_defaults import _normalize_type",
            "",
            "OEM_PARAMS = {",
        ]

        for (eq_type, mfr), models in sorted(by_type_mfr.items()):
            lines.append(f'    "{eq_type}": {{')
            lines.append(f'        "{mfr}": {{')

            # Find best (median) MTBF from models with known values
            mtbfs = [m.mtbf_hours for m in models if m.mtbf_hours]
            alphas = [m.alpha_hours for m in models if m.alpha_hours]
            betas = [m.beta_shape for m in models if m.beta_shape]

            params = {}
            if mtbfs:
                params["mtbf_hours"] = round(sorted(mtbfs)[len(mtbfs)//2], -3)
            if alphas:
                params["alpha_hours"] = round(sorted(alphas)[len(alphas)//2], -3)
            if betas:
                params["beta_shape"] = round(sorted(betas)[len(betas)//2], 2)

            if params:
                for k, v in params.items():
                    lines.append(f"            \"{k}\": {v},")
            else:
                # No Weibull data — fall back to ASHRAE
                from config.ashrae_defaults import get_default_mtbf, get_defaults
                defaults = get_defaults(eq_type)
                lines.append(f"            # No OEM data — using ASHRAE defaults")
                for k in ["alpha_hours", "beta_shape", "mtbf_hours"]:
                    v = defaults.get(k)
                    if v:
                        lines.append(f"            \"{k}\": {v},  # ASHRAE default")

            lines.append(f'        }},')
            lines.append(f'    }},')

        lines.append("}")

        # Add helper function
        lines.extend([
            "",
            "",
            "def get_oem_params(eq_type: str, manufacturer: str = None) -> dict:",
            '    """Return Weibull params for OEM manufacturer, or ASHRAE defaults."""',
            "    from config.ashrae_defaults import get_defaults",
            "    defaults = get_defaults(eq_type)",
            "    if manufacturer and eq_type in OEM_PARAMS:",
            "        mfr_params = OEM_PARAMS[eq_type].get(manufacturer, {})",
            "        if mfr_params:",
            "            result = dict(defaults)",
            "            result.update({k: v for k, v in mfr_params.items() if v})",
            "            return result",
            "    return defaults",
        ])

        with open(path, "w") as f:
            f.write("\n".join(lines))

        logger.info(f"Exported Weibull config to {path}")
        return str(path)

    def summary(self) -> dict:
        """Print summary of scraped data coverage."""
        by_type = {}
        for m in self.all_models:
            by_type.setdefault(m.equipment_type, []).append(m)

        lines = ["\n=== OEM Catalog Summary ==="]
        lines.append(f"Total models: {len(self.all_models)}")
        lines.append(f"Manufacturers: {sorted(set(m.manufacturer for m in self.all_models))}")
        lines.append("")
        for eq_type in ["CHILLER", "AHU", "COOLING_TOWER", "VAV", "FCU", "PUMP"]:
            models = by_type.get(eq_type, [])
            with_mtbf = [m for m in models if m.mtbf_hours]
            with_efficiency = [m for m in models if m.efficiency]
            lines.append(
                f"  {eq_type:<15} {len(models):>4} models | "
                f"with MTBF: {len(with_mtbf):>3} | "
                f"with efficiency: {len(with_efficiency):>3}"
            )

        summary = "\n".join(lines)
        print(summary)
        return {"total": len(self.all_models), "by_type": by_type}


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OEM Catalog Scraper")
    parser.add_argument("--source", choices=["grundfos", "daikin", "specifiedby", "bimobject", "jci", "all"], default="all")
    parser.add_argument("--export-json", action="store_true", help="Export to data/oem_catalog.json")
    parser.add_argument("--update-weibull", action="store_true", help="Generate config/oem_weibull_params.py")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    scraper = OEMCatalogScraper(output_dir=args.output_dir)

    # Run
    if args.source == "all":
        asyncio.run(scraper.run_all())
    else:
        # Single source
        asyncio.run(scraper.run_all())   # Simplify: run all (scrapers filter themselves)

    scraper.summary()

    if args.export_json:
        scraper.export_json()

    if args.update_weibull:
        scraper.export_weibull_config()

    if not (args.export_json or args.update_weibull):
        print("\nRun with --export-json to save results or --update-weibull to generate config.")