# Rung 6: events (access control, people counters, room bookings)

Who is in a zone is the other half of most energy waste. These feeds give ARVIS occupancy per zone:
- access control (badge swipes, door events);
- people counters;
- the booking calendar.

With occupancy, ARVIS can flag a zone that has been empty for a while but is still being cooled.

```yaml
sources:
  - id: access
    kind: events
    doors:
      DOOR-L5-E: {zone: L5, direction: in}
      DOOR-L5-X: {zone: L5, direction: out}      # with exit readers, ARVIS counts people
      DOOR-L6:   {zone: L6}                        # entries only: presence, not a count
    zones:
      L5: {name: Floor 5, presence_window_min: 120, reset_at: "03:00",
           conditioned_by: [{point: AHU-05/SF_STS}, {point: VAV-5-01/DMPR, above: 20}]}
    rooms: {"Meeting Room 5A": L5}               # calendar LOCATION → zone
    empty_after_min: 45
```

## How events arrive
- **Push:** `POST /api/v1/events?source=access` with the header `x-arvis-events-token: $ARVIS_EVENTS_TOKEN`. The body is one event or a list:
  `{type: badge | door_open | door_forced | people_count | booking, door | zone, direction, count, at, id}`
  Events with the same `id` are counted once, so a retried webhook does no harm. The endpoint refuses everything if the token isn't set.
- **Files:** `POST /api/v1/events/import` takes a badge-export CSV (time, door, direction) or a booking `.ics` file.

## What comes out
- **Points per zone:**
  - `<ZONE>/OCC_COUNT`: people in the zone;
  - `<ZONE>/OCCUPIED`: 0 or 1;
  - `<ZONE>/BOOKED`: 0 or 1.
- **Measured occupancy wins over guesswork.** These points replace the CO₂-based estimate in occupancy and energy (GSAS) analysis.
- **Empty but still cooled.** When a zone has been empty for `empty_after_min` while any point in its `conditioned_by` list is on, ARVIS raises that once ("Floor 5 has had nobody in it since 18:10, but its cooling is still running"). It goes through the attention gate like any other signal and clears when the zone is occupied again or the conditioning stops.
- **Nightly reset.** `reset_at` zeroes the count once a night, so people who leave through a fire exit don't make the count drift upwards.

## Privacy
ARVIS keeps only the door, zone, direction, count and time of each event. Card numbers, names and any other field an access-control system sends are dropped the moment an event arrives: they are never stored, logged or passed on.
