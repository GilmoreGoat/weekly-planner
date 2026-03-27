from __future__ import annotations

"""
Adds events to Google Calendar via the Google Calendar API (OAuth2).
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# Configurable timezone — set TIMEZONE env var or pass via the sidebar
DEFAULT_TIMEZONE = os.environ.get("TIMEZONE", "America/Los_Angeles")


def _get_credentials(credentials_file: str, token_file: str):
    """Load or refresh Google OAuth2 credentials."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None

    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(credentials_file).exists():
                raise FileNotFoundError(
                    f"Google credentials file not found: {credentials_file}\n"
                    "Download it from Google Cloud Console → APIs & Services → Credentials"
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return creds


def _parse_datetime(date_str: str | None) -> tuple[str | None, bool]:
    """
    Parse a date string and return (formatted_string, is_all_day).
    Returns (None, False) if unparseable.
    """
    if not date_str:
        return None, False

    formats = [
        ("%Y-%m-%dT%H:%M:%S", False),
        ("%Y-%m-%dT%H:%M:%S%z", False),
        ("%Y-%m-%dT%H:%M:00", False),
        ("%Y-%m-%d", True),
    ]

    # Handle timezone-aware ISO strings
    if "+" in date_str or date_str.endswith("Z"):
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.isoformat(), False
        except ValueError:
            pass

    for fmt, all_day in formats:
        try:
            dt = datetime.strptime(date_str[:len(fmt.replace("%Y", "0000").replace("%m", "00")
                                                  .replace("%d", "00").replace("%H", "00")
                                                  .replace("%M", "00").replace("%S", "00")
                                                  .replace("%z", ""))], fmt)
            if all_day:
                return dt.strftime("%Y-%m-%d"), True
            return dt.isoformat(), False
        except ValueError:
            continue

    # Last resort: try dateutil if available
    try:
        from dateutil import parser as dateutil_parser
        dt = dateutil_parser.parse(date_str)
        return dt.isoformat(), False
    except Exception:
        pass

    return None, False


def _build_event_body(item: dict[str, Any], calendar_id: str) -> dict | None:
    """Convert a plan item to a Google Calendar event body."""
    title = item.get("title", "Untitled Event")
    date_str = item.get("date")
    description = item.get("description", "")
    location = item.get("location", "")
    source = item.get("source", "")

    if not date_str:
        return None

    parsed_date, is_all_day = _parse_datetime(date_str)
    if not parsed_date:
        return None

    if description and source:
        description = f"{description}\n\nSource: {source}"
    elif source:
        description = f"Source: {source}"

    if item.get("link"):
        description += f"\nLink: {item['link']}"

    if is_all_day:
        event = {
            "summary": title,
            "description": description,
            "location": location or None,
            "start": {"date": parsed_date},
            "end": {"date": parsed_date},
        }
    else:
        # Default duration: 1 hour
        start_dt = datetime.fromisoformat(parsed_date)
        end_dt = start_dt + timedelta(hours=1)
        event = {
            "summary": title,
            "description": description,
            "location": location or None,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": DEFAULT_TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": DEFAULT_TIMEZONE},
        }

    # Remove None values
    event = {k: v for k, v in event.items() if v is not None}
    return event


def add_events_to_calendar(
    plan: dict[str, Any],
    credentials_file: str | None = None,
    token_file: str | None = None,
    calendar_id: str | None = None,
    timezone: str | None = None,
) -> list[dict[str, Any]]:
    """
    Add schedule and personal events to Google Calendar.
    Returns a list of created event summaries with their Google Calendar links.
    """
    from googleapiclient.discovery import build

    # Allow caller or env to override the module-level default
    global DEFAULT_TIMEZONE
    if timezone:
        DEFAULT_TIMEZONE = timezone
    elif os.environ.get("TIMEZONE"):
        DEFAULT_TIMEZONE = os.environ["TIMEZONE"]

    creds_file = credentials_file or os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    tok_file = token_file or os.environ.get("GOOGLE_TOKEN_FILE", "token.json")
    cal_id = calendar_id or os.environ.get("GOOGLE_CALENDAR_ID", "primary")

    creds = _get_credentials(creds_file, tok_file)
    service = build("calendar", "v3", credentials=creds)

    # Collect items with dates from schedule and events
    items_to_add: list[dict[str, Any]] = []

    for item in plan.get("schedule", []):
        if item.get("date"):
            items_to_add.append(item)

    for item in plan.get("events", []):
        if item.get("date"):
            # Avoid adding duplicates already in schedule
            titles_in_schedule = {i.get("title", "").lower() for i in plan.get("schedule", [])}
            if item.get("title", "").lower() not in titles_in_schedule:
                items_to_add.append(item)

    created: list[dict[str, Any]] = []

    for item in items_to_add:
        event_body = _build_event_body(item, cal_id)
        if not event_body:
            logger.warning("Skipping item with unparseable date: %s", item.get("title"))
            continue

        try:
            created_event = service.events().insert(
                calendarId=cal_id, body=event_body
            ).execute()

            created.append(
                {
                    "title": item.get("title"),
                    "date": item.get("date"),
                    "gcal_link": created_event.get("htmlLink"),
                    "gcal_id": created_event.get("id"),
                }
            )
            logger.info("Created calendar event: %s", item.get("title"))
        except Exception as e:
            logger.error("Failed to create event '%s': %s", item.get("title"), e)

    logger.info("Added %d events to Google Calendar", len(created))
    return created


def run(
    plan: dict[str, Any],
    credentials_file: str | None = None,
    token_file: str | None = None,
    calendar_id: str | None = None,
    timezone: str | None = None,
) -> list[dict[str, Any]]:
    """Main entry point. Returns list of created events."""
    return add_events_to_calendar(plan, credentials_file, token_file, calendar_id, timezone)
