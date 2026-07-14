# ArvisX — Design-Partner Pilot Agreement

*Template. Fill the [BRACKETS]. This is a plain-language design-partner agreement, NOT
legal advice — have a lawyer review before signing, especially the liability, data, and
fire-system clauses.*

---

**This Pilot Agreement** is made on [DATE] between:

- **Provider:** [YOUR COMPANY / ArvisX], [address] ("ArvisX", "we").
- **Community:** [COMMUNITY / SOCIETY / OWNERS' ASSOCIATION NAME], represented by its
  [Managing Committee / Chairman / Facility Manager] ("the Community", "you"），at
  [building address].

Together, "the Parties".

---

## 1. Purpose

A no-fee design-partner pilot to deploy ArvisX — an **advisory operations-intelligence
layer** — over the Community's existing utilities (water, power backup, STP, pool, fire-
pump visibility, common-area equipment). The pilot validates ArvisX in a live building
and produces shared learnings; in return the Community gets early access at no cost.

## 2. What ArvisX is — and is NOT (read carefully)

2.1 ArvisX is **advisory and read-only**. It observes sensor telemetry, learns each
asset's normal, and **recommends** actions (alerts, work orders, cost estimates). It does
**NOT control, operate, start, stop, or actuate any equipment**. All physical action is
taken by the Community's staff/vendors.

2.2 **Fire systems:** ArvisX provides **supplementary visibility only** (e.g. "fire-pump
test overdue"). It is **NOT** a certified fire-detection or fire-alarm system and **does
not replace** the building's legally-required, certified fire system or any statutory
inspection. The Community's certified fire system remains the system of record.

2.3 ArvisX is a **pilot / pre-production** product. It may contain errors, miss issues, or
raise false alarms. It is a decision-support aid, **not a guarantee** of equipment health
or safety.

## 3. Scope of the pilot

3.1 **Assets covered:** [list — e.g. underground + overhead tanks, transfer + booster
pumps, diesel generator + battery, STP blower/pump, pool filtration, fire pump]. Start
set: [the 2–3 highest-value assets].

3.2 **Sensors / telemetry:** [who supplies + installs the edge gateway + sensors; on whose
power/network]. Telemetry reaches ArvisX over the Community's LAN/MQTT.

3.3 **Channels:** WhatsApp (daily digest + alerts to nominated recipients) and a web
dashboard.

3.4 **Sites:** this pilot covers **one** building/community only.

3.5 **Out of scope:** equipment control, billing/payments, statutory fire compliance, any
domain not listed in 3.1.

## 4. Term

4.1 Pilot term: **[12] weeks** from the go-live date (commissioning → learning →
operational → readout), starting [DATE].

4.2 Either Party may end the pilot with **[7] days'** written notice. On termination
ArvisX stops processing and, on request, deletes Community data per §6.4.

## 5. Responsibilities

**ArvisX will:**
- Deploy and operate the ArvisX stack for the term, at no licence fee.
- Commission the building with the FM (target: half a day of on-site setup).
- Provide the WhatsApp digest/alerts and dashboard access.
- Give a written + verbal readout at the end (§7).
- Keep Community data confidential (§6).

**The Community will:**
- Nominate a **Facility Manager** as primary contact and an empowered **committee sponsor**.
- Provide site access, power, network/LAN, and cooperation for sensor install.
- Act on alerts within its normal operations (and record outcomes via work orders) so the
  pilot can measure real value.
- Provide reasonable feedback at weekly check-ins.
- Allow ArvisX to use **anonymised/aggregated** pilot results in a case study (§8).

## 6. Data

6.1 **Ownership:** the Community owns its raw operational/telemetry data. ArvisX owns the
software, models, and any learned patterns/aggregates derived across deployments.

6.2 **Use:** ArvisX processes Community data solely to operate the pilot and improve the
product. No personal resident data is required; the Community will not feed ArvisX
personal/financial resident data.

6.3 **Confidentiality:** each Party keeps the other's non-public information confidential
during and after the pilot.

6.4 **Retention/deletion:** on termination, ArvisX deletes the Community's identifiable
data within [30] days on written request; anonymised aggregates may be retained.

6.5 **Security:** the deployment uses access control (API keys / user roles); the
Community is responsible for the security of its own LAN and devices.

## 7. Success criteria (agreed up front)

The Parties agree the pilot is successful if, by end of term:
- [ ] The building is **commissioned to operational** on real telemetry.
- [ ] ArvisX delivers the **daily digest** and **sparse alerts** reliably.
- [ ] The FM **acts on ≥ [50]%** of pushed alerts (raises/closes work orders).
- [ ] At least **one quantified outcome** is documented (money saved/at-risk, or an issue
      flagged early).
- [ ] False-alarm rate is **below [1 per 2 weeks]** by end of term.

Agreed targets may be adjusted in writing by both Parties before go-live.

## 8. Publicity / reference

8.1 ArvisX may produce a **case study** using pilot results. The Community's **name/logo**
will be used only with prior written approval; otherwise results are anonymised
("a [size]-unit community in [city]").

8.2 The Community agrees to consider acting as a **reference** (one call / quote) if the
pilot meets its success criteria — at its discretion.

## 9. Fees

9.1 The pilot is **free of licence fees**. Hardware/sensor costs: [who pays — specify].

9.2 Post-pilot commercial terms (if the Community continues) are **not** set by this
agreement and will be a separate offer.

## 10. Liability

10.1 ArvisX is provided **"as is"** for the pilot, without warranties of fitness or
uninterrupted operation.

10.2 ArvisX is **not liable** for equipment failure, damage, injury, service interruption,
or losses arising from action or inaction based on its advisory output. The Community
remains responsible for operating and maintaining its equipment and for statutory
compliance (incl. fire).

10.3 To the extent permitted by law, ArvisX's total liability under this pilot is limited
to [QAR/INR 0 — no-fee pilot] / [the fees paid].

## 11. General

11.1 Governing law: [Qatar / India — state/emirate].
11.2 This is the entire agreement for the pilot and supersedes prior discussions.
11.3 Neither Party may assign it without the other's consent.

---

**Signed:**

ArvisX: ___________________  Name: [__]  Title: [__]  Date: [__]

Community: ________________  Name: [__]  Title: [__]  Date: [__]

*(Not legal advice — review with counsel before signing.)*
