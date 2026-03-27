from __future__ import annotations

"""
Claude AI orchestrator — merges events from all sources, deduplicates,
and prioritizes by urgency, returning structured output for the dashboard.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

PRIORITY_LABELS = {1: "critical", 2: "high", 3: "medium", 4: "low"}


def _serialize_events(events: list[dict[str, Any]]) -> str:
    """Format events as a readable JSON block for the prompt."""
    return json.dumps(events, indent=2, default=str)


def deduplicate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Simple pre-dedup before sending to Claude: remove exact title+date duplicates.
    Claude will handle semantic duplicates.
    """
    seen: set[tuple[str, str | None]] = set()
    unique = []
    for e in events:
        key = (e.get("title", "").strip().lower(), e.get("date"))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def orchestrate_with_claude(
    instagram_events: list[dict[str, Any]],
    canvas_events: list[dict[str, Any]],
    notes_data: dict[str, Any],
    client: anthropic.Anthropic,
) -> dict[str, Any]:
    """
    Send all sources to Claude and get back a unified, prioritized weekly plan.

    Returns:
        {
            schedule: list of time-based items sorted by date,
            tasks: list of actionable tasks (assignments, goals, reminders),
            events: list of social/campus events,
            summary: markdown string,
            all_items: flat list with priority scores
        }
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    notes_items = notes_data.get("all_items", [])
    goals = notes_data.get("goals", [])
    reminders = notes_data.get("reminders", [])

    all_raw_events = deduplicate_events(instagram_events + canvas_events + notes_items)

    prompt = f"""You are a smart weekly planner assistant. Today is {now}.

You have received data from three sources:
1. Instagram events scraped from campus accounts
2. Canvas (LMS) assignments and due dates
3. Personal notes including goals, reminders, and personal appointments

## Source Data

### Instagram Events
{_serialize_events(instagram_events)}

### Canvas Assignments
{_serialize_events(canvas_events)}

### Personal Notes Items
Goals: {json.dumps(goals)}
Reminders: {json.dumps(reminders)}
Personal Events/Reminders with dates: {_serialize_events(notes_items)}

## Your Task

Produce a unified weekly plan JSON with exactly this structure:
{{
  "schedule": [
    {{
      "title": "...",
      "date": "ISO 8601 date or datetime",
      "time": "HH:MM or null",
      "location": "...",
      "link": "...",
      "source": "canvas|instagram|notes",
      "type": "assignment|event|appointment|reminder",
      "priority": 1-4,
      "priority_label": "critical|high|medium|low",
      "description": "..."
    }}
  ],
  "tasks": [
    {{
      "title": "...",
      "due_date": "ISO 8601 or null",
      "source": "...",
      "priority": 1-4,
      "priority_label": "...",
      "category": "academic|personal|reminder|goal",
      "notes": "..."
    }}
  ],
  "events": [
    {{
      "title": "...",
      "date": "ISO 8601",
      "location": "...",
      "link": "...",
      "source": "...",
      "description": "..."
    }}
  ],
  "summary": "markdown summary of the week (3-5 sentences covering key deadlines, events, and goals)"
}}

Rules:
- Merge semantic duplicates (same event from multiple sources → keep one, note sources)
- Priority 1 = critical (due today/tomorrow, exams), 2 = high (due this week), 3 = medium, 4 = low
- Sort schedule and events by date ascending
- Sort tasks by priority then due_date
- Tasks = things to DO (assignments, goals, reminders). Schedule = time-blocked items with dates. Events = campus/social events.
- Some items may appear in both schedule and tasks if they are both time-blocked and actionable
- Return ONLY valid JSON, no markdown fences, no extra text"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Claude orchestrator returned invalid JSON, attempting partial parse")
        # Try to extract JSON from the response
        import re
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
            except json.JSONDecodeError:
                result = _fallback_structure(all_raw_events, goals, reminders)
        else:
            result = _fallback_structure(all_raw_events, goals, reminders)

    # Ensure all required keys exist
    result.setdefault("schedule", [])
    result.setdefault("tasks", [])
    result.setdefault("events", [])
    result.setdefault("summary", "Weekly plan generated.")
    result["all_items"] = all_raw_events

    logger.info(
        "Orchestration complete: %d schedule items, %d tasks, %d events",
        len(result["schedule"]),
        len(result["tasks"]),
        len(result["events"]),
    )
    return result


def _fallback_structure(
    events: list[dict[str, Any]],
    goals: list[str],
    reminders: list[str],
) -> dict[str, Any]:
    """Return a minimal structure when Claude fails to parse."""
    tasks = [
        {
            "title": g,
            "due_date": None,
            "source": "notes",
            "priority": 3,
            "priority_label": "medium",
            "category": "goal",
            "notes": "",
        }
        for g in goals
    ] + [
        {
            "title": r,
            "due_date": None,
            "source": "notes",
            "priority": 2,
            "priority_label": "high",
            "category": "reminder",
            "notes": "",
        }
        for r in reminders
    ]

    schedule = [
        {
            "title": e.get("title", ""),
            "date": e.get("date"),
            "time": None,
            "location": e.get("location"),
            "link": e.get("link"),
            "source": e.get("source", ""),
            "type": e.get("type", "event"),
            "priority": 2,
            "priority_label": "high",
            "description": e.get("description", ""),
        }
        for e in events
        if e.get("date")
    ]

    return {
        "schedule": schedule,
        "tasks": tasks,
        "events": events,
        "summary": f"Your week has {len(events)} events and {len(tasks)} tasks.",
    }


def run(
    instagram_events: list[dict[str, Any]],
    canvas_events: list[dict[str, Any]],
    notes_data: dict[str, Any],
    anthropic_client: anthropic.Anthropic | None = None,
) -> dict[str, Any]:
    """Main entry point."""
    client = anthropic_client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return orchestrate_with_claude(instagram_events, canvas_events, notes_data, client)
