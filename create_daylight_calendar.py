#!/usr/bin/env python3

import csv
import datetime
import argparse
import hashlib
import sys
from typing import Callable, Optional
from astral import LocationInfo, Observer, SunDirection
from astral.sun import sunrise as sunrise_time
from astral.sun import sunset as sunset_time
from astral.sun import time_of_transit, SUN_APPARENT_RADIUS
from astral.sun import blue_hour as blue_hour_times
from astral.sun import golden_hour as golden_hour_times
from timezonefinder import TimezoneFinder
from zoneinfo import ZoneInfo

try:
    from geopy.geocoders import Nominatim
    GEOPY_AVAILABLE = True
except ImportError:
    GEOPY_AVAILABLE = False

def geocode_location(location_name):
    """
    Geocode a location name to latitude and longitude using Nominatim.

    Args:
        location_name: Name of the location (e.g., "Brooklyn", "London, UK")

    Returns:
        tuple: (latitude, longitude, display_name)

    Raises:
        ValueError: If location cannot be found or geopy is not available
    """
    if not GEOPY_AVAILABLE:
        raise ValueError(
            "geopy library is required for location name lookup. "
            "Install it with: pip install geopy"
        )

    try:
        geolocator = Nominatim(user_agent="daylight-calendar-generator")
        location = geolocator.geocode(location_name, timeout=10)

        if location is None:
            raise ValueError(f"Could not find location: {location_name}")

        print(f"Found location: {location.address}")
        return location.latitude, location.longitude, location.address

    except Exception as e:
        raise ValueError(f"Error geocoding location '{location_name}': {e}")

# Generate an ICS file string manually to avoid extra dependencies
def generate_ics_content(events):
    """Generate ICS calendar content from a list of event dictionaries."""
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Daylight Calendar Generator//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for evt in events:
        ics_lines.append("BEGIN:VEVENT")
        ics_lines.append(f"UID:{evt['uid']}")
        ics_lines.append(f"DTSTAMP:{evt['dtstamp']}")
        ics_lines.append(f"DTSTART;TZID={evt['timezone']}:{evt['dtstart']}")
        ics_lines.append(f"DTEND;TZID={evt['timezone']}:{evt['dtend']}")
        ics_lines.append(f"SUMMARY:{evt['summary']}")
        ics_lines.append(f"DESCRIPTION:{evt['description']}")
        ics_lines.append("CLASS:PRIVATE")
        ics_lines.append("STATUS:CONFIRMED")
        ics_lines.append("TRANSP:TRANSPARENT")  # "Free" time (doesn't block calendar)
        ics_lines.append("END:VEVENT")

    ics_lines.append("END:VCALENDAR")
    return "\r\n".join(ics_lines) + "\r\n"  # ICS spec requires CRLF line endings

def format_datetime_ics(dt):
    """Format datetime for ICS: YYYYMMDDTHHmmss"""
    return dt.strftime("%Y%m%dT%H%M%S")

def generate_uid(date, event_type, lat, lng):
    """Generate a unique, stable UID for an event."""
    # Create a stable hash based on date, type, and location
    uid_string = f"{date.isoformat()}-{event_type}-{lat}-{lng}"
    hash_suffix = hashlib.md5(uid_string.encode()).hexdigest()[:8]
    return f"{date.strftime('%Y%m%d')}-{event_type}-{hash_suffix}@daylight-calendar"

def sun_time(time_for: Callable[..., datetime.datetime], observer: Observer,
             date: datetime.date, tz: datetime.tzinfo) -> Optional[datetime.datetime]:
    """Return astral's sunrise or sunset for a local date, or None if it doesn't happen.

    Args:
        time_for: astral's ``sunrise`` or ``sunset`` function.
        observer: Astral observer for the location.
        date: The local day to calculate for.
        tz: Time zone for the result.

    Returns:
        The time, or None when the sun doesn't rise or set that day (polar
        night or midnight sun).
    """
    # Don't use astral's sun(): it also computes civil dawn and dusk and raises
    # if either is missing, which drops sunrise and sunset in white nights.
    try:
        return time_for(observer, date, tz)
    except ValueError:
        return None


def sunset_after(observer: Observer, sunrise: datetime.datetime,
                 tz: datetime.tzinfo) -> Optional[datetime.datetime]:
    """Return the first sunset within 24 hours after a sunrise.

    Args:
        observer: Astral observer for the location.
        sunrise: The sunrise the daylight period starts with.
        tz: Time zone for the result.

    Returns:
        The sunset that ends this sunrise's daylight, or None if the sun
        doesn't set within a day (the start of midnight sun).
    """
    # astral's sunset() gives at most one sunset per local date. Near the
    # Arctic Circle in summer, sunset drifts back and forth across midnight:
    # one date's sunset can belong to the previous evening, and another date
    # can have two sunsets, one of which sunset() never returns. So take the
    # raw transit for the surrounding UTC dates and pick the first one after
    # sunrise, the same calculation sunset() itself uses.
    utc_date = sunrise.astimezone(datetime.timezone.utc).date()
    candidates = []
    for offset in (-1, 0, 1):
        try:
            candidates.append(time_of_transit(observer, utc_date + datetime.timedelta(days=offset),
                                              90.0 + SUN_APPARENT_RADIUS, SunDirection.SETTING))
        except ValueError:
            continue  # the sun doesn't set on that date
    later = [t for t in candidates if sunrise < t < sunrise + datetime.timedelta(days=1)]
    return min(later).astimezone(tz) if later else None


PHOTO_HOURS = {
    # name: (astral function, summary, sun elevation band as astral defines it)
    'golden-hour': (golden_hour_times, 'Golden hour', '4° below to 6° above the horizon'),
    'blue-hour': (blue_hour_times, 'Blue hour', '6° to 4° below the horizon'),
}


def photo_hour_events(observer: Observer, date: datetime.date, tz: datetime.tzinfo,
                      golden_hour: bool, blue_hour: bool) -> list[dict]:
    """Build morning and evening golden and/or blue hour events for one day.

    Args:
        observer: Astral observer for the location.
        date: The day to calculate for.
        tz: Time zone for the event times.
        golden_hour: Include golden hour events.
        blue_hour: Include blue hour events.

    Returns:
        Event dictionaries in the same shape as the daylight events. A period
        the sun doesn't reach on this day (common near the poles) is left out.
    """
    wanted = [name for name, enabled in (('golden-hour', golden_hour), ('blue-hour', blue_hour)) if enabled]
    events = []
    for name in wanted:
        times_for, summary, band = PHOTO_HOURS[name]
        for direction, part in ((SunDirection.RISING, 'morning'), (SunDirection.SETTING, 'evening')):
            try:
                start, end = times_for(observer, date, direction, tz)
            except ValueError:
                # astral's error here is a bare "math domain error"; say what it means.
                print(f"Skipping {part} {summary.lower()} on {date}: the sun doesn't reach it",
                      file=sys.stderr)
                continue
            events.append({
                'summary': summary,
                'description': f"{part.capitalize()} {summary.lower()}: sun {band}",
                'start': start,
                'end': end,
                'type': f"{name}-{part}",
                'date': date,
            })
    return events


def generate_daylight_calendar(lat, lng, start_date_str, end_date_str, filename="daylight_calendar.ics",
                               separate_events=False, format_type="ics", golden_hour=False, blue_hour=False):
    """
    Generate a calendar file with daylight hours for a specific location and date range.

    Args:
        lat: Latitude of the location
        lng: Longitude of the location
        start_date_str: Start date in YYYY-MM-DD format
        end_date_str: End date in YYYY-MM-DD format
        filename: Output filename
        separate_events: If True, create separate sunrise/sunset events; else single daylight event
        format_type: Output format - "ics" or "csv"
        golden_hour: If True, also add morning and evening golden hour events
        blue_hour: If True, also add morning and evening blue hour events
    """
    # 1. Setup Timezone and Location
    tf = TimezoneFinder()
    timezone_str = tf.timezone_at(lng=lng, lat=lat)

    if not timezone_str:
        print(f"Could not determine timezone for {lat}, {lng}. Defaulting to UTC.")
        timezone_str = "UTC"

    print(f"Detected Timezone: {timezone_str}")
    tz = ZoneInfo(timezone_str)

    # Create an Astral location object
    location = LocationInfo(
        name="Custom Location",
        region="Region",
        timezone=timezone_str,
        latitude=lat,
        longitude=lng
    )

    # 2. Parse Dates
    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()

    # 3. Collect events data
    events_data = []
    # RFC 5545 requires DTSTAMP in UTC form, marked with a trailing "Z".
    dtstamp = format_datetime_ics(datetime.datetime.now(datetime.timezone.utc)) + "Z"

    current_date = start_date

    while current_date <= end_date:
        sunrise = sun_time(sunrise_time, location.observer, current_date, tz)
        sunset = sun_time(sunset_time, location.observer, current_date, tz)
        # Polar night or midnight sun: skip only the missing events, since blue
        # or golden hour may still happen.
        missing = [name for name, time in (('sunrise', sunrise), ('sunset', sunset)) if time is None]
        if missing:
            print(f"No {' or '.join(missing)} on {current_date}", file=sys.stderr)

        if separate_events:
            if sunrise is not None:
                # Sunrise event: 30 minutes long, ending at sunrise
                sunrise_start = sunrise - datetime.timedelta(minutes=30)
                events_data.append({
                    'summary': 'Sunrise',
                    'description': 'Sunrise',
                    'start': sunrise_start,
                    'end': sunrise,
                    'type': 'sunrise',
                    'date': current_date
                })

            if sunset is not None:
                # Sunset event: 30 minutes long, ending at sunset
                sunset_start = sunset - datetime.timedelta(minutes=30)
                events_data.append({
                    'summary': 'Sunset',
                    'description': 'Sunset',
                    'start': sunset_start,
                    'end': sunset,
                    'type': 'sunset',
                    'date': current_date
                })
        elif sunrise is not None:
            daylight_end = sunset_after(location.observer, sunrise, tz)
            if daylight_end is None:
                print(f"Skipping daylight on {current_date}: the sun rises but doesn't set",
                      file=sys.stderr)
            else:
                # Single daylight event from sunrise to sunset
                events_data.append({
                    'summary': 'Daylight',
                    'description': 'Daylight hours from sunrise to sunset',
                    'start': sunrise,
                    'end': daylight_end,
                    'type': 'daylight',
                    'date': current_date
                })

        events_data.extend(photo_hour_events(location.observer, current_date, tz, golden_hour, blue_hour))

        current_date += datetime.timedelta(days=1)

    # Golden and blue hour overlap the daylight events in time, so order
    # by start rather than by the order the events were generated in.
    events_data.sort(key=lambda evt: evt['start'])

    # 4. Write output file based on format
    if format_type == "ics":
        # Generate ICS format
        ics_events = []
        for evt_data in events_data:
            ics_events.append({
                'uid': generate_uid(evt_data['date'], evt_data['type'], lat, lng),
                'dtstamp': dtstamp,
                'dtstart': format_datetime_ics(evt_data['start']),
                'dtend': format_datetime_ics(evt_data['end']),
                'summary': evt_data['summary'],
                'description': evt_data['description'],
                'timezone': timezone_str
            })

        ics_content = generate_ics_content(ics_events)
        with open(filename, mode='w', encoding='utf-8') as file:
            file.write(ics_content)

    else:  # CSV format
        headers = [
            "Subject", "Start Date", "Start Time",
            "End Date", "End Time", "All Day Event",
            "Description", "Private"
        ]

        with open(filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file, quoting=csv.QUOTE_ALL)
            writer.writerow(headers)

            for evt_data in events_data:
                row = [
                    evt_data['summary'],
                    evt_data['start'].strftime("%Y-%m-%d"),
                    evt_data['start'].strftime("%H:%M:%S"),
                    evt_data['end'].strftime("%Y-%m-%d"),
                    evt_data['end'].strftime("%H:%M:%S"),
                    "False",
                    evt_data['description'],
                    "True"
                ]
                writer.writerow(row)

    print(f"Successfully generated '{filename}' from {start_date_str} to {end_date_str}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Generate a calendar file (ICS or CSV) with daylight hours for a specific location and date range.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using location name (requires geopy library)
  %(prog)s --location "Brooklyn, NY" -s 2026-01-01 -e 2026-05-01

  # Using exact coordinates
  %(prog)s --lat 40.66545 --lon -73.98875 -s 2026-01-01 -e 2026-05-01

  # ICS with separate 30-minute sunrise and sunset events
  %(prog)s --location "London, UK" -s 2026-01-01 -e 2026-05-01 --separate-events

  # CSV format for Google Calendar import
  %(prog)s --location "Paris" -s 2026-01-01 -e 2026-05-01 -f csv -o paris.csv
        """
    )

    # Create mutually exclusive group for location specification
    location_group = parser.add_mutually_exclusive_group(required=True)

    location_group.add_argument(
        '-l', '--location',
        type=str,
        help='Location name (e.g., "Brooklyn", "London, UK", "Paris, France"). Requires geopy library.'
    )

    location_group.add_argument(
        '--lat', '--latitude',
        type=float,
        help='Latitude of the location (e.g., 40.66545 for Brooklyn, NY). Must be used with --lon.'
    )

    parser.add_argument(
        '--lon', '--longitude',
        type=float,
        help='Longitude of the location (e.g., -73.98875 for Brooklyn, NY). Must be used with --lat.'
    )

    parser.add_argument(
        '-s', '--start',
        type=str,
        required=True,
        help='Start date in YYYY-MM-DD format (e.g., 2026-01-01)'
    )

    parser.add_argument(
        '-e', '--end',
        type=str,
        required=True,
        help='End date in YYYY-MM-DD format (e.g., 2026-05-01)'
    )

    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output filename (default: daylight_calendar.ics or .csv based on format)'
    )

    parser.add_argument(
        '-f', '--format',
        type=str,
        choices=['ics', 'csv'],
        default='ics',
        help='Output format: ics (default) or csv'
    )

    parser.add_argument(
        '--separate-events',
        action='store_true',
        help='Create separate 30-minute sunrise and sunset events (both ending at actual time) instead of a single daylight event'
    )

    parser.add_argument(
        '--golden-hour',
        action='store_true',
        help='Also add morning and evening golden hour events (sun 4° below to 6° above the horizon)'
    )

    parser.add_argument(
        '--blue-hour',
        action='store_true',
        help='Also add morning and evening blue hour events (sun 6° to 4° below the horizon)'
    )

    args = parser.parse_args()

    # Validate date format
    try:
        datetime.datetime.strptime(args.start, "%Y-%m-%d")
        datetime.datetime.strptime(args.end, "%Y-%m-%d")
    except ValueError as e:
        parser.error(f"Invalid date format: {e}")

    # Resolve location to coordinates
    if args.location:
        # Use location name - geocode it
        try:
            lat, lon, address = geocode_location(args.location)
        except ValueError as e:
            parser.error(str(e))
            sys.exit(1)
    else:
        # Use coordinates - validate that both lat and lon are provided
        if args.lat is None or args.lon is None:
            parser.error("When using coordinates, both --lat and --lon must be specified")
        lat = args.lat
        lon = args.lon

    # Determine output filename if not specified
    if args.output is None:
        extension = 'ics' if args.format == 'ics' else 'csv'
        args.output = f'daylight_calendar.{extension}'

    generate_daylight_calendar(lat, lon, args.start, args.end,
                               args.output, args.separate_events, args.format,
                               golden_hour=args.golden_hour, blue_hour=args.blue_hour)