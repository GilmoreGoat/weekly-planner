from __future__ import annotations

"""
Parses weekly_notes.txt for goals, reminders, and personal items.
Supports both freeform text and a structured markdown format.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Section headers to look for (case-insensitive)
SECTION_PATTERNS = {
    "goals": re.compile(r"^#{1,3}\s*goals?\b", re.IGNORECASE | re.MULTILINE),
    "reminders": re.compile(r"^#{1,3}\s*reminders?\b", re.IGNORECASE | re.MULTILINE),
    "personal": re.compile(
        r"^#{1,3}\s*personal\s*(items?|notes?|events?)?\b", re.IGNORECASE | re.MULTILINE
    ),
    "notes": re.compile(r"^#{1,3}\s*notes?\b", re.IGNORECASE | re.MULTILINE),
    "events": re.compile(r"^#{1,3}\s*events?\b", re.IGNORECASE | re.MULTILINE),
}

# Patterns to detect dates in text lines
DATE_PATTERNS = [
    # "Tuesday at 10am", "Monday 3pm"
    re.compile(
        r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        re.IGNORECASE,
    ),
    # "March 30", "March 30th"
    re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?\b",
        re.IGNORECASE,
    ),
    # "3/30", "03/30"
    re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b"),
    # "by Friday", "on Thursday"
    re.compile(r"\b(?:by|on)\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", re.IGNORECASE),
]

# Patterns to detect time
TIME_PATTERN = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE)

# Patterns to detect location hints
LOCATION_PATTERN = re.compile(r"\bat\s+([A-Z][A-Za-z0-9 ]+(?:Center|Hall|Building|Room|Library|Cafe|Coffee|Park|Plaza)?)", re.IGNORECASE)


def _extract_bullet_items(text: str) -> list[str]:
    """Extract bullet-point items from a text block."""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("-", "*", "•", "+")):
            item = line.lstrip("-*•+ ").strip()
            if item:
                items.append(item)
        elif line and not line.startswith("#"):
            items.append(line)
    return items


def _extract_section(content: str, pattern: re.Pattern) -> str:
    """Extract text between this section header and the next one."""
    match = pattern.search(content)
    if not match:
        return ""

    start = match.end()

    # Find the next section header
    next_header = re.search(r"^#{1,3}\s+\w", content[start:], re.MULTILINE)
    end = start + next_header.start() if next_header else len(content)

    return content[start:end].strip()


def _infer_date(text: str, reference_date: datetime | None = None) -> str | None:
    """Try to extract a date string from a line of text."""
    ref = reference_date or datetime.now()

    # Named weekday
    weekday_match = re.search(
        r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
        text,
        re.IGNORECASE,
    )
    if weekday_match:
        day_name = weekday_match.group(1).capitalize()
        day_map = {
            "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
            "Friday": 4, "Saturday": 5, "Sunday": 6,
        }
        target_dow = day_map[day_name]
        current_dow = ref.weekday()
        days_ahead = (target_dow - current_dow) % 7
        if days_ahead == 0:
            days_ahead = 7
        target = ref.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        target = target + timedelta(days=days_ahead)

        # Try to extract time too
        time_m = TIME_PATTERN.search(text)
        if time_m:
            hour = int(time_m.group(1))
            minute = int(time_m.group(2) or 0)
            meridiem = time_m.group(3).lower()
            if meridiem == "pm" and hour != 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            target = target.replace(hour=hour, minute=minute)
            return target.strftime("%Y-%m-%dT%H:%M:00")
        return target.strftime("%Y-%m-%d")

    # Month + day
    month_match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?\b",
        text,
        re.IGNORECASE,
    )
    if month_match:
        month_str = month_match.group(1)
        day = int(month_match.group(2))
        month_map = {
            "January": 1, "February": 2, "March": 3, "April": 4,
            "May": 5, "June": 6, "July": 7, "August": 8,
            "September": 9, "October": 10, "November": 11, "December": 12,
        }
        month = month_map[month_str.capitalize()]
        year = ref.year
        if month < ref.month:
            year += 1
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def _infer_location(text: str) -> str | None:
    """Try to extract a location from a text line."""
    loc_match = LOCATION_PATTERN.search(text)
    if loc_match:
        return loc_match.group(1).strip()
    return None


def parse_notes_file(filepath: str) -> dict[str, Any]:
    """
    Parse a weekly_notes.txt file and return structured data.
    Returns: {goals, reminders, personal_events, raw_notes, all_items}
    """
    path = Path(filepath)
    if not path.exists():
        logger.warning("Notes file not found: %s", filepath)
        return {"goals": [], "reminders": [], "personal_events": [], "raw_notes": "", "all_items": []}

    content = path.read_text(encoding="utf-8")
    logger.info("Parsing notes file: %s (%d chars)", filepath, len(content))

    goals_text = _extract_section(content, SECTION_PATTERNS["goals"])
    reminders_text = _extract_section(content, SECTION_PATTERNS["reminders"])
    personal_text = _extract_section(content, SECTION_PATTERNS["personal"])
    events_text = _extract_section(content, SECTION_PATTERNS["events"])

    goals = _extract_bullet_items(goals_text)
    reminders = _extract_bullet_items(reminders_text)
    personal_raw = _extract_bullet_items(personal_text + "\n" + events_text)

    # Build structured personal events
    personal_events = []
    for item in personal_raw:
        date_str = _infer_date(item)
        location = _infer_location(item)
        personal_events.append(
            {
                "type": "personal_item",
                "title": item,
                "date": date_str,
                "location": location,
                "link": None,
                "source": "weekly_notes.txt",
                "description": item,
            }
        )

    # Also scan reminders for deadline dates
    reminder_events = []
    for r in reminders:
        date_str = _infer_date(r)
        if date_str:
            reminder_events.append(
                {
                    "type": "reminder",
                    "title": r,
                    "date": date_str,
                    "location": None,
                    "link": None,
                    "source": "weekly_notes.txt",
                    "description": r,
                }
            )

    all_items = personal_events + reminder_events

    return {
        "goals": goals,
        "reminders": reminders,
        "personal_events": personal_events,
        "reminder_events": reminder_events,
        "raw_notes": content,
        "all_items": all_items,
    }


def run(filepath: str = "weekly_notes.txt") -> dict[str, Any]:
    """Main entry point."""
    return parse_notes_file(filepath)
