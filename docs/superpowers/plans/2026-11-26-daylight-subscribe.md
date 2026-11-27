# Daylight Subscribe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A static page plus a Cloudflare Worker that let anyone subscribe Google or Apple Calendar to a rolling daylight / golden hour / blue hour feed for any place.

**Architecture:** The Worker serves `GET /cal.ics?lat&lon&mode&golden&blue&name`, computing events with a JS port of astral 3.2 and returning RFC 5545 ICS. The static page geocodes a place, builds the feed URL and offers Google (`?cid=webcal://…`), Apple (`webcal://…`), copy and download links. Correctness of the sun math is pinned by JSON fixtures generated from astral 3.2 in Python.

**Tech Stack:** JavaScript (ES modules), Node 20+, Vitest, Wrangler (Cloudflare Workers), `@photostructure/tz-lookup`; Python 3.13 + astral 3.2 + timezonefinder for fixtures only.

**Spec:** `docs/superpowers/specs/2026-11-26-daylight-subscribe-design.md` (written in the `daylight-calendar` repo; Task 1 copies it into the new repo).

## Global Constraints

- New repo: `~/github/daylight-subscribe`, MIT license, public. Never commit secrets, `.wrangler/`, `node_modules/`, `.dev.vars`.
- Event times match astral 3.2 within 5 seconds (fixture tolerance).
- Summaries/descriptions exactly as the CLI: `Daylight` / `Daylight hours from sunrise to sunset`; `Sunrise` / `Sunrise`; `Sunset` / `Sunset`; `Golden hour` / `Morning golden hour: sun 4° below to 6° above the horizon` (and `Evening …`); `Blue hour` / `Morning blue hour: sun 6° to 4° below the horizon` (and `Evening …`).
- Window: location-local today −7 days to +365 days, inclusive.
- Coordinates rounded to 2 decimals before any URL or UID.
- `name`: default `Daylight`, control chars stripped, max 60 chars.
- ICS times in UTC with `Z`; CRLF; lines folded at 75 octets; feed < 1,000,000 bytes.
- Ported astral code keeps the astral Apache-2.0 copyright notice; `LICENSES/astral-APACHE-2.0.txt` included.
- Page: no framework, no build step; one Nominatim request per submit; OpenStreetMap attribution visible.
- Code style per `~/github/CLAUDE.md`: JSDoc on exported functions, comments explain why.

## Review Focus

1. **Sunset before sunrise on the same local date** (Reykjavik 2026-06-21): the daylight block must run from sunrise to the first sunset *after* it, never backwards. Test in Task 4.
2. **Civil twilight never ends but the sun still sets** (Reykjavik midsummer): sunrise/sunset events must still appear (the CLI drops them). Test in Task 4.
3. **Locations far from UTC** (Auckland, Honolulu, Kiritimati UTC+14): events attributed to the correct local date, no duplicates or gaps across the window. Fixtures in Task 1, test in Task 4.
4. **DST transition days** (Brooklyn 2026-03-08, 2026-11-01; Sydney 2026-04-05, 2026-10-04): UTC times correct, local date iteration doesn't skip or repeat a day. Fixtures in Task 1, test in Task 4.
5. **Hostile `name` values** (commas, semicolons, newlines, emoji, 200 chars): escaped, folded on UTF-8 boundaries, truncated, never breaks the ICS. Tests in Tasks 5 and 6.

---

### Task 1: Repo scaffold and astral fixtures

**Files:**
- Create: `package.json`, `.gitignore`, `LICENSE`, `LICENSES/astral-APACHE-2.0.txt`, `README.md` (stub), `CLAUDE.md`, `PROJECT.md`, `docs/superpowers/specs/2026-11-26-daylight-subscribe-design.md` (copied), this plan (copied)
- Create: `tools/make_fixtures.py`, `tools/requirements.txt` (`astral==3.2`, `timezonefinder>=8.2.1`)
- Create: `test/fixtures/sun.json` (generated, committed)
- Test: `test/fixtures.test.js`

**Interfaces:**
- Produces: `test/fixtures/sun.json`, an array of
  `{name: string, lat: number, lon: number, tz: string, date: "YYYY-MM-DD", sunrise: ISO|null, sunset: ISO|null, golden_morning: [ISO, ISO]|null, golden_evening: [ISO, ISO]|null, blue_morning: [ISO, ISO]|null, blue_evening: [ISO, ISO]|null}`
  where ISO is a UTC string like `2026-12-01T12:03:14.512Z`, `null` where astral raises `ValueError`.

- [ ] **Step 1:** `git init`, `npm init -y`, set `"type": "module"`, scripts `"test": "vitest run"`, `"dev": "wrangler dev"`, `"deploy": "wrangler deploy"`; `npm i -D vitest wrangler`; `npm i @photostructure/tz-lookup`. `.gitignore` covers Node, Python, macOS, IDE, `.wrangler/`, `.dev.vars`.
- [ ] **Step 2: Write `tools/make_fixtures.py`** (`#!/usr/bin/env python3`, type hints, `--output` flag, default `test/fixtures/sun.json`). Locations: Brooklyn (40.66545, -73.98875), London (51.5072, -0.1276), Sydney (-33.8688, 151.2093), Quito (-0.1807, -78.4678), Auckland (-36.8485, 174.7633), Honolulu (21.3069, -157.8583), Kiritimati (1.8721, -157.4278), Reykjavik (64.1466, -21.9426), Tromsø (69.6492, 18.9553). Dates: every 5th day of 2026 plus 2026-03-08, 2026-03-29, 2026-04-05, 2026-06-21, 2026-10-04, 2026-10-25, 2026-11-01, 2026-12-21. tz from `TimezoneFinder().timezone_at`. Call `astral.sun.sunrise`, `sunset`, `golden_hour`, `blue_hour` individually with `Observer(lat, lon)` and `ZoneInfo(tz)`; never `sun()` (it raises when civil dawn fails; see spec). Catch `ValueError` per value → `null`.
- [ ] **Step 3:** Run `python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt && .venv/bin/python tools/make_fixtures.py`. Expected: file written; stderr prints the entry count (≈ 9 × 81). Add `.venv/` to `.gitignore`.
- [ ] **Step 4: Write `test/fixtures.test.js`**, a sanity check on the ground truth:
  ```js
  test('Reykjavik midsummer has sunrise and sunset but astral sunset precedes sunrise', () => {
    const f = fixture('Reykjavik', '2026-06-21');
    expect(f.sunrise).not.toBeNull();
    expect(f.sunset).not.toBeNull();
    expect(new Date(f.sunset) < new Date(f.sunrise)).toBe(true);
  });
  test('Tromsø has no sunrise on 2026-06-21 or 2026-12-21', () => { /* both sunrise null */ });
  test('Brooklyn 2026-12-01 sunrise is 12:00 UTC', () => { /* sunrise starts with '2026-12-01T12:00' (astral: 12:00:47) */ });
  ```
- [ ] **Step 5:** `npm test`. Expected: 3 pass (the data is real, so there is no red step for this sanity test; if any fails, the fixture generator is wrong, so stop and investigate).
- [ ] **Step 6:** Commit `"Scaffold project and generate astral 3.2 fixtures"`.

### Task 2: Time zone helpers

**Files:**
- Create: `src/tz.js`
- Test: `test/tz.test.js`

**Interfaces:**
- Produces:
  - `lookupTimeZone(lat: number, lon: number): string`: IANA name via `@photostructure/tz-lookup`.
  - `localDate(instant: Date, timeZone: string): string`: `YYYY-MM-DD` at that instant in that zone (use `Intl.DateTimeFormat('en-CA', {timeZone, year, month, day})`).
  - `addDays(isoDate: string, n: number): string`: pure calendar arithmetic on the date string (via `Date.UTC`), no time zone involved.

- [ ] **Step 1: Failing tests:** for every distinct location in `sun.json`, `lookupTimeZone(lat, lon) === tz`; `localDate(new Date('2026-06-21T00:02:38Z'), 'Atlantic/Reykjavik') === '2026-06-21'`; `localDate(new Date('2026-12-31T10:30:00Z'), 'Pacific/Kiritimati') === '2027-01-01'`; `addDays('2026-03-08', 1) === '2026-03-09'`; `addDays('2026-01-03', -7) === '2025-12-27'`; `addDays('2028-02-28', 1) === '2028-02-29'`.
- [ ] **Step 2:** `npx vitest run test/tz.test.js`. Expected: FAIL, module not found.
- [ ] **Step 3:** Implement `src/tz.js`. If `tz-lookup` disagrees with timezonefinder for a fixture location, don't change the test: report it (it would mean real users get wrong dates).
- [ ] **Step 4:** Run again. Expected: PASS.
- [ ] **Step 5:** Commit `"Add time zone helpers"`.

### Task 3: Sun math port (sunrise, sunset, golden hour, blue hour)

**Files:**
- Create: `src/sun.js` (header: astral copyright line + Apache-2.0 notice + "Ported from astral 3.2 astral/sun.py")
- Test: `test/sun.test.js`

**Interfaces:**
- Consumes: `localDate` from Task 2.
- Produces:
  - `sunrise(lat: number, lon: number, isoDate: string, timeZone: string): Date | null`
  - `sunset(lat: number, lon: number, isoDate: string, timeZone: string): Date | null`
  - `sunBand(lat: number, lon: number, isoDate: string, timeZone: string, band: 'golden' | 'blue', direction: 'rising' | 'setting'): {start: Date, end: Date} | null`
  - Each returns exactly what astral's same-named function returns for that local date (including its date-retry behaviour), or `null` where astral raises.
  - `sunsetAfter(lat: number, lon: number, sunrise: Date): Date | null`: earliest raw `timeOfTransit` sunset for the UTC dates −1, 0, +1 around `sunrise` that is after it and less than 24 h later (port of the CLI's `sunset_after`).

- [ ] **Step 1: Failing test:** table-driven over every fixture entry: for each of `sunrise`, `sunset`, and the four bands, `null` ⇔ `null`, otherwise `|js − fixture| ≤ 5000 ms`. One `test.each` per quantity so failures name location and date. Plus: `sunsetAfter(64.1466, -21.9426, sunrise('2026-06-27'))` is within 5 s of `2026-06-28T00:00:11Z`; for Tromsø's last sunrise before the midnight sun, `sunsetAfter(69.6492, 18.9553, sunrise('2026-05-17'))` is within 5 s of `2026-05-17T22:20:31Z` (local 00:20 the next day).
- [ ] **Step 2:** `npx vitest run test/sun.test.js`. Expected: FAIL, module not found.
- [ ] **Step 3:** Port from astral 3.2 `sun.py` (read it from `.venv/lib/python3.13/site-packages/astral/sun.py`): the NOAA helper chain (`julianday` … `hour_angle`), `refraction_at_zenith`, `adjust_to_horizon` (elevation 0), `time_of_transit`, `time_at_elevation`, `sunrise`, `sunset`, `golden_hour`, `blue_hour`, keeping astral's local-date adjustment logic and its `ValueError` conditions (return `null` instead). Keep helper names identical to astral's (camelCased) so a reviewer can diff them side by side. Export only the four functions above.
- [ ] **Step 4:** Run again. Expected: PASS for all entries. If a few entries miss, compare against astral step by step; do not widen the tolerance.
- [ ] **Step 5:** Commit `"Port astral sunrise, sunset, golden and blue hour"`.

### Task 4: Event building

**Files:**
- Create: `src/events.js`
- Test: `test/events.test.js`

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces:
  - `buildEvents(opts: {lat: number, lon: number, timeZone: string, startDate: string, endDate: string, mode: 'block' | 'separate', golden: boolean, blue: boolean}): Event[]`, sorted by `start`.
  - `Event = {type: 'daylight'|'sunrise'|'sunset'|'golden-hour-morning'|'golden-hour-evening'|'blue-hour-morning'|'blue-hour-evening', date: string, summary: string, description: string, start: Date, end: Date}` (summaries/descriptions per Global Constraints).

- [ ] **Step 1: Failing tests:**
  - `block`, Brooklyn 2026-12-01..2026-12-07: 7 events, all `Daylight`, each `start` within 5 s of the fixture-equivalent `sunrise()` result.
  - `separate`, same range: 14 events; each `Sunset` ends at `sunset()` and starts 30 min earlier.
  - `golden` + `blue` + `block`, Brooklyn 2026-12-01: 5 events, order blue-morning, golden-morning, daylight, golden-evening, blue-evening.
  - Reykjavik 2026-06-20..2026-06-22, `block`: 3 `Daylight` events, every `end > start`, each `end` is the first sunset after its `start` (Review Focus 1, 2).
  - Reykjavik 2026-06-01..2026-07-31, `block`: 61 events, none overlapping; 2026-06-27 ends at `2026-06-28T00:00:11Z` (±5 s). Same values as the CLI's `test_white_nights_daylight_never_overlaps`.
  - Tromsø 2026-06-21 `block` + `blue`: no `Daylight` event; blue hours included only where `sunBand` is non-null.
  - Brooklyn 2026-03-01..2026-03-15 and Sydney 2026-09-28..2026-10-10: exactly one `Daylight` per date, dates consecutive (Review Focus 4).
  - Kiritimati and Auckland, a 30-day range: exactly one `Daylight` per date, each event's `localDate(start, tz) === date` (Review Focus 3).
- [ ] **Step 2:** `npx vitest run test/events.test.js`. Expected: FAIL.
- [ ] **Step 3:** Implement. Iterate dates with `addDays` from `startDate` to `endDate`. For `block`, the end is the earliest raw sunset `timeOfTransit` for the UTC dates −1, 0, +1 around the sunrise that is after the sunrise and less than 24 h later; if none, skip the day. (Per-date `sunset()` is not enough: Reykjavik 2026-06-28 has two sunsets and astral returns only one; see `sunset_after` in the Python CLI.) Use `sunsetAfter` from Task 3. For `separate`, emit each of sunrise/sunset independently when non-null, applying the same "after sunrise" rule only to block mode.
- [ ] **Step 4:** Run again. Expected: PASS.
- [ ] **Step 5:** Commit `"Build daylight, sunrise/sunset and photo-hour events"`.

### Task 5: ICS serialization

**Files:**
- Create: `src/ics.js`
- Test: `test/ics.test.js`

**Interfaces:**
- Consumes: `Event` from Task 4.
- Produces: `toIcs(opts: {events: Event[], calendarName: string, timeZone: string, lat: number, lon: number, dtstamp: Date}): string`.
  - Header lines in order: `BEGIN:VCALENDAR`, `VERSION:2.0`, `PRODID:-//daylight-subscribe//EN`, `CALSCALE:GREGORIAN`, `METHOD:PUBLISH`, `X-WR-CALNAME:<escaped name>`, `X-WR-TIMEZONE:<tz>`, `REFRESH-INTERVAL;VALUE=DURATION:P1D`, `X-PUBLISHED-TTL:P1D`.
  - Per event: `UID:<YYYYMMDD>-<type>-<lat>_<lon>@daylight-subscribe` (lat/lon as given, already rounded), `DTSTAMP`, `DTSTART`, `DTEND` as `YYYYMMDDTHHMMSSZ` (seconds truncated, like the CLI), `SUMMARY`, `DESCRIPTION`, `TRANSP:TRANSPARENT`.

- [ ] **Step 1: Failing tests:**
  - Output starts with `BEGIN:VCALENDAR\r\n`, ends with `END:VCALENDAR\r\n`, contains no bare `\n`.
  - A Brooklyn `Daylight` event at `2026-12-01T12:00:47.962Z` renders `DTSTART:20261201T120047Z`.
  - UID for that event: `20261201-daylight-40.67_-73.99@daylight-subscribe`.
  - `calendarName: 'Sun; rise, set\nnow'` renders `X-WR-CALNAME:Sun\; rise\, set\nnow` (literal backslash-n).
  - Every line's UTF-8 byte length ≤ 75; a 60-char emoji name folds without splitting a code point (`Buffer.from(unfolded).toString()` round-trips) (Review Focus 5).
  - Unfolding (remove `\r\n ` sequences) restores the original description of `Golden hour` events, including `°`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement escaping (`\\`, `;`, `,`, newline) and folding by UTF-8 bytes (continuation lines start with one space and count it).
- [ ] **Step 4:** Run; expected PASS.
- [ ] **Step 5:** Commit `"Serialize events to RFC 5545 ICS"`.

### Task 6: Worker request handling and deploy config

**Files:**
- Create: `src/worker.js`, `wrangler.toml` (`name = "daylight-subscribe"`, `main = "src/worker.js"`, current `compatibility_date`)
- Test: `test/worker.test.js`

**Interfaces:**
- Consumes: Tasks 2, 4, 5.
- Produces:
  - `handleRequest(request: Request, now: Date): Promise<Response>` (exported for tests).
  - `export default { fetch: (request) => handleRequest(request, new Date()) }`.
  - Public feed contract (the page builds these URLs): `/cal.ics?lat=<num>&lon=<num>[&mode=block|separate][&golden=1][&blue=1][&name=<text>]`.

- [ ] **Step 1: Failing tests** (Node's global `Request`, fixed `now = new Date('2026-11-26T15:00:00Z')`):
  - `GET /cal.ics?lat=40.66545&lon=-73.98875` → 200, headers exactly per spec (`text/calendar; charset=utf-8`, `inline; filename="daylight.ics"`, `public, max-age=86400`, `*`); body contains `X-WR-CALNAME:Daylight`, `X-WR-TIMEZONE:America/New_York`; first event date `20261119`, last `20271126`; UIDs use `40.67_-73.99`.
  - `HEAD` → 200, empty body. `POST` → 405. `/other` → 404.
  - Missing `lat` → 400 mentioning `lat`; `lat=91` → 400; `lon=abc` → 400; `mode=weekly` → 400 mentioning `mode`.
  - `name` with control characters and 200 chars → 200; `X-WR-CALNAME` value (unescaped) is ≤ 60 chars, no control chars (Review Focus 5).
  - `mode=separate&golden=1&blue=1` → body byte length < 1,000,000.
  - DTSTAMP is `20261126T000000Z`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement: parse, validate, round lat/lon to 2 decimals (`Math.round(x * 100) / 100`), `timeZone = lookupTimeZone`, `today = localDate(now, tz)`, window `addDays(today, -7)`..`addDays(today, 365)`.
- [ ] **Step 4:** Run; expected PASS. Then `npx wrangler dev` and `curl -i 'http://localhost:8787/cal.ics?lat=40.67&lon=-73.99&golden=1'`. Expected: 200 and a valid calendar.
- [ ] **Step 5:** Commit `"Serve the ICS feed from a Cloudflare Worker"`.

### Task 7: Static page

**Files:**
- Create: `site/index.html`, `site/style.css`, `site/app.js` (DOM wiring only), `site/links.js` (pure functions), `site/config.js` (`export const FEED_BASE = 'https://daylight-subscribe.<subdomain>.workers.dev';`)
- Test: `test/links.test.js`

**Interfaces:**
- Consumes: the feed contract from Task 6.
- Produces (`site/links.js`):
  - `feedUrl(base: string, opts: {lat: number, lon: number, mode: 'block'|'separate', golden: boolean, blue: boolean, name: string}): string`: lat/lon rounded to 2 decimals; params in order `lat, lon, mode, golden, blue, name`; omits `mode=block`, false flags, and `name` when it equals `Daylight`.
  - `webcalUrl(httpsUrl: string): string`
  - `googleSubscribeUrl(httpsUrl: string): string`: `https://calendar.google.com/calendar/r?cid=` + `encodeURIComponent(webcalUrl(httpsUrl))`.
  - `geocode(query: string, fetchFn: typeof fetch): Promise<{lat: number, lon: number, label: string} | null>`: `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=<encoded>`; `null` on empty results; throws with a readable message on non-200.

- [ ] **Step 1: Failing tests:**
  - `feedUrl('https://x.dev', {lat: 40.66545, lon: -73.98875, mode: 'block', golden: false, blue: false, name: 'Daylight'}) === 'https://x.dev/cal.ics?lat=40.67&lon=-73.99'`.
  - With `mode: 'separate', golden: true, blue: true, name: 'Daylight · Brooklyn'` → `…?lat=40.67&lon=-73.99&mode=separate&golden=1&blue=1&name=Daylight+%C2%B7+Brooklyn`.
  - `webcalUrl('https://x.dev/cal.ics?lat=1&lon=2') === 'webcal://x.dev/cal.ics?lat=1&lon=2'`.
  - `googleSubscribeUrl('https://x.dev/cal.ics?lat=1&lon=2') === 'https://calendar.google.com/calendar/r?cid=webcal%3A%2F%2Fx.dev%2Fcal.ics%3Flat%3D1%26lon%3D2'`.
  - `geocode` with a fake fetch returning `[{lat: '40.65', lon: '-73.95', display_name: 'Brooklyn, …'}]` → numbers parsed; with `[]` → `null`; with status 429 → throws.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement `links.js`, then the page: place field + Find button (disabled while a request is in flight), Use my location, resolved place line, options (radio: one block / sunrise and sunset; checkboxes: golden hour, blue hour; name field prefilled `Daylight · <first part of label>`), and actions (Add to Google Calendar opens a new tab; Add to Apple Calendar; Copy link; Download .ics), all disabled until a location is set. Footer: "Place search © OpenStreetMap contributors" linking to osm.org/copyright, and a link to the Python CLI repo. Under the Google button, one muted line: subscribing works from Google Calendar on the web; it then appears on the phone too.
- [ ] **Step 4:** Run tests; expected PASS. Then `npx serve site` (or `python3 -m http.server -d site`) with `config.js` pointed at `http://localhost:8787` and `wrangler dev` running; search "Brooklyn", toggle options, and check that Copy link and Download .ics produce the expected feed.
- [ ] **Step 5:** Commit `"Add the subscribe page"`.

### Task 8: Deploy and end-to-end check

**Files:**
- Create: `.github/workflows/pages.yml` (deploy `site/` with `actions/upload-pages-artifact` + `actions/deploy-pages` on push to `main`)
- Modify: `site/config.js` (real Worker URL), `README.md`, `PROJECT.md`
- Modify (other repos): `~/github/PROJECTS.md` (registry entry), `~/github/daylight-calendar/README.md` (one line linking the page)

- [ ] **Step 1:** `npx wrangler login` (user runs it: `! npx wrangler login`), `npm run deploy`. Expected: a `*.workers.dev` URL; `curl -I '<url>/cal.ics?lat=40.67&lon=-73.99'` → 200 `text/calendar`.
- [ ] **Step 2:** Set `FEED_BASE`, create the GitHub repo (ask the user before creating/pushing), enable Pages from Actions, push. Expected: page live at `https://<user>.github.io/daylight-subscribe/`.
- [ ] **Step 3: Manual checks** (record results in PROJECT.md, including anything that didn't work):
  - Google Calendar web: Add to Google Calendar → confirm dialog → a separate calendar named per `name` appears with events in the right local times.
  - Apple Calendar on macOS and iOS: webcal link → Subscribe dialog → separate calendar.
  - Google Calendar on a phone: note what the cid link actually does there and update the hint line if needed.
  - Validate one feed at https://icalendar.org/validator.html.
- [ ] **Step 4:** README: what it is, the page link, the feed URL format, how to run tests, regenerate fixtures, and deploy; how to move the page to another host (copy `site/`, set `FEED_BASE`). PROJECT.md: architecture, decisions (from the spec's Approaches), the CLI's `sun()` bug, next steps (custom domain for the feed, personal-site hosting).
- [ ] **Step 5:** Commit `"Deploy Worker and page; document"`.
