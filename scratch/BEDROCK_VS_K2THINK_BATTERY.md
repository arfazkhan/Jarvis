# Bedrock vs K2Think — RCA scenario battery (2026-06-10)

Multi-scenario head-to-head on the commercial ARVIS swarm, same 4 ground-truth
scenarios (`scratch/scenario_battery.py`), reranking ON, OpenMP guard active.
Backend switched via `ARVIS_LLM_BACKEND` (Bedrock = default; K2Think =
`ARVIS_LLM_BACKEND=k2think LLM_PROVIDER=k2think TOOL_PROVIDER=k2think`).

Logs: `battery_bedrock.log`, `battery_k2think.log`.

## Aggregate

| Metric | Bedrock (Kimi/Nova/MiniMax) | K2Think (K2-Think-v2) |
|---|---|---|
| Contradiction rate / synthesis | **5.60** (28 total) | **0.00** (0 total) |
| Grounded scenarios | 2 / 4 | **4 / 4** |
| H4 faithfulness fails | 8 | **0** |
| Avg investigation latency | ~285s | **~108s** |
| Checks passed | 12 | 14 |
| `confirmed` (over-claim) | False (all) | False (all) |

## Per scenario

| Scenario | Bedrock | K2Think |
|---|---|---|
| ahu_oa_damper_slip | 190s · grnd=F · 6 contr · lead=blade slip ✅ | 116s · grnd=T · 0 contr · lead=blade slip ✅ (5/0) |
| coil_capacity_limit | 391s · grnd=T · 2 contr · 3 hyps | 92s · grnd=T · 0 contr · dom 0.18 |
| chiller_low_efficiency | 328s · grnd=T · **20 contr** · led damper (wrong class) | 129s · grnd=T · 0 contr · **hyps=0** · led damper (wrong) |
| normal_negative_control | 232s · **grnd=F** · invented damper fault ❌ | 95s · grnd=T · led OA-sensor fault (2/0) |

## Verdict

**K2Think won this battery on the dimension ARVIS lives on — grounded, contradiction-free
reasoning** (0 vs 5.60 contradiction rate; 4/4 vs 2/4 grounded; 0 vs 8 H4 fails), and was
~2.6× faster this run. Bedrock produced richer / more-decisive differentials but paid in
faithfulness failures (worst: chiller, 20 contradictions) and a false-positive on the
negative control.

Diagnosis quality was otherwise comparable: both led the correct damper family on the
damper case, both wobbled (led damper) on the chiller; neither over-claimed (`confirmed`
False everywhere).

## Caveats (do not over-read)
1. **One battery each** — both engines are nondeterministic; a production call needs ≥3× runs.
2. **K2Think dropped the structured differential (hyps=0) on the chiller** that run — a
   reliability ding even with the robust extractor; heavy reasoners occasionally emit no array.
3. **Bedrock invented a damper fault on the normal control** (grnd=F) this run — real
   false-positive risk.
4. Contradiction count comes from the H4 logger; part of K2's 0 may reflect more H4-skips
   (cleaner causal prose), but 0 vs 28 is too large to be only that.

**Recommendation:** K2Think is the stronger default for trustworthy (grounded) advisory and
is sovereign (no AWS). Keep Bedrock available for richer differentials where AWS is present.
Run 3× each before locking a production default.
