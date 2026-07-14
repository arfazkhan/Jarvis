# Cost Estimator — *Agent 2*

**"How much will my interiors cost?" — answered on WhatsApp, in two minutes.**

The homeowner does three things. Everything else is ours.

```
   send floor plan  →  tap a style  →  tap a budget  →  estimate  →  talk to an expert?
```

---

## What they see

> **Your home includes**
> ✅ Modular kitchen ✅ Wardrobe ✅ Bed with storage ✅ TV unit
> ✅ Bathroom vanity ✅ Balcony styling ✅ Shoe rack ✅ Dining set
> ✅ False ceiling ✅ Painting
>
> **Estimated cost**
> **₹18.4 Lakhs** *(Good finish, incl. GST)*
>
> **Confidence** 91%
>
> Your dream home comes to about ₹3.4 Lakhs more than your planned budget.
> That's normal — and fixable. We can bring it down by changing materials,
> trimming the scope, or phasing the work.
>
> 👉 **Would you like to talk to an interior expert?**

No spreadsheet. No jargon. One number they can act on.

---

## The two workers

| | **Worker 1 — Takeoff** | **Worker 2 — Estimator** |
|---|---|---|
| **Does** | Reads the floor plan. Identifies rooms and lists what has to be built. | Prices that list. |
| **How** | Vision model | **A rate card. Arithmetic.** |
| **Never** | Prices anything | Guesses anything |

**This split is the whole design.** The AI *counts*; a human-owned table *prices*.

A miscount is a **visible, correctable mistake** — the user sees "✅ Wardrobe" and knows their home
has three. An invented price is **a lie you can't see**. So no LLM ever touches a rupee: every
figure traces to `seeds/pricing_bangalore.json`, which the business can retune without a developer.

---

## Confidence is honest

It isn't decoration. It **falls** when we had to *assume* a quantity rather than *read* one, and it
is capped at **95%** — because a floor plan is not a site visit, and we won't pretend otherwise.

When it drops below 70 the message says so out loud:
> *Some quantities were assumed — a designer will firm these up.*

---

## The budget never changes the estimate

Worth saying twice, because it's the one place a product like this could quietly cheat.

The number is the number. The budget only decides **which of four things we say afterwards**:

| Situation | We say |
|---|---|
| Estimate **over** budget | *"Costs about ₹X more than planned. That's normal — and fixable."* |
| Estimate **under** budget | *"You have roughly ₹X of headroom — you could upgrade."* |
| They **match** | *"Your budget and this estimate line up well."* |
| They **don't know** | *"Here's a realistic estimate. Use it as a starting point."* |

A range like *"₹20–30L"* is read as **≈₹25L** — because that's what the person meant. Anchoring to
the floor would let us call a ₹18L estimate "about right" when they actually have headroom. That's
a lie of framing, and the tests forbid it.

---

## No vision key? We ask. We never guess.

If the drawing can't be read — or no vision model is configured — the bot does **not** invent a
floor plan:

> *"I couldn't read that as a floor plan — no problem, I won't guess. 🙂
> Just tell me the basics: how many bedrooms, bathrooms and balconies?"*

Four honest answers beat one confident hallucination. Confidence reflects the difference.

---

## The business outcome

The estimate is what we *give*. **The lead is what we get.**

By the time a designer picks up the phone, we already know:
- **the home** — 3BHK, 1250 sqft, what it needs built
- **the taste** — Premium
- **the money** — ₹20–30L, and that our estimate leaves them headroom

The **Estimator** tab in the console lists every lead, hottest first — the ones who said *yes, put
me through to an expert*.

---

## Two agents, one WhatsApp number

| | Lives in | Talks to | Does |
|---|---|---|---|
| **Agent 1 — AI Manager** | **Groups** | Project teams | Runs the project |
| **Agent 2 — Cost Estimator** | **1:1 DMs** | Homeowners | Qualifies the lead |

A group message is a project. A direct message is a customer. No collision.
