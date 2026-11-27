"""Characterization tests for create_daylight_calendar.py."""

import csv
import re
import subprocess
import sys
from pathlib import Path

import create_daylight_calendar as cdc

SCRIPT = Path(__file__).resolve().parent.parent / "create_daylight_calendar.py"

# Brooklyn, NY: the coordinates used in the script's own --help examples.
BROOKLYN = (40.66545, -73.98875)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_csv_daylight_event_times(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    cdc.generate_daylight_calendar(*BROOKLYN, "2026-01-01", "2026-01-02", str(out), format_type="csv")
    rows = _read_csv(out)
    assert len(rows) == 2
    first = rows[0]
    assert first["Subject"] == "Daylight"
    assert first["Start Date"] == "2026-01-01"
    # Values match the owner's previously generated brooklyn2026.csv.
    assert first["Start Time"] == "07:20:08"
    assert first["End Time"] == "16:39:14"


def test_csv_handles_dst_transition(tmp_path: Path) -> None:
    # 2026-03-08 is the US spring-forward date; times must be in local (EDT) time.
    out = tmp_path / "out.csv"
    cdc.generate_daylight_calendar(*BROOKLYN, "2026-03-07", "2026-03-08", str(out), format_type="csv")
    rows = _read_csv(out)
    est_sunrise, edt_sunrise = rows[0]["Start Time"], rows[1]["Start Time"]
    assert est_sunrise.startswith("06:")
    assert edt_sunrise.startswith("07:")


def test_separate_events_end_at_sun_times(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    cdc.generate_daylight_calendar(*BROOKLYN, "2026-01-01", "2026-01-01", str(out),
                                   separate_events=True, format_type="csv")
    sunrise, sunset = _read_csv(out)
    assert (sunrise["Subject"], sunrise["Start Time"], sunrise["End Time"]) == ("Sunrise", "06:50:08", "07:20:08")
    assert (sunset["Subject"], sunset["Start Time"], sunset["End Time"]) == ("Sunset", "16:09:14", "16:39:14")


def test_ics_structure(tmp_path: Path) -> None:
    out = tmp_path / "out.ics"
    cdc.generate_daylight_calendar(*BROOKLYN, "2026-01-01", "2026-01-03", str(out))
    raw = out.read_bytes().decode("utf-8")
    assert raw.startswith("BEGIN:VCALENDAR\r\n")
    assert raw.endswith("END:VCALENDAR\r\n")
    assert raw.count("BEGIN:VEVENT") == 3
    assert "DTSTART;TZID=America/New_York:20260101T072008\r\n" in raw
    assert "DTEND;TZID=America/New_York:20260101T163914\r\n" in raw
    dtstamp = next(line for line in raw.split("\r\n") if line.startswith("DTSTAMP:"))
    # RFC 5545: DTSTAMP must be in UTC, written with a trailing "Z".
    assert re.fullmatch(r"DTSTAMP:\d{8}T\d{6}Z", dtstamp), dtstamp


def test_uids_are_stable(tmp_path: Path) -> None:
    a, b = tmp_path / "a.ics", tmp_path / "b.ics"
    for path in (a, b):
        cdc.generate_daylight_calendar(*BROOKLYN, "2026-01-01", "2026-01-02", str(path))

    def uids(path: Path) -> list[str]:
        return [l for l in path.read_text().splitlines() if l.startswith("UID:")]

    assert uids(a) == uids(b)
    assert len(set(uids(a))) == 2


def test_polar_night_days_are_skipped(tmp_path: Path) -> None:
    # Tromsø has no sunrise in mid-December; those days are skipped, not fatal.
    out = tmp_path / "out.csv"
    cdc.generate_daylight_calendar(69.6492, 18.9553, "2026-12-20", "2026-12-21", str(out), format_type="csv")
    assert _read_csv(out) == []


def test_cli_requires_both_lat_and_lon(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--lat", "40.7", "-s", "2026-01-01", "-e", "2026-01-02"],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "both --lat and --lon" in result.stderr


def test_cli_default_output_name(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--lat", str(BROOKLYN[0]), "--lon", str(BROOKLYN[1]),
         "-s", "2026-01-01", "-e", "2026-01-01", "-f", "csv"],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "daylight_calendar.csv").exists()


def test_does_not_depend_on_pytz() -> None:
    # The standard library's zoneinfo (3.9+) replaces pytz; one less dependency.
    source = SCRIPT.read_text()
    assert "pytz" not in source


def _times(rows: list[dict[str, str]], subject: str) -> list[tuple[str, str]]:
    return [(r["Start Time"], r["End Time"]) for r in rows if r["Subject"] == subject]


def test_golden_hour_events(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    cdc.generate_daylight_calendar(*BROOKLYN, "2026-01-01", "2026-01-01", str(out),
                                   format_type="csv", golden_hour=True)
    rows = _read_csv(out)
    # astral's golden hour: sun from 4 degrees below to 6 degrees above the horizon.
    assert _times(rows, "Golden hour") == [("07:00:20", "08:02:18"), ("15:57:04", "16:59:02")]
    assert len(_times(rows, "Daylight")) == 1  # added alongside, not instead


def test_blue_hour_events(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    cdc.generate_daylight_calendar(*BROOKLYN, "2026-01-01", "2026-01-01", str(out),
                                   format_type="csv", blue_hour=True)
    rows = _read_csv(out)
    assert _times(rows, "Blue hour") == [("06:48:45", "07:00:20"), ("16:59:02", "17:10:37")]


def test_events_are_in_chronological_order(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    cdc.generate_daylight_calendar(*BROOKLYN, "2026-01-01", "2026-01-02", str(out), format_type="csv",
                                   separate_events=True, golden_hour=True, blue_hour=True)
    starts = [(r["Start Date"], r["Start Time"]) for r in _read_csv(out)]
    assert len(starts) == 2 * 6
    assert starts == sorted(starts)


def test_photo_events_have_distinct_stable_uids(tmp_path: Path) -> None:
    out = tmp_path / "out.ics"
    cdc.generate_daylight_calendar(*BROOKLYN, "2026-01-01", "2026-01-01", str(out),
                                   golden_hour=True, blue_hour=True)
    uids = [l for l in out.read_text().splitlines() if l.startswith("UID:")]
    assert len(uids) == 5
    assert len(set(uids)) == 5


def test_polar_night_keeps_blue_hour(tmp_path: Path) -> None:
    # In Tromsø in December the sun never rises (no daylight or golden hour),
    # but it does reach the blue-hour band. Missing events are skipped one by one.
    out = tmp_path / "out.csv"
    cdc.generate_daylight_calendar(69.6492, 18.9553, "2026-12-20", "2026-12-20", str(out),
                                   format_type="csv", golden_hour=True, blue_hour=True)
    rows = _read_csv(out)
    assert [r["Subject"] for r in rows] == ["Blue hour", "Blue hour"]


def test_cli_golden_and_blue_hour_flags(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--lat", str(BROOKLYN[0]), "--lon", str(BROOKLYN[1]),
         "-s", "2026-01-01", "-e", "2026-01-01", "-f", "csv", "--golden-hour", "--blue-hour"],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    subjects = [r["Subject"] for r in _read_csv(tmp_path / "daylight_calendar.csv")]
    assert subjects.count("Golden hour") == 2
    assert subjects.count("Blue hour") == 2


# Reykjavik, Iceland: in midsummer the sun sets but never drops 6° below the
# horizon, so there is no civil dawn or dusk, and sunset falls just after midnight.
REYKJAVIK = (64.1466, -21.9426)


def test_white_nights_keep_daylight(tmp_path: Path) -> None:
    # Daylight runs from sunrise to the next sunset, which is after midnight here.
    out = tmp_path / "out.csv"
    cdc.generate_daylight_calendar(*REYKJAVIK, "2026-06-20", "2026-06-21", str(out), format_type="csv")
    rows = _read_csv(out)
    spans = [(r["Start Date"], r["Start Time"], r["End Date"], r["End Time"]) for r in rows]
    assert spans == [
        ("2026-06-20", "02:56:15", "2026-06-21", "00:02:38"),
        ("2026-06-21", "02:56:20", "2026-06-22", "00:02:50"),
    ]


def test_white_nights_keep_separate_sunrise_and_sunset(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    cdc.generate_daylight_calendar(*REYKJAVIK, "2026-06-21", "2026-06-21", str(out),
                                   format_type="csv", separate_events=True)
    rows = _read_csv(out)
    events = [(r["Subject"], r["End Date"], r["End Time"]) for r in rows]
    # The sunset that falls on June 21 is the one just after midnight.
    assert events == [("Sunset", "2026-06-21", "00:02:38"), ("Sunrise", "2026-06-21", "02:56:20")]


def test_white_nights_daylight_never_overlaps(tmp_path: Path) -> None:
    # Sunset drifts back and forth across midnight, so one local date (June 28)
    # has two sunsets and astral's per-date sunset() returns only one of them.
    # June 27's daylight must end at the sunset just after midnight, not the next evening.
    out = tmp_path / "out.csv"
    cdc.generate_daylight_calendar(*REYKJAVIK, "2026-06-01", "2026-07-31", str(out), format_type="csv")
    rows = _read_csv(out)
    june_27 = next(r for r in rows if r["Start Date"] == "2026-06-27")
    assert (june_27["End Date"], june_27["End Time"]) == ("2026-06-28", "00:00:11")
    spans = [(r["Start Date"] + r["Start Time"], r["End Date"] + r["End Time"]) for r in rows]
    assert len(spans) == 61
    assert all(prev_end < start for (_, prev_end), (start, _) in zip(spans, spans[1:]))
