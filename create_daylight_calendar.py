import csv
import datetime
import argparse
from astral import LocationInfo
from astral.sun import sun
from timezonefinder import TimezoneFinder
import pytz

def generate_daylight_csv(lat, lng, start_date_str, end_date_str, filename="daylight_calendar.csv"):
    # 1. Setup Timezone and Location
    # We use TimezoneFinder so this works for ANY location you reuse this for later
    tf = TimezoneFinder()
    timezone_str = tf.timezone_at(lng=lng, lat=lat)
    
    if not timezone_str:
        print(f"Could not determine timezone for {lat}, {lng}. Defaulting to UTC.")
        timezone_str = "UTC"
    
    print(f"Detected Timezone: {timezone_str}")
    tz = pytz.timezone(timezone_str)
    
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
    
    # 3. Prepare CSV File
    # headers as requested
    headers = [
        "Subject", "Start Date", "Start Time", 
        "End Date", "End Time", "All Day Event", 
        "Description", "Private"
    ]

    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        # quote_all ensures every field is wrapped in quotes
        writer = csv.writer(file, quoting=csv.QUOTE_ALL)
        writer.writerow(headers)

        current_date = start_date
        
        # 4. Iterate through date range
        while current_date <= end_date:
            try:
                # Calculate sun data for the specific date
                s = sun(location.observer, date=current_date, tzinfo=tz)
                
                sunrise = s['sunrise']
                sunset = s['sunset']

                # Format data for Google Calendar
                # Google CSV prefers:
                # Date: YYYY-MM-DD (or MM/DD/YYYY, but ISO is safer)
                # Time: HH:MM:SS (24hr)
                
                row = [
                    "Daylight",                         # Subject
                    sunrise.strftime("%Y-%m-%d"),       # Start Date
                    sunrise.strftime("%H:%M:%S"),       # Start Time
                    sunset.strftime("%Y-%m-%d"),        # End Date
                    sunset.strftime("%H:%M:%S"),        # End Time
                    "False",                            # All Day Event
                    "Daylight hours from sunrise to sunset", # Description
                    "True"                              # Private
                ]
                
                writer.writerow(row)
                
            except Exception as e:
                # Polar regions or calculation errors
                print(f"Skipping {current_date}: {e}")

            current_date += datetime.timedelta(days=1)

    print(f"Successfully generated '{filename}' from {start_date_str} to {end_date_str}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Generate a CSV calendar file with daylight hours for a specific location and date range.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --lat 40.66545 --lon -73.98875 --start 2026-01-01 --end 2026-05-01 -o brooklyn.csv
  %(prog)s -l 40.66545 -L -73.98875 -s 2026-01-01 -e 2026-05-01
        """
    )

    parser.add_argument(
        '--lat', '--latitude',
        type=float,
        required=True,
        help='Latitude of the location (e.g., 40.66545 for Brooklyn, NY)'
    )

    parser.add_argument(
        '--lon', '--longitude',
        type=float,
        required=True,
        help='Longitude of the location (e.g., -73.98875 for Brooklyn, NY)'
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
        default='daylight_calendar.csv',
        help='Output CSV filename (default: daylight_calendar.csv)'
    )

    args = parser.parse_args()

    # Validate date format
    try:
        datetime.datetime.strptime(args.start, "%Y-%m-%d")
        datetime.datetime.strptime(args.end, "%Y-%m-%d")
    except ValueError as e:
        parser.error(f"Invalid date format: {e}")

    generate_daylight_csv(args.lat, args.lon, args.start, args.end, args.output)