# AI Manager

**An AI project manager that lives in the WhatsApp group your team already uses.**

It listens to everything — text, voice notes, photos, PDFs — keeps a real dependency-scheduled
plan, chases the promises people make, remembers everything forever, and briefs the team twice a
day. Nobody installs an app. Nobody changes how they work.

---

## What it does

| | |
|---|---|
| **Understands everything** | Every message in the group is read and understood — including **voice notes in mixed Hindi / Kannada / English** (transcribed to English) and PDFs. It speaks only when it has something worth saying. |
| **Asks about photos, never guesses** | A site photo arrives → *"📷 Got the photo — what's this about?"* The person's own answer (typed **or a voice note**) becomes the caption and a permanent memory. The AI never invents what an image shows. |
| **Turns talk into a plan** | *"False ceiling is done"* → *"Mark **False ceiling** as done? YES / NO"* → the schedule recomputes, downstream dates shift, and the next owner is told they're up. |
| **Chases promises** | *"We'll finish tomorrow"* becomes a tracked promise with a name and a date. If it slips, the tone escalates — gently at first, then firmly, then to the manager. It never nags twice in a day. |
| **Remembers forever** | *"Remember the client wants matte finish."* Six months later: *"What did we say about the finish?"* → the answer, **with the date and who said it**. |
| **Briefs twice a day** | Morning: what's due, what's overdue, who promised what. Evening: what actually happened — and the day itself becomes a memory. |
| **Proves what was agreed** | Every approval is kept with the client's exact words, timestamped. One click exports the **evidence pack PDF** — the document you show when a client says "I never approved that." |

---

## Two surfaces, one brain

```
        WhatsApp group                          Web console
   (the site team, the client)              (the office / owner)
              │                                      │
              │  understands everything              │  sees everything
              │  speaks when useful                  │  can act on anything
              └──────────────┬───────────────────────┘
                             ▼
                      one database, one brain
              plan · promises · approvals · memories
```

**Everything done in WhatsApp appears in the console** — tasks completed, promises made, approvals
given, photos captioned, memories saved.

**Everything done in the console is known to the bot** — a plan edit, a confirmation, a memory you
teach it. Ask it in the group a second later and it already knows. There is no sync job to fail:
both read the same database, and the AI Manager's answer is built from the full situation (plan +
promise ledger + approval trail + photo context + semantically-retrieved history) on every question.

*(Proven, not assumed — see `tests/test_roundtrip.py`.)*

---

## The rules it plays by

These are non-negotiable, inherited from ArvisX:

1. **It proposes; it never writes on its own.** Only a deterministic executor changes the plan, and
   only after a human says YES. Money-touching facts never auto-commit.
2. **Grounding is law.** It cannot state a number, name or date that didn't come from real data.
   "I don't know" beats a confident invention.
3. **It degrades, it doesn't break.** No LLM? It still ingests, tracks, chases and briefs — just
   more bluntly. No speech key? It stays silent about voice notes rather than guessing at them.
4. **Speaking is gated; understanding isn't.** It hears every message in the group. It only talks
   when it has something to say.
5. **It lets go.** A photo nobody explains gets one more ask, then is filed quietly. It doesn't nag.

---

## Risk lanes (how it's allowed to act)

| Lane | What | Example |
|------|------|---------|
| **A** — auto, undoable | Low-risk filing | A photo is stored; a PDF is parsed; a memory is saved |
| **B** — confirm in chat | Anything that changes the plan | *"Mark False ceiling done? YES / NO"* |
| **C** — structured form | Money, measurements, attendance | *Deferred — needs the official WhatsApp API* |

---

## Commands (in the group)

| Say | Get |
|---|---|
| `@firstbriq tasks` | Overdue, today, next 7 days — owner-tagged |
| `@firstbriq digest` | Where the project stands |
| `@firstbriq promises` | The open promise ledger, with how late each one is |
| `@firstbriq approvals` | The approval log |
| `remind Ravi` | Ravi gets shown exactly what he owes, and how overdue |
| `remember <anything>` | Stored forever |
| `@firstbriq what did we say about X?` | Answered, with the date and who said it |
| *(anything else)* | Understood silently, and remembered |

---

## What it is **not**

Not a PM tool people have to open. Not a chatbot that answers questions and forgets. Not an image
analyser that guesses what a photo shows. Not an autonomous agent that edits your project behind
your back.

It's a manager that sits in the group, pays attention, remembers, and follows up.
