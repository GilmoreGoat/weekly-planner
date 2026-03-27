from __future__ import annotations

"""
Orchestrator — merges events from all sources and uses any configured LLM
to deduplicate, prioritize, and return a structured weekly plan.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _serialize_events(events: list[dict[str, Any]]) -> str:
    return json.dumps(events, indent=2, default=str)


def deduplicate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str | None]] = set()
    unique = []
    for e in events:
        key = (e.get("title", "").strip().lower(), e.get("date"))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def orchestrate_with_llm(
    instagram_events: list[dict[str, Any]],
    canvas_events: list[dict[str, Any]],
    notes_data: dict[str, Any],
    llm_client: Any,
) -> dict[str, Any]:
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
- Merge semantic duplicates (same event from multiple sources)
- Priority 1 = critical (due today/tomorrow, exams), 2 = high (due this week), 3 = medium, 4 = low
- Sort schedule and events by date ascending
- Sort tasks by priority then due_date
- Return ONLY valid JSON, no markdown fences, no extra text"""

    raw = llm_client.chat(prompt, max_tokens=4096)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        import re
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
            except json.JSONDecodeError:
                result = _fallback_structure(all_raw_events, goals, reminders)
        else:
            result = _fallback_structure(all_raw_events, goals, reminders)

    result.setdefault("schedule", [])
    result.setdefault("tasks", [])
    result.setdefault("events", [])
    result.setdefault("summary", "Weekly plan generated.")
    result["all_items"] = all_raw_events

    logger.info("Orchestration complete: %d schedule, %d tasks, %d events",
                len(result["schedule"]), len(result["tasks"]), len(result["events"]))
    return result


def _fallback_structure(events, goals, reminders):
    tasks = (
        [{"title": g, "due_date": None, "source": "notes", "priority": 3, "priority_label": "medium", "category": "goal", "notes": ""} for g in goals]
        + [{"title": r, "due_date": None, "source": "notes", "priority": 2, "priority_label": "high", "category": "reminder", "notes": ""} for r in reminders]
    )
    schedule = [
        {"title": e.get("title",""), "date": e.get("date"), "time": None, "location": e.get("location"),
         "link": e.get("link"), "source": e.get("source",""), "type": e.get("type","event"),
         "priority": 2, "priority_label": "high", "description": e.get("description","")}
        for e in events if e.get("date")
    ]
    return {"schedule": schedule, "tasks": tasks, "events": events,
            "summary": f"Your week has {len(events)} events and {len(tasks)} tasks."}


def run(instagram_events, canvas_events, notes_data, llm_client=None):
    if llm_client is None:
        from src.llm_client import LLMClient
        llm_client = LLMClient.from_env()
    return orchestrate_with_llm(instagram_events, canvas_events, notes_data, llm_client)
