# Daylight Subscribe: design

## Intent

Let a stranger who lands on a web page get daylight (and optionally golden and
blue hour) into their calendar without installing anything, downloading a
file, or using the calendar's import screen. They pick a place and options,
press "Add to Google Calendar" or "Add to Apple Calendar", and end up
subscribed to a calendar of its own that they can hide or remove in one step.

This is a separate project (`daylight-subscribe`), not part of the Python CLI.
The CLI (`daylight-calendar/create_daylight_calendar.py`, astral 3.2) is the
reference for what the events mean and when they happen.

## Goals

- One-click subscription for Google Calendar (web) and Apple Calendar
  (macOS/iOS), plus a copyable feed URL for anything else.
- The feed always covers a rolling window, so there is no date range to pick
  and it never runs out.
- Same events as the CLI: one daylight block or 30-minute sunrise/sunset
  events, optional morning/evening golden hour and blue hour.
- Event times match astral 3.2 to within 5 seconds.
- The page is static files with no build step, so it can move from GitHub
  Pages to the user's personal site later by copying a folder and changing
  one config value.

## Non-goals

- Accounts, stored data, analytics.
- Writing into calendars through the Google Calendar API (needs OAuth
  verification; strangers would see an "unverified app" warning).
- Fixed date ranges, CSV output, Outlook-specific buttons.

## Anti-goals

- A page that asks strangers to understand ICS, import, or calendar settings.
- Putting events on the visitor's main calendar.
- Leaking a precise home location: coordinates are rounded before they go
  into a URL that Google and Apple will store.

## Approaches considered

- **A. Subscribe link + serverless feed (chosen).** A Cloudflare Worker
  computes the ICS from URL parameters on every request. Subscriptions are
  separate calendars by design and stay current. Costs: a tiny backend
  outside GitHub Pages, a JS port of the sun math, and Google refreshing
  subscriptions on its own schedule (12-24 h), which doesn't matter for
  deterministic data.
- **B. Google Calendar API.** Google-only, and the calendar scope needs app
  verification. Rejected.
- **C. Static page that downloads an `.ics`.** Keeps the import step the user
  wants to remove. Rejected.

## Design

### Feed (Cloudflare Worker)

- `GET /cal.ics?lat=..&lon=..[&mode=block|separate][&golden=1][&blue=1][&name=..]`
  (also `HEAD`). Other methods: 405. Other paths: 404.
- `lat` in [-90, 90], `lon` in [-180, 180], both required; `mode` defaults
  to `block`; `name` defaults to `Daylight`, is stripped of control
  characters and cut to 60 characters. Bad input: 400, `text/plain`
  explaining which parameter is wrong. Unknown parameters are ignored.
- Time zone from coordinates with `@photostructure/tz-lookup` (offline,
  bundled). It decides which local date each event belongs to.
- Window: local today at the location, from 7 days before to 365 days
  after, inclusive.
- Events (same summaries and descriptions as the CLI):
  - `block`: `Daylight`, sunrise to the first sunset after that sunrise
    (found from astral's raw transit, not per-date `sunset()`, which can
    miss a sunset when sunsets drift across midnight).
  - `separate`: `Sunrise` and `Sunset`, each 30 minutes ending at the event.
  - `golden`: morning and evening `Golden hour` (sun -4° to +6°).
  - `blue`: morning and evening `Blue hour` (sun -6° to -4°).
  - Any event the sun doesn't reach that day is left out. Unlike the CLI,
    a missing civil dawn/dusk does not remove sunrise and sunset.
- ICS: times in UTC (`...Z`), so no `VTIMEZONE` is needed;
  `X-WR-CALNAME`, `X-WR-TIMEZONE`, `REFRESH-INTERVAL;VALUE=DURATION:P1D`,
  `X-PUBLISHED-TTL:P1D`; events `TRANSP:TRANSPARENT`; text escaped and
  lines folded per RFC 5545; CRLF line endings. UIDs are stable per date,
  event type and rounded location. DTSTAMP is midnight UTC of the request
  day.
- Response headers: `Content-Type: text/calendar; charset=utf-8`,
  `Content-Disposition: inline; filename="daylight.ics"`,
  `Cache-Control: public, max-age=86400`, `Access-Control-Allow-Origin: *`.
- The largest feed (separate + golden + blue) stays under 1 MB.

### Sun math

A faithful JS port of the parts of astral 3.2 `astral/sun.py` needed for
sunrise, sunset, golden hour and blue hour, including astral's handling
of results that land on a different local date. Observer elevation is
always 0. Astral is Apache-2.0; the port keeps its copyright notice and
the license text.

Correctness is pinned by fixtures generated in Python from astral 3.2 (calling
`sunrise`, `sunset`, `golden_hour`, `blue_hour` individually, never `sun()`).

### Page (static)

- Plain HTML, CSS and ES modules; no framework, no build step.
- Place search sends one Nominatim request when the user submits (no
  autocomplete, per Nominatim policy), shows the resolved place name, and
  credits OpenStreetMap. "Use my location" uses browser geolocation.
- Options: daylight as one block or sunrise and sunset; golden hour;
  blue hour; calendar name (prefilled `Daylight · <place>`).
- Actions: Add to Google Calendar
  (`https://calendar.google.com/calendar/r?cid=<encoded webcal URL>`),
  Add to Apple Calendar (`webcal://` URL), Copy link, Download .ics.
- Coordinates are rounded to 2 decimals (about 1 km, a few seconds of
  sunrise time) before building any URL.
- The feed base URL lives in `site/config.js`.

## Known issue in the CLI (reference project)

`create_daylight_calendar.py` uses astral's `sun()`, which raises if civil
dawn or dusk doesn't happen. At high latitudes in summer (for example
Reykjavik, 2026-06-21) the CLI drops the daylight event although the sun
rises and sets. Also, astral can return a sunset earlier than the sunrise
on the same local date (Reykjavik 2026-06-21: sunrise 02:56, sunset
00:02, which belongs to the previous evening). Both are fixed in the CLI
(commit `cb2a362`, `sun_time` and `sunset_after`); the JS port follows the same rules.

## Left to the builder

Visual design of the page, exact error wording, Worker name and
`workers.dev` subdomain, GitHub Actions details.
