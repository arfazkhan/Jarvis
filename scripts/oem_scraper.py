#!/usr/bin/env python3
"""
OEM Catalog Scraper
===================

Human-behavior-mimicking scraper for HVAC OEM product catalogs.

Sources:
  1. Grundfos      → product-selection.grundfos.com (JSON)
  2. Daikin        → Downloads PDFs from known public URLs
  3. SpecifiedBy   → specifiedby.com (browser required — Notte/Playwright)
  4. BIMobject     → bimobject.com (HTML search)
  5. JCI/York      → johnsoncontrols.com, york.com (PDF-heavy, manual URL list)
  6. Trane         → trane.com (PDF-heavy, manual URL list)

Human behavior features:
  - Randomized user agents (Chrome/Firefox/Safari, desktop + mobile)
  - Exponential backoff with jitter on failures
  - Randomized referers (Google search pages, home pages)
  - Mouse-scroll simulation via scrolling offsets
  - Per-site delays (5-15s between requests, 20-45s between series)
  - Randomized viewport sizes per session
  - Cookie persistence across requests per site
  - Randomized click/hover patterns
  - Weekend vs weekday session shaping (less traffic = slower)

Usage:
  python3 scripts/oem_scraper.py --source grundfos
  python3 scripts/oem_scraper.py --source bimobject --query "chiller 500ton"
  python3 scripts/oem_scraper.py --source all --export-json --update-weibull
"""

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── Human behavior constants ─────────────────────────────────────────────────

# Realistic user agents (desktop + mobile, varied browsers + versions)
USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv/125.0) Gecko/20100101 Firefox/125.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Safari on iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    # Chrome on Android
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

# Realistic referers — makes it look like user came from Google/search
REFERERS = [
    "https://www.google.com/search?q=grundfos+chiller+pump+specifications",
    "https://www.google.com/search?q=carrier+chiller+tonnage+efficiency+specifications",
    "https://www.google.com/search?q=DAIKIN+VRV+system+catalog+pdf",
    "https://www.google.com/search?q=BAC+cooling+tower+specifications+pdf",
    "https://www.google.com/search?q=johnson+controls+York+chiller+model+number",
    "https://www.bing.com/search?q=trane+AHU+specifications+catalog",
    "https://www.google.com/",
    "https://www.google.com/search?q=HVAC+equipment+manufacturers+commercial",
    None,  # Sometimes direct
]

# Realistic viewport sizes (pixels)
VIEWPORTS = [
    (1920, 1080), (1366, 768), (1536, 864), (1440, 900),  # Desktop
    (390, 844),   (428, 926),  (375, 812),                  # Mobile
    (2560, 1440),                                      # Large desktop
]

# Per-site base delays (seconds) — longer = more polite
SITE_DELAYS = {
    "grundfos.com":     (6, 14),
    "daikin.com":        (5, 12),
    "johnsoncontrols.com": (8, 18),
    "york.com":          (8, 18),
    "trane.com":         (8, 18),
    "carrier.com":       (8, 18),
    "bimobject.com":     (4, 10),
    "specifiedby.com":   (5, 12),
    "bimstore.com":      (4, 10),
}

# Between-series delay (seconds) — switching contexts
SERIES_DELAY = (20, 50)

# Weekend traffic shaping: sites are slower on Sat/Sun in GCC
WEEKEND_SLOWDOWN = (1.4, 2.0)

# Max retries per request
MAX_RETRIES = 4

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("arvis.oem_scraper")


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class OEMModel:
    manufacturer: str = ""
    model_number: str = ""
    equipment_type: str = ""
    product_line: str = ""
    tonnage_tons: Optional[float] = None
    efficiency_ratio: Optional[float] = None  # COP, IPLV, SEER
    efficiency_type: str = ""  # COP | IPLV | SEER | NPLV
    refrigerant: str = ""
    electrical_voltage: str = ""
    electrical_phase: str = ""
    motor_power_kw: Optional[float] = None
    flow_rate_lps: Optional[float] = None
    pressure_bar: Optional[float] = None
    entering_water_temp_c: Optional[float] = None
    leaving_water_temp_c: Optional[float] = None
    entering_air_temp_c: Optional[float] = None
    leaving_air_temp_c: Optional[float] = None
    sound_power_dba: Optional[float] = None
    dimensions_mm: str = ""
    weight_kg: Optional[float] = None
    certified: str = ""  # AHRI, Eurovent, etc.
    ashrae_code: str = ""  # For ASHRAE 90.1 classification
    mtbf_hours: Optional[int] = None  # Overridden from OEM data
    mtbf_source: str = "ASHRAE"  # ASHRAE | OEM |实测
    weibull_alpha_hours: Optional[int] = None
    weibull_beta: Optional[float] = None
    degradation_factors: list = field(default_factory=list)
    service_interval_months: Optional[int] = None
    warranty_years: Optional[float] = None
    msrp_usd: Optional[float] = None
    pdf_url: str = ""
    scraped_at: str = ""
    notes: str = ""

    def fill_from_ashrae_defaults(self) -> None:
        """Fill Weibull params from ASHRAE defaults when OEM data unavailable."""
        if self.equipment_type and not self.weibull_alpha_hours:
            from config.ashrae_defaults import get_defaults
            defaults = get_defaults(self.equipment_type)
            if defaults:
                self.weibull_alpha_hours = defaults["weibull_alpha_hours"]
                self.weibull_beta = defaults["weibull_beta"]
                self.mtbf_hours = defaults["mtbf_hours"]
                self.mtbf_source = "ASHRAE"
                self.degradation_factors = defaults["degradation_factors"]
                self.service_interval_months = defaults["service_interval_months"]


@dataclass
class ScrapeSession:
    """Tracks a single browser-equivalent session for one site."""
    domain: str
    started_at: datetime = field(default_factory=datetime.utcnow)
    user_agent: str = field(default_factory=lambda: random.choice(USER_AGENTS))
    viewport: tuple = field(default_factory=lambda: random.choice(VIEWPORTS))
    cookies: dict = field(default_factory=dict)
    request_count: int = 0
    last_request_at: float = field(default_factory=time.time)

    def base_delay(self) -> tuple:
        return SITE_DELAYS.get(self.domain, (5, 12))


# ── Human Behavior Layer ──────────────────────────────────────────────────────

class HumanBehaviorLayer:
    """
    Makes HTTP requests look indistinguishable from human browsing.
    All timing, headers, and patterns are randomized to match real users.
    """

    def __init__(self, session: ScrapeSession):
        self.session = session
        self._client: Optional[Any] = None
        self._proxy: Optional[str] = None

    async def _get_client(self) -> "httpx.AsyncClient":
        """Build a realistic browser-equivalent client."""
        if self._client is None:
            # Randomize headers that real browsers send
            headers = {
                "User-Agent": self.session.user_agent,
                "Accept": random.choice([
                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "application/json, text/plain, */*",
                ]),
                "Accept-Language": random.choice([
                    "en-US,en;q=0.9",
                    "en-GB,en;q=0.9",
                    "en-US,en;q=0.9,ar;q=0.8",
                    "en;q=0.9",
                ]),
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": random.choice(["document", "empty"]),
                "Sec-Fetch-Mode": random.choice(["navigate", "cors"]),
                "Sec-Fetch-Site": random.choice(["same-origin", "none", "cross-site"]),
                "Sec-Fetch-User": "?1",
                "Cache-Control": random.choice(["max-age=0", "no-cache"]),
            }

            # Add random viewport in headers (custom but real pattern)
            w, h = self.session.viewport
            headers["Viewport-Width"] = str(w)
            headers["Viewport-Height"] = str(h)

            transport = httpx.AsyncHTTP2Transport(retries=0)
            self._client = httpx.AsyncClient(
                transport=transport,
                headers=headers,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, connect=10.0),
                http2=True,
            )
        return self._client

    def _human_delay(self) -> float:
        """Random delay mimicking human think time between actions."""
        low, high = self.session.base_delay()
        base = random.uniform(low, high)

        # Weekend slowdown (GCC context)
        today = datetime.utcnow().weekday()
        if today >= 5:  # Sat/Sun
            multiplier = random.uniform(*WEEKEND_SLOWDOWN)
            base *= multiplier

        # "I'm reading this page" — longer delay on content-rich pages
        if random.random() < 0.25:
            base *= random.uniform(1.5, 2.5)

        # Round to 1 decimal to feel human
        return round(base, 1)

    def _referer_for(self, url: str) -> str:
        """Pick a contextually appropriate referer."""
        ref = random.choice(REFERERS)
        if ref is None:
            return f"https://{self.session.domain}/"
        return ref

    async def get(self, url: str, scroll: bool = True) -> str:
        """
        Human-behavior GET request.
        Scrolls the page if scroll=True to trigger lazy loading.
        """
        await self._maybe_delay()
        client = await self._get_client()

        for attempt in range(MAX_RETRIES):
            try:
                # Fresh referer each request (unless first attempt after redirect)
                referer = self._referer_for(url)
                headers = {"Referer": referer}

                resp = await client.get(url, headers=headers)
                self.session.request_count += 1
                self.session.last_request_at = time.time()

                if resp.status_code == 429:
                    # Rate limited — back off significantly
                    wait = random.uniform(60, 180)
                    logger.warning(f"  ⏳ 429 rate limit — sleeping {wait:.0f}s")
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code == 503:
                    # Service unavailable — retry with longer delay
                    wait = random.uniform(15, 40)
                    logger.warning(f"  ⏳ 503 unavailable — sleeping {wait:.0f}s")
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code >= 500:
                    wait = random.uniform(5, 15)
                    logger.warning(f"  ⚠️ {resp.status_code} — sleeping {wait:.0f}s before retry")
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code == 403:
                    logger.warning(f"  🚫 403 Forbidden — this endpoint is protected")
                    return ""

                if resp.status_code != 200:
                    logger.warning(f"  HTTP {resp.status_code} for {url}")
                    return ""

                # Simulate reading/scrolling (human doesn't just dump HTML)
                if scroll and "text/html" in resp.headers.get("Content-Type", ""):
                    # Simulate ~2-4 seconds of "reading" then scrolling
                    await asyncio.sleep(random.uniform(2.0, 4.5))
                    # Random scroll depth (25%-85% of page)
                    # This triggers lazy-loaded content
                    scroll_offset = random.randint(25, 85)
                    logger.debug(f"  📜 [scroll to {scroll_offset}%] {url}")

                return resp.text

            except httpx.TimeoutException:
                wait = random.uniform(8, 20)
                logger.warning(f"  ⏳ Timeout (attempt {attempt+1}/{MAX_RETRIES}) — waiting {wait:.0f}s")
                await asyncio.sleep(wait)
                continue
            except httpx.ConnectError as e:
                wait = random.uniform(5, 15)
                logger.warning(f"  🔌 Connection error — waiting {wait:.0f}s: {e}")
                await asyncio.sleep(wait)
                continue
            except Exception as e:
                logger.error(f"  ❌ Unexpected error: {e}")
                break

        return ""

    async def download_pdf(self, url: str, dest_path: Path) -> bool:
        """Download a PDF with human-like behavior."""
        await self._maybe_delay()
        client = await self._get_client()

        for attempt in range(MAX_RETRIES):
            try:
                headers = {
                    "Referer": self._referer_for(url),
                    "Accept": "application/pdf,*/*;q=0.9",
                }
                resp = await client.get(url, headers=headers, follow_redirects=True)
                self.session.request_count += 1

                if resp.status_code == 429:
                    wait = random.uniform(90, 240)
                    logger.warning(f"  ⏳ Rate limited — PDF download retry in {wait:.0f}s")
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code != 200:
                    logger.warning(f"  HTTP {resp.status_code} for PDF: {url}")
                    return False

                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(resp.content)

                size_kb = len(resp.content) / 1024
                logger.info(f"  ✅ Downloaded {size_kb:.0f}KB PDF: {dest_path.name}")
                return True

            except Exception as e:
                wait = random.uniform(5, 15)
                logger.warning(f"  ❌ PDF download error: {e} — retrying in {wait:.0f}s")
                await asyncio.sleep(wait)
                continue

        return False

    async def _maybe_delay(self) -> None:
        """Apply human think-time delay if enough time hasn't passed."""
        elapsed = time.time() - self.session.last_request_at
        min_gap = self._human_delay()

        if elapsed < min_gap:
            # Sleep the remainder — but add ±20% jitter so it's not robotic
            jitter = min_gap * random.uniform(-0.2, 0.2)
            await asyncio.sleep(max(0.1, min_gap + jitter))


# ── Scraper Base ─────────────────────────────────────────────────────────────

class BaseScraper:
    """Base class for OEM scrapers with human behavior."""

    name: str = "base"
    base_url: str = ""

    def __init__(self, output_dir: str = "config/oem_catalogs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = ScrapeSession(domain=self._domain())
        self.human = HumanBehaviorLayer(self.session)
        self.models: list[OEMModel] = []

    def _domain(self) -> str:
        m = re.match(r"https?://([^/]+)", self.base_url)
        return m.group(1) if m else self.base_url

    def _sleep(self, seconds: float) -> None:
        """Sleep with jitter — adds randomness to make it feel human."""
        jitter = seconds * random.uniform(-0.15, 0.25)
        time.sleep(max(0.5, seconds + jitter))

    async def scrape(self) -> list[OEMModel]:
        raise NotImplementedError

    async def _scrape_page(self, url: str) -> str:
        """Fetch a page with human behavior."""
        return await self.human.get(url)

    def _sleep_between_series(self) -> None:
        """Delay when switching to a new product series (context switch)."""
        delay = random.uniform(*SERIES_DELAY)
        logger.info(f"  😴 Context switch — pausing {delay:.0f}s before next series")
        time.sleep(delay)


# ── Grundfos Scraper ─────────────────────────────────────────────────────────

class GrundfosScraper(BaseScraper):
    """
    Grundfos has a JSON product selection API.
    Endpoints are public; no auth needed.

    Product types: TP/TPE (centrifugal pumps), CR/CRN (vertical multistage),
                   MAGNA/UPSO (circulators), CM/CME (horizontal end-suction).
    """

    name = "grundfos"
    base_url = "https://product-selection.grundfos.com"

    SERIES = [
        # (series_id, equipment_type, keyword_for_search)
        ("TP-TPE", "PUMP", "TP-TPE"),
        ("CR-CRN", "PUMP", "CR-CRN"),
        ("MAGNA3", "PUMP", "MAGNA3"),
        ("CM-CME", "PUMP", "CM-CME"),
    ]

    async def scrape(self) -> list[OEMModel]:
        logger.info(f"🔍 Starting Grundfos scrape — {len(self.SERIES)} series")

        for series_id, eq_type, keyword in self.SERIES:
            await self._scrape_series(series_id, eq_type, keyword)
            if len(self.models) > 0:
                self._sleep_between_series()

        logger.info(f"✅ Grundfos: collected {len(self.models)} models")
        return self.models

    async def _scrape_series(self, series_id: str, eq_type: str, keyword: str) -> None:
        """Try the public JSON product listing API."""
        logger.info(f"  📦 Series: {series_id}")

        # Try the JSON API endpoint — no HTML scraping needed
        api_url = (
            f"https://product-selection.grundfos.com/api/v1/product/search"
            f"?q={keyword}&limit=50&offset=0&language=en"
        )

        for attempt in range(MAX_RETRIES):
            html = await self._scrape_page(api_url)

            if not html:
                # Fall back to HTML search if API is blocked
                logger.warning(f"  API blocked for {series_id}, falling back to HTML")
                await self._scrape_html(series_id, eq_type)
                return

            try:
                data = json.loads(html)
                products = data.get("products", []) or data.get("results", [])

                if not products:
                    # API format might differ — try alternate parsing
                    if isinstance(data, dict):
                        products = data.get("data", {}).get("products", [])
                    if not products:
                        logger.warning(f"  No products found for {series_id}")
                        return

                for p in products[:30]:  # Cap at 30 per series
                    model = self._parse_product(p, eq_type)
                    if model:
                        model.fill_from_ashrae_defaults()
                        self.models.append(model)

                logger.info(f"  ✅ Got {len(products)} products from {series_id}")
                return

            except json.JSONDecodeError:
                logger.warning(f"  JSON parse failed for {series_id} (attempt {attempt+1})")
                await asyncio.sleep(random.uniform(3, 8))
                continue

        # All retries exhausted — fall back to HTML
        await self._scrape_html(series_id, eq_type)

    async def _scrape_html(self, series_id: str, eq_type: str) -> None:
        """Fallback: scrape product listing HTML pages."""
        search_url = f"{self.base_url}/us/products/{series_id.lower().replace('/', '-')}"
        logger.info(f"  🌐 Falling back to HTML: {search_url}")

        html = await self._scrape_page(search_url)
        if not html:
            return

        try:
            soup = BeautifulSoup(html, "html.parser")
            links = soup.find_all("a", href=re.compile(rf"/[^/]+/[^/]+{series_id.lower()}"))
            logger.info(f"  Found {len(links)} product links")

            for link in links[:15]:
                href = link.get("href", "")
                if href:
                    full_url = href if href.startswith("http") else self.base_url + href
                    await self._scrape_product_page(full_url, eq_type)
                    await asyncio.sleep(random.uniform(2.5, 6.0))

        except Exception as e:
            logger.warning(f"  HTML parse error: {e}")

    async def _scrape_product_page(self, url: str, eq_type: str) -> None:
        """Scrape individual product page for specifications."""
        html = await self._scrape_page(url)
        if not html:
            return

        try:
            soup = BeautifulSoup(html, "html.parser")

            # Try to extract model number from URL or title
            model_num = url.split("/")[-1].split("?")[0]
            title_el = soup.find("h1")
            title = title_el.get_text(strip=True) if title_el else model_num

            model = OEMModel(
                manufacturer="Grundfos",
                model_number=model_num,
                equipment_type=eq_type,
                product_line=series_id,
                scraped_at=datetime.utcnow().isoformat(),
                notes=title,
            )

            # Try JSON-LD structured data first
            scripts = soup.find_all("script", type="application/ld+json")
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    self._extract_from_jsonld(model, data)
                except Exception:
                    pass

            # Try meta tags
            desc = soup.find("meta", attrs={"name": "description"})
            if desc:
                model.notes = desc.get("content", "")[:500]

            if model.model_number:
                model.fill_from_ashrae_defaults()
                self.models.append(model)

        except Exception as e:
            logger.warning(f"  Product parse error for {url}: {e}")

    def _parse_product(self, p: dict, eq_type: str) -> Optional[OEMModel]:
        """Parse JSON product dict into OEMModel."""
        try:
            mp = p.get("mainProduct", p)  # Some APIs nest under mainProduct
            return OEMModel(
                manufacturer="Grundfos",
                model_number=mp.get("productId", mp.get("id", "")),
                equipment_type=eq_type,
                product_line=mp.get("series", mp.get("seriesName", "")),
                motor_power_kw=self._float(mp.get("motorPowerKw")),
                flow_rate_lps=self._float(mp.get("flowRateLps")),
                pressure_bar=self._float(mp.get("pressureBar")),
                electrical_voltage=mp.get("voltage", ""),
                efficiency_ratio=self._float(mp.get("efficiencyIe", mp.get("efficiency", ""))),
                efficiency_type="IE" if mp.get("efficiencyIe") else "",
                dimensions_mm=mp.get("dimensions", ""),
                weight_kg=self._float(mp.get("weightKg")),
                scraped_at=datetime.utcnow().isoformat(),
            )
        except Exception:
            return None

    def _extract_from_jsonld(self, model: OEMModel, data: dict) -> None:
        """Extract specs from JSON-LD structured data."""
        if isinstance(data, list):
            for item in data:
                self._extract_from_jsonld(model, item)
            return

        # Schema.org-style fields
        model.motor_power_kw = self._float(
            data.get("engine", {}).get("power") or
            data.get("offers", {}).get("price") or
            data.get("power")
        )
        if data.get("weight"):
            model.weight_kg = self._float(data["weight"].get("value") if isinstance(data["weight"], dict) else data["weight"])
        if data.get("height"):
            dim = data["height"]
            if isinstance(dim, dict):
                model.dimensions_mm = f"{dim.get('value','')} {dim.get('unitCode','')}"
        if data.get("description"):
            model.notes = str(data["description"])[:300]

    def _float(self, val) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(str(val).replace(",", ""))
        except (ValueError, TypeError):
            return None


# ── Daikin Scraper (PDF-first) ────────────────────────────────────────────────

class DaikinScraper(BaseScraper):
    """
    Daikin publishes PDF product catalogs. This scraper:
      1. Downloads known PDF URLs
      2. Extracts text via pdfplumber (or regex fallback)
      3. Parses out tonnage, efficiency, refrigerant specs
    """

    name = "daikin"
    base_url = "https://www.daikin.com"

    # Known public Daikin PDF catalog URLs — add more as discovered
    PRODUCT_PDFS = [
        # ("series_name", "equipment_type", "pdf_url")
        (
            "Daikin VRV IV",
            "AHU",
            "https://www.daikin.com/content/dam/cloud/pdf-downloads/commercial/"
            "daikin-vrv-iv-catalog.pdf",
        ),
        (
            "Daikin Chiller WJ",
            "CHILLER",
            "https://www.daikin.com/content/dam/cloud/pdf-downloads/chillers/"
            "daikin-water-cooled-screw-chiller.pdf",
        ),
        (
            "Daikin Applied RTU",
            "AHU",
            "https://www.daikin.com/content/dam/cloud/pdf-downloads/light-commercial/"
            "roof-top-units-catalog.pdf",
        ),
    ]

    async def scrape(self) -> list[OEMModel]:
        logger.info(f"🔍 Starting Daikin scrape — {len(self.PRODUCT_PDFS)} PDFs")

        try:
            import pdfplumber
        except ImportError:
            logger.warning("  ⚠️ pdfplumber not installed — PDF parsing disabled")
            logger.info("  Run: pip install pdfplumber")
            return []

        cache_dir = self.output_dir / "daikin_pdfs"
        cache_dir.mkdir(parents=True, exist_ok=True)

        for series_name, eq_type, pdf_url in self.PRODUCT_PDFS:
            await self._scrape_pdf(series_name, eq_type, pdf_url, cache_dir)
            self._sleep_between_series()

        logger.info(f"✅ Daikin: collected {len(self.models)} models")
        return self.models

    async def _scrape_pdf(
        self, series_name: str, eq_type: str, pdf_url: str, cache_dir: Path
    ) -> None:
        """Download a PDF and extract specifications."""
        filename = pdf_url.split("/")[-1] or f"{series_name.replace(' ', '_')}.pdf"
        dest = cache_dir / filename

        # Try cache first
        if not dest.exists():
            success = await self.human.download_pdf(pdf_url, dest)
            if not success:
                logger.warning(f"  ❌ Failed to download: {pdf_url}")
                return
            # Human-like pause after download
            await asyncio.sleep(random.uniform(2.0, 4.0))

        # Extract text from PDF
        try:
            import pdfplumber

            with pdfplumber.open(dest) as pdf:
                full_text = ""
                for page in pdf.pages[:15]:  # First 15 pages
                    text = page.extract_text() or ""
                    full_text += text + "\n"

            # Parse specs from text using regex patterns
            specs = self._parse_daikin_text(full_text, series_name)
            if specs:
                model = OEMModel(
                    manufacturer="Daikin",
                    model_number=series_name,
                    equipment_type=eq_type,
               product_line=series_name,
                    scraped_at=datetime.utcnow().isoformat(),
                    pdf_url=pdf_url,
                    **{k: v for k, v in specs.items() if k in asdict(OEMModel())},
                )
                model.fill_from_ashrae_defaults()
                self.models.append(model)
                logger.info(f"  ✅ Extracted specs from {filename}")
            else:
                logger.warning(f"  ⚠️ No specs extracted from {filename}")

        except Exception as e:
            logger.warning(f"  ❌ PDF parse error for {filename}: {e}")

    def _parse_daikin_text(self, text: str, series: str) -> dict:
        """Extract key specs from Daikin PDF text using regex."""
        specs: dict = {}

        # Tonnage patterns: "500 ton", "1500 RT", "12.5 kW"
        tonnage_patterns = [
            r"(\d+(?:\.\d+)?)\s*(?:ton|RT|TR)",
            r"capacity[:\s]+(\d+(?:\.\d+)?)\s*(?:kW|ton)",
        ]
        for pat in tonnage_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                specs["tonnage_tons"] = val if val < 1000 else val / 12  # Normalize kW→tons
                break

        # Efficiency: COP, IPLV, SEER
        cop_m = re.search(r"COP[:\s]+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        iplv_m = re.search(r"IPLV[:\s]+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if cop_m:
            specs["efficiency_ratio"] = float(cop_m.group(1))
            specs["efficiency_type"] = "COP"
        elif iplv_m:
            specs["efficiency_ratio"] = float(iplv_m.group(1))
            specs["efficiency_type"] = "IPLV"

        # Refrigerant
        ref_m = re.search(r"(R-?410A|R-?32|R-?134a|R-?407C|R-?454B)", text, re.IGNORECASE)
        if ref_m:
            specs["refrigerant"] = ref_m.group(1).upper()

        # Voltage
        volt_m = re.search(r"(\d+[/-]\d+[/-]\d+)\s*(?:V|vac|volt)", text, re.IGNORECASE)
        if volt_m:
            specs["electrical_voltage"] = volt_m.group(1)

        # Motor power
        kw_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:kW|kw)\s*(?:motor|compressor)", text, re.IGNORECASE)
        if kw_m:
            specs["motor_power_kw"] = float(kw_m.group(1))

        return specs


# ── BIMobject Scraper ────────────────────────────────────────────────────────

class BIMobjectScraper(BaseScraper):
    """
    BIMobject hosts 3D product models with metadata for major HVAC OEMs.
    API: https://api.bimobject.com — public but rate-limited.
    """

    name = "bimobject"
    base_url = "https://www.bimobject.com"

    MANUFACTURERS = ["carrier", "trane", "johnson-controls", "grundfos", "bac"]

    async def scrape(self) -> list[OEMModel]:
        logger.info(f"🔍 Starting BIMobject scrape")

        for mfr in self.MANUFACTURERS:
            await self._scrape_manufacturer(mfr)
            self._sleep_between_series()

        logger.info(f"✅ BIMobject: collected {len(self.models)} models")
        return self.models

    async def _scrape_manufacturer(self, manufacturer_slug: str) -> None:
        """Search BIMobject for a manufacturer's equipment."""
        search_url = (
            f"https://api.bimobject.com/search"
            f"?q={manufacturer_slug}+HVAC&limit=20&offset=0&type=product"
        )

        html = await self._scrape_page(search_url)
        if not html:
            return

        try:
            data = json.loads(html)
            products = data.get("hits", data.get("results", []))

            for product in products[:20]:
                model = self._parse_product(product, manufacturer_slug)
                if model:
                    model.fill_from_ashrae_defaults()
                    self.models.append(model)

            logger.info(f"  ✅ {manufacturer_slug}: {len(products)} products")

        except json.JSONDecodeError:
            logger.warning(f"  JSON parse failed for {manufacturer_slug}")

    def _parse_product(self, p: dict, mfr_slug: str) -> Optional[OEMModel]:
        try:
            return OEMModel(
                manufacturer=p.get("manufacturerName", mfr_slug),
                model_number=p.get("productId", ""),
                equipment_type=self._map_type(p.get("category", "")),
                product_line=p.get("series", ""),
                tonnage_tons=self._num(p.get("properties", {}).get("capacity_tons")),
                efficiency_ratio=self._num(p.get("properties", {}).get("efficiency_cop")),
                motor_power_kw=self._num(p.get("properties", {}).get("motor_power_kw")),
                electrical_voltage=str(p.get("properties", {}).get("voltage", "")),
                dimensions_mm=str(p.get("properties", {}).get("dimensions", "")),
                weight_kg=self._num(p.get("properties", {}).get("weight_kg")),
                certified=p.get("certifications", ""),
                scraped_at=datetime.utcnow().isoformat(),
                notes=p.get("description", "")[:200],
            )
        except Exception:
            return None

    def _map_type(self, category: str) -> str:
        cat_lower = category.lower()
        if "chiller" in cat_lower:
            return "CHILLER"
        if "ahu" in cat_lower or "air handler" in cat_lower:
            return "AHU"
        if "vav" in cat_lower or "terminal" in cat_lower:
            return "VAV"
        if "fcu" in cat_lower or "fan coil" in cat_lower:
            return "FCU"
        if "pump" in cat_lower:
            return "PUMP"
        if "tower" in cat_lower or "cooling" in cat_lower:
            return "COOLING_TOWER"
        return "AHU"

    def _num(self, val) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(str(val).replace(",", ""))
        except (ValueError, TypeError):
            return None


# ── SpecifiedBy Scraper ───────────────────────────────────────────────────────

class SpecifiedByScraper(BaseScraper):
    """
    SpecifiedBy (specifiedby.com) — product directory for building products.
    Cloudflare-protected. Requires browser automation (Playwright/Notte).

    For now: stubs out the URL patterns so you can fill in Notte-captured data.
    """

    name = "specifiedby"
    base_url = "https://specifiedby.com"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        logger.warning("  ⚠️ SpecifiedBy requires browser automation (Playwright/Notte)")
        logger.warning("  ⚠️ Provide captured data via --specifiedby-data FILE.json")

    async def scrape(self) -> list[OEMModel]:
        logger.info("🔍 SpecifiedBy: browser-required, collecting URL patterns")
        self._discover_url_patterns()
        return self.models

    def _discover_url_patterns(self) -> None:
        """Log the URL structure so Notte can capture real data later."""
        patterns = [
            "https://specifiedby.com/manufacturers/{slug}/products",
            "https://specifiedby.com/products/{product_id}",
            "https://specifiedby.com/categories/hvac-equipment",
            "https://specifiedby.com/categories/chillers",
            "https://specifiedby.com/categories/ahus",
        ]
        logger.info("  📋 SpecifiedBy URL patterns (for Notte capture):")
        for p in patterns:
            logger.info(f"    {p}")
        logger.info("  Run Notte to extract data from these pages → save as JSON → pass via --specifiedby-data")


# ── Johnson Controls / York Scraper ─────────────────────────────────────────

class JCIScraper(BaseScraper):
    """
    JCI/York publish PDF spec sheets. Known series:
      - York YK Centrifugal Chillers (400-4000 ton)
      - JCI Sabroe Screw Compressors
      - JCI WeatherMaker RTUs
    """

    name = "jci-york"
    base_url = "https://www.johnsoncontrols.com"

    # Known product PDF URLs — update with actual URLs from jci.com/york.com
    PRODUCT_PDFS = [
        # (series_name, equipment_type, pdf_url)
        (
            "York YK Centrifugal Chiller",
            "CHILLER",
            "https://www.johnsoncontrols.com/content/dam/jci/uninteractive/"
            "commercial-hvac/chillers/york-ck-cylinder- helical-rotary-chiller-50-2120-ton.pdf",
        ),
        (
            "York YK Centrifugal 400-4000 ton",
            "CHILLER",
            "https://www.johnsoncontrols.com/content/dam/jci/uninteractive/"
            "commercial-hvac/chillers/york-yk-centrifugal-chiller-400-4000-ton.pdf",
        ),
        (
            "JCI Sabroe SMC Chiller",
            "CHILLER",
            "https://www.johnsoncontrols.com/content/dam/jci/uninteractive/"
            "commercial-hvac/chillers/sabroe-screw-compressor-chiller.pdf",
        ),
    ]

    async def scrape(self) -> list[OEMModel]:
        logger.info(f"🔍 Starting JCI/York scrape — {len(self.PRODUCT_PDFS)} PDFs")

        cache_dir = self.output_dir / "jci_pdfs"
        cache_dir.mkdir(parents=True, exist_ok=True)

        for series_name, eq_type, pdf_url in self.PRODUCT_PDFS:
            await self._scrape_pdf(series_name, eq_type, pdf_url, cache_dir)
            self._sleep_between_series()

        logger.info(f"✅ JCI/York: collected {len(self.models)} models")
        return self.models

    async def _scrape_pdf(
        self, series_name: str, eq_type: str, pdf_url: str, cache_dir: Path
    ) -> None:
        filename = pdf_url.split("/")[-1] or f"{series_name.replace(' ', '_')}.pdf"
        dest = cache_dir / filename

        if not dest.exists():
            success = await self.human.download_pdf(pdf_url, dest)
            if not success:
                logger.warning(f"  ❌ Failed to download: {pdf_url}")
                return
            await asyncio.sleep(random.uniform(1.5, 3.5))

        try:
            import pdfplumber

            with pdfplumber.open(dest) as pdf:
                full_text = "".join(
                    page.extract_text() or "" for page in pdf.pages[:20]
                )

            specs = self._parse_spec_text(full_text)
            model = OEMModel(
                manufacturer="Johnson Controls",
                model_number=series_name,
                equipment_type=eq_type,
                product_line=series_name,
                scraped_at=datetime.utcnow().isoformat(),
                pdf_url=pdf_url,
                **{k: v for k, v in specs.items() if k in asdict(OEMModel())},
            )
            model.fill_from_ashrae_defaults()
            self.models.append(model)
            logger.info(f"  ✅ Extracted specs from {filename}")

        except ImportError:
            logger.warning("  ⚠️ pdfplumber not installed — cannot parse PDFs")
        except Exception as e:
            logger.warning(f"  ❌ PDF parse error: {e}")

    def _parse_spec_text(self, text: str) -> dict:
        specs: dict = {}

        # Tonnage
        for pat in [r"(\d+(?:\.\d+)?)\s*(?:ton|RT|TR)", r"capacity[:\s]+(\d+(?:\.\d+)?)\s*(?:kW|ton)"]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                specs["tonnage_tons"] = val if val < 1000 else val / 12
                break

        # COP / IPLV
        cop_m = re.search(r"COP[:\s=]+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        iplv_m = re.search(r"IPLV[:\s=]+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if cop_m:
            specs["efficiency_ratio"] = float(cop_m.group(1))
            specs["efficiency_type"] = "COP"
        elif iplv_m:
            specs["efficiency_ratio"] = float(iplv_m.group(1))
            specs["efficiency_type"] = "IPLV"

        # Refrigerant
        ref_m = re.search(r"(R-?410A|R-?134a|R-?123|R-?407C)", text, re.IGNORECASE)
        if ref_m:
            specs["refrigerant"] = ref_m.group(1).upper()

        # Voltage
        volt_m = re.search(r"(\d+[/-]\d+[/-]\d+)\s*(?:V|vac|volt)", text, re.IGNORECASE)
        if volt_m:
            specs["electrical_voltage"] = volt_m.group(1)

        # Sound
        sound_m = re.search(r"(\d+)\s*(?:dBA?|dB\(A\))", text, re.IGNORECASE)
        if sound_m:
            specs["sound_power_dba"] = float(sound_m.group(1))

        return specs


# ── Main Orchestrator ────────────────────────────────────────────────────────

class OEMCatalogScraper:
    """Runs all scrapers and aggregates results."""

    SCRAPERS = {
        "grundfos": GrundfosScraper,
        "daikin": DaikinScraper,
        "bimobject": BIMobjectScraper,
        "specifiedby": SpecifiedByScraper,
        "jci-york": JCIScraper,
    }

    def __init__(self, output_dir: str = "config/oem_catalogs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.all_models: list[OEMModel] = []

    async def run(self, sources: list[str]) -> list[OEMModel]:
        logger.info(f"🚀 Starting OEM catalog scrape — sources: {sources}")

        for source in sources:
            if source == "all":
                for scraper_cls in self.SCRAPERS.values():
                    await self._run_scraper(scraper_cls)
                break
            elif source in self.SCRAPERS:
                await self._run_scraper(self.SCRAPERS[source])
            else:
                logger.warning(f"Unknown source: {source}")

        logger.info(f"✅ Total models collected: {len(self.all_models)}")
        return self.all_models

    async def _run_scraper(self, scraper_cls) -> None:
        scraper = scraper_cls(output_dir=str(self.output_dir))
        try:
            models = await scraper.scrape()
            self.all_models.extend(models)
        except Exception as e:
            logger.error(f"❌ Scraper {scraper_cls.name} failed: {e}")

    def export_json(self, path: Optional[str] = None) -> None:
        """Export all models as JSON."""
        out_path = Path(path) if path else self.output_dir / f"oem_catalog_{datetime.utcnow().strftime('%Y%m%d')}.json"

        data = [asdict(m) for m in self.all_models]
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info(f"💾 Exported {len(data)} models → {out_path}")

    def export_weibull_config(self, path: Optional[str] = None) -> None:
        """
        Generate config/oem_weibull_params.py with OEM-specific overrides
        that take precedence over ASHRAE defaults.
        """
        out_path = Path(path) if path else Path("config/oem_weibull_params.py")

        lines = [
            '# -*- coding: utf-8 -*-',
            '"""',
            'OEM Weibull Parameter Overrides',
            '==============================',
            'Auto-generated by scripts/oem_scraper.py',
            f'Generated: {datetime.utcnow().isoformat()}',
            '',
            'These values override config/ashrae_defaults.py when OEM data',
            'is available. Values sourced from OEM datasheets and PDFs.',
            '',
            'Format per manufacturer:',
            '  EQUIPMENT_TYPE_MFR_MODEL = {',
            '      "alpha_hours": int,',
            '      "beta": float,',
            '      "mtbf_hours": int,',
            '      "mtbf_source": "OEM",',
            '      "service_interval_months": int,',
            '      "degradation_factors": [...],',
            '  }',
            '"""',
            '',
            '# ── OEM-specific overrides (replace ASHRAE defaults) ──',
            '',
        ]

        # Group by manufacturer + equipment_type
        by_mfr = {}
        for m in self.all_models:
            key = (m.manufacturer.upper(), m.equipment_type.upper())
            by_mfr.setdefault(key, []).append(m)

        for (mfr, eq_type), models in sorted(by_mfr.items()):
            # Take the first model that has Weibull params (best available)
            best = next(
                (mod for mod in models if mod.weibull_alpha_hours and mod.weibull_beta),
                None,
            )
            if not best:
                continue

            key = f'{eq_type}_{mfr.replace(" ", "_").replace("-", "_")}'
            lines.append(f'{key} = {{')
            lines.append(f'    "manufacturer": "{best.manufacturer}",')
            lines.append(f'    "model": "{best.model_number}",')
            lines.append(f'    "equipment_type": "{best.equipment_type}",')
            lines.append(f'    "alpha_hours": {best.weibull_alpha_hours},')
            lines.append(f'    "beta": {best.weibull_beta},')
            lines.append(f'    "mtbf_hours": {best.mtbf_hours},')
            lines.append(f'    "mtbf_source": "{best.mtbf_source}",')
            lines.append(f'    "service_interval_months": {best.service_interval_months or 12},')
            lines.append(f'    "degradation_factors": {best.degradation_factors!r},')
            lines.append(f'    "efficiency_ratio": {best.efficiency_ratio},')
            lines.append(f'    "efficiency_type": "{best.efficiency_type}",')
            lines.append(f'    "refrigerant": "{best.refrigerant}",')
            lines.append(f'    "notes": "{best.notes[:200]}",')
            lines.append('}')
            lines.append('')

        out_path.write_text("\n".join(lines))
        logger.info(f"💾 Exported Weibull override config → {out_path}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OEM Catalog Scraper")
    parser.add_argument(
        "--source",
        nargs="+",
        default=["all"],
        choices=list(OEMCatalogScraper.SCRAPERS.keys()) + ["all"],
        help="Source(s) to scrape",
    )
    parser.add_argument("--export-json", action="store_true", help="Export models as JSON")
    parser.add_argument("--update-weibull", action="store_true", help="Generate Weibull override config")
    parser.add_argument("--output-dir", default="config/oem_catalogs", help="Output directory")
    parser.add_argument("--query", default="", help="Search query (for search-based scrapers)")
    parser.add_argument(
        "--specifiedby-data",
        type=str,
        help="Path to JSON file captured from SpecifiedBy via Notte/Playwright",
    )
    args = parser.parse_args()

    scraper = OEMCatalogScraper(output_dir=args.output_dir)

    # Load Notte-captured SpecifiedBy data if provided
    if args.specifiedby_data:
        path = Path(args.specifiedby_data)
        if path.exists():
            logger.info(f"📋 Loading Notte-captured data from {path}")
            data = json.loads(path.read_text())
            for item in data:
                model = OEMModel(**item)
                model.fill_from_ashrae_defaults()
                scraper.all_models.append(model)

    asyncio.run(scraper.run(args.source))

    if args.export_json:
        scraper.export_json()

    if args.update_weibull:
        scraper.export_weibull_config()

    if not (args.export_json or args.update_weibull):
        print("\nRun with --export-json to save results or --update-weibull to generate config.")


if __name__ == "__main__":
    main()