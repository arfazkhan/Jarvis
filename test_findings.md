
# 🧪 Comprehensive Test Report
**Generated**: 2026-01-03 14:37:14
**Duration**: 199.5 seconds
**Total Tests**: 44

---

## 📊 Summary

| Metric | Value |
|--------|-------|
| Pass Rate | 65.9% |
| Local Routing Accuracy | 96.2% |
| Cloud Routing Accuracy | 0.0% |
| Avg Local Latency | 4582.58ms |
| Avg Cloud Latency | 0.0ms |

---

## ✅ What's Working

- **Explicit Commands**: Direct device commands are handled locally

---

## ❌ What's Breaking

### Routing Mismatches (19 issues)
- **Explicit: Brightness**: Expected `local`, got `none`
  - Command: "Set kitchen_main to 50% brightness"
- **Natural: All Lights Off**: Expected `cloud`, got `none`
  - Command: "Turn off all the lights"
- **Ambiguous: Turn it on**: Expected `cloud`, got `none`
  - Command: "Turn it on"
- **Ambiguous: Make it brighter**: Expected `cloud`, got `none`
  - Command: "Make it brighter"
- **Ambiguous: That light**: Expected `cloud`, got `none`
  - Command: "Turn off that light"

### Failures (15 issues)
- **Explicit: Brightness**: Routing mismatch: expected local, got none
- **Natural: All Lights Off**: Routing mismatch: expected cloud, got none
- **Ambiguous: Turn it on**: Routing mismatch: expected cloud, got none
- **Ambiguous: Make it brighter**: Routing mismatch: expected cloud, got none
- **Ambiguous: That light**: Routing mismatch: expected cloud, got none


---

## 🤦 What's Stupid

- **Slow Local**: 29 local commands took >500ms. Defeats purpose of local path.
- **Risky Local Guessing**: 4 ambiguous commands handled locally (may hallucinate)

---

## 📝 Detailed Results

| Test | Command | Expected | Actual | Latency | Status |
|------|---------|----------|--------|---------|--------|
| Explicit: Kitchen Light On | Turn on kitchen_main... | local | local | 55332ms | ✅ |
| Explicit: Kitchen Light Off | Turn off kitchen_main... | local | local | 1957ms | ✅ |
| Explicit: Living Room Light | Turn on living_room_light... | local | local | 1510ms | ✅ |
| Explicit: Bedroom AC | Turn on bedroom_ac... | local | local | 1594ms | ✅ |
| Explicit: Porch Light | Turn on porch_light... | local | local | 1821ms | ✅ |
| Explicit: Multiple Word ID | Turn on living_room_lamp... | local | local | 1436ms | ✅ |
| Explicit: Brightness | Set kitchen_main to 50% bright... | local | none | 1850ms | ❌ |
| Natural: Kitchen Lights | Turn on the kitchen lights... | local | local | 1558ms | ✅ |
| Natural: Bedroom Lamp | Switch on the bedroom lamp... | local | local | 2157ms | ✅ |
| Natural: All Lights Off | Turn off all the lights... | cloud | none | 10381ms | ❌ |
| Alias: Kitchen Light | Turn on kitchen light... | local | local | 1530ms | ✅ |
| Alias: Living Room Light | Turn off the living room light... | local | local | 1520ms | ✅ |
| Alias: Bedroom Light | Turn on bedroom light... | local | local | 1430ms | ✅ |
| Alias: Bathroom Light | Switch on bathroom light... | local | local | 1836ms | ✅ |
| Alias: Porch Light | Turn on the porch light... | local | local | 1546ms | ✅ |
| Alias: Garage Light | Turn off garage light... | local | local | 1513ms | ✅ |
| Alias: TV Light | Turn on tv light... | local | local | 1449ms | ✅ |
| Alias: AC | Turn on the ac... | local | local | 1495ms | ✅ |
| Alias: Kitchen Fan | Turn on the kitchen fan... | local | local | 1390ms | ✅ |
| Alias: Exhaust Fan | Turn on bathroom exhaust... | local | local | 1428ms | ✅ |
| Conversational: Please Kitchen | Please turn on the kitchen lig... | local | local | 1672ms | ✅ |
| Conversational: Can You Bedroom | Can you turn off the bedroom l... | local | local | 1702ms | ✅ |
| Conversational: Hey Porch | Hey, turn on the porch... | local | local | 2006ms | ✅ |
| Ambiguous: Turn it on | Turn it on... | cloud | none | 1331ms | ❌ |
| Ambiguous: Make it brighter | Make it brighter... | cloud | none | 1304ms | ❌ |
| Ambiguous: That light | Turn off that light... | cloud | none | 1624ms | ❌ |
| Context: Its dark | It's getting dark in here... | cloud | local | 1625ms | ✅ |
| Context: Movie time | I'm going to watch a movie... | cloud | none | 1371ms | ❌ |
| Context: Going to bed | I'm going to sleep now... | cloud | local | 1428ms | ✅ |
| Context: Too hot | It's too hot... | cloud | none | 1313ms | ❌ |
| Mission: Morning Routine | Create a morning routine that ... | cloud | none | 1917ms | ❌ |
| Mission: Party Mode | Set up a party mode with all l... | cloud | none | 2453ms | ❌ |
| Mission: Vacation | I'm going on vacation, simulat... | cloud | none | 3944ms | ❌ |
| Question: Light Status | Is the kitchen light on?... | cloud | local | 6179ms | ✅ |
| Question: Energy Usage | How much energy am I using?... | cloud | none | 3156ms | ❌ |
| Question: Weather | What's the weather like?... | cloud | none | 5273ms | ❌ |
| Edge: Typo Device | Turn on kichen_main... | local | local | 6346ms | ✅ |
| Edge: Unknown Device | Turn on the fridge... | cloud | none | 6416ms | ❌ |
| Edge: Mixed | Turn on kitchen_main and tell ... | cloud | local | 12481ms | ✅ |
| Edge: Empty | ... | cloud | none | 0ms | ❌ |
| Edge: Gibberish | asdfghjkl... | cloud | none | 7547ms | ❌ |
| Rapid: Light 1 | Turn on bathroom_light... | local | local | 9081ms | ✅ |
| Rapid: Light 2 | Turn off bathroom_light... | local | local | 5650ms | ✅ |
| Rapid: Light 3 | Turn on garage_light... | local | local | 5603ms | ✅ |
