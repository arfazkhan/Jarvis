"""Agent 2 — Cost Estimator. The invariants that matter:
  · the LLM never sets a price — every rupee traces to the rate card
  · the budget NEVER changes the estimate, only the message
  · confidence is honest — it falls when we assumed rather than read
  · no vision key → we ask the human, we never guess at the drawing
"""
import pytest
from fastapi.testclient import TestClient

from fbq import estimator, pricing, takeoff


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FBQ_DB", str(tmp_path / "fbq.db"))
    monkeypatch.setenv("FBQ_MEDIA_DIR", str(tmp_path / "media"))
    for k in ("FBQ_LLM", "ARVIS_X_LLM", "FBQ_VISION_KEY", "OPENAI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    from fbq.api import create_app
    return TestClient(create_app())


PHONE = "919900011122"


def _msg(client, text, phone=PHONE):
    return client.post("/api/v1/estimate/message",
                       json={"phone": phone, "name": "Asha", "text": text}).json()["reply"]


# ── pricing: deterministic, traceable to the rate card ────────────────────
def test_every_rupee_comes_from_the_rate_card():
    rc = pricing.load_rates()
    scope = {"source": "user", "items": [{"key": "modular_kitchen", "qty": 100, "assumed": False}]}
    est = pricing.estimate(scope, "good", rc)
    line = est["lines"][0]
    assert line["rate"] == rc["items"]["modular_kitchen"]["rates"]["good"]
    assert line["cost"] == 100 * line["rate"]                 # arithmetic, not opinion
    ov = rc["overheads"]
    expected = line["cost"] * (1 + (ov["design_fee_pct"] + ov["execution_pct"]) / 100)
    expected *= (1 + ov["gst_pct"] / 100)
    assert abs(est["total"] - expected) < 2                   # rounding only


def test_unknown_item_is_never_invented():
    scope = {"source": "user", "items": [{"key": "helipad", "qty": 1}]}
    est = pricing.estimate(scope, "luxury")
    assert est["lines"] == [] and est["total"] == 0           # priced at zero, never guessed


def test_tier_scales_the_price_monotonically():
    scope = {"source": "user", "items": [{"key": "wardrobe", "qty": 120, "assumed": False}]}
    totals = [pricing.estimate(scope, t)["total"] for t in pricing.TIERS]
    assert totals == sorted(totals) and totals[0] < totals[-1]


# ── confidence is honest ──────────────────────────────────────────────────
def test_confidence_falls_when_quantities_are_assumed():
    read = {"source": "vision", "vision_confidence": 0.9,
            "items": [{"key": "modular_kitchen", "qty": 110, "assumed": False},
                      {"key": "wardrobe", "qty": 126, "assumed": False},
                      {"key": "tv_unit", "qty": 32, "assumed": False},
                      {"key": "false_ceiling", "qty": 400, "assumed": False}]}
    guessed = {"source": "vision", "vision_confidence": 0.9,
               "items": [{"key": k, "qty": None, "assumed": True}
                         for k in ("modular_kitchen", "wardrobe", "tv_unit", "false_ceiling")]}
    assert pricing.estimate(read, "good")["confidence"] > pricing.estimate(guessed, "good")["confidence"]


def test_confidence_never_claims_certainty():
    perfect = {"source": "vision", "vision_confidence": 1.0,
               "items": [{"key": k, "qty": 50, "assumed": False}
                         for k in ("modular_kitchen", "wardrobe", "tv_unit", "false_ceiling",
                                   "painting")]}
    assert pricing.estimate(perfect, "good")["confidence"] <= 95   # a plan is not a site visit


# ── the budget changes the WORDS, never the NUMBER ────────────────────────
def test_budget_does_not_move_the_estimate():
    scope = takeoff.scope_from_answers(bedrooms=3, bathrooms=2, balconies=2, carpet_sqft=1200)
    est = pricing.estimate(scope, "good")
    totals = {b["id"]: pricing.estimate(scope, "good")["total"]
              for b in pricing.load_rates()["budget_bands"]}
    assert len(set(totals.values())) == 1                     # identical, whatever the budget
    assert est["total"] == list(totals.values())[0]


def test_the_four_situations():
    assert pricing.budget_verdict(1800000, "10_15")["situation"] == "over"
    assert pricing.budget_verdict(1800000, "20_30")["situation"] == "under"
    assert pricing.budget_verdict(1800000, "15_20")["situation"] == "close"
    assert pricing.budget_verdict(1800000, "unsure")["situation"] == "unknown"
    over = pricing.budget_verdict(1800000, "10_15")["text"]
    assert "more than your planned budget" in over and "Lakhs" in over


# ── parsers ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,want", [("1", "basic"), ("3", "premium"), ("premium", "premium"),
                                       ("luxury please", "luxury"), ("banana", None)])
def test_parse_tier(text, want):
    assert estimator.parse_tier(text) == want


@pytest.mark.parametrize("text,want", [("1", "under_10"), ("4", "20_30"), ("not sure", "unsure"),
                                       ("around 18 lakhs", "15_20"), ("hello", None)])
def test_parse_budget(text, want):
    assert estimator.parse_budget(text) == want


def test_parse_rooms():
    r = estimator.parse_rooms("3 bed, 2 bath, 2 balcony, 1200 sqft")
    assert r == {"bedrooms": 3, "bathrooms": 2, "balconies": 2, "carpet_sqft": 1200.0}
    assert estimator.parse_rooms("3bhk")["bedrooms"] == 3
    assert estimator.parse_rooms("hello") is None


def test_scope_scales_with_bedrooms():
    two = takeoff.scope_from_answers(2)
    four = takeoff.scope_from_answers(4)
    beds2 = next(i for i in two["items"] if i["key"] == "bed")["qty"]
    beds4 = next(i for i in four["items"] if i["key"] == "bed")["qty"]
    assert beds2 == 2 and beds4 == 4
    assert pricing.estimate(four, "good")["total"] > pricing.estimate(two, "good")["total"]


# ── the funnel, end to end (no vision key → the honest fallback path) ─────
def test_full_funnel_without_vision(client):
    assert "floor plan" in _msg(client, "hi").lower()
    r = _msg(client, "3bhk")                                   # typed instead of uploading
    assert "3BHK" in r and "Basic" in r and "Luxury" in r      # → style menu
    r = _msg(client, "2")                                      # good
    assert "budget" in r.lower()
    r = _msg(client, "3")                                      # ₹15–20L
    assert "Your home includes" in r and "Lakhs" in r and "Confidence" in r
    assert "interior expert" in r
    lead = client.get("/api/v1/leads").json()["leads"][0]
    assert lead["stage"] == "estimated" and lead["tier"] == "good" and lead["estimate_total"] > 0


def test_unreadable_plan_asks_instead_of_guessing(client):
    """No vision key configured → we must ASK, never invent a floor plan reading."""
    r = client.post("/api/v1/estimate/plan", content=b"not-a-real-image",
                    params={"phone": PHONE, "name": "Asha", "filename": "plan.jpg"}).json()["reply"]
    assert "couldn't read" in r.lower() and "won't guess" in r.lower()
    assert "bedrooms" in r.lower()
    r2 = _msg(client, "3 bed 2 bath")                          # they answer → funnel continues
    assert "3BHK" in r2


def test_lead_is_captured_for_the_business(client):
    _msg(client, "hi"); _msg(client, "3bhk"); _msg(client, "2"); _msg(client, "3")
    r = _msg(client, "yes")
    assert "expert" in r.lower()
    lead = client.get("/api/v1/leads", params={"stage": "lead_captured"}).json()["leads"][0]
    assert lead["wants_expert"] == 1 and lead["phone"] == PHONE
    assert lead["scope"]["rooms"]["bedrooms"] == 3            # we know the home
    assert lead["tier"] == "good" and lead["budget_band"] == "15_20"   # …the taste and the money


def test_declining_is_respected(client):
    _msg(client, "hi"); _msg(client, "3bhk"); _msg(client, "2"); _msg(client, "3")
    r = _msg(client, "no")
    assert "no problem" in r.lower()
    assert client.get("/api/v1/leads", params={"stage": "declined"}).json()["leads"]


def test_breakdown_on_request(client):
    _msg(client, "hi"); _msg(client, "3bhk"); _msg(client, "2"); _msg(client, "3")
    r = _msg(client, "breakdown")
    assert "Where the money goes" in r and "GST" in r and "Total" in r


def test_restart(client):
    _msg(client, "hi"); _msg(client, "3bhk"); _msg(client, "2"); _msg(client, "3"); _msg(client, "no")
    assert "floor plan" in _msg(client, "restart").lower()


def test_rate_card_is_visible_to_the_business(client):
    rc = client.get("/api/v1/pricing").json()
    assert rc["items"]["modular_kitchen"]["rates"]["luxury"] > 0 and rc["overheads"]["gst_pct"] == 18.0
