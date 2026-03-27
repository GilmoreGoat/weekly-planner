from __future__ import annotations

"""
Creates a weekly planner Notion page via the Notion API.
"""

import logging
import os
from datetime import datetime
from typing import Any

from notion_client import Client

logger = logging.getLogger(__name__)


def _priority_emoji(priority: int) -> str:
    return {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢"}.get(priority, "⚪")


def _rich_text(content: str) -> list[dict]:
    return [{"type": "text", "text": {"content": str(content)[:2000]}}]


def _heading(level: int, text: str) -> dict:
    tag = f"heading_{level}"
    return {
        "object": "block",
        "type": tag,
        tag: {"rich_text": _rich_text(text)},
    }


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(text)},
    }


def _bulleted_item(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text(text)},
    }


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _callout(text: str, emoji: str = "📅") -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": _rich_text(text),
            "icon": {"type": "emoji", "emoji": emoji},
        },
    }


def build_page_blocks(plan: dict[str, Any]) -> list[dict]:
    """Convert the orchestrator output into Notion block objects."""
    blocks: list[dict] = []

    # Summary callout
    summary = plan.get("summary", "")
    if summary:
        blocks.append(_callout(summary, "🗓️"))
        blocks.append(_divider())

    # --- Schedule ---
    if plan.get("schedule"):
        blocks.append(_heading(2, "📅 Schedule"))
        for item in plan["schedule"]:
            date_str = item.get("date", "")
            time_str = item.get("time", "")
            location = item.get("location", "")
            priority = item.get("priority", 3)
            emoji = _priority_emoji(priority)

            parts = [f"{emoji} {item.get('title', 'Untitled')}"]
            if date_str:
                parts.append(f"📆 {date_str}" + (f" at {time_str}" if time_str else ""))
            if location:
                parts.append(f"📍 {location}")
            if item.get("link"):
                parts.append(f"🔗 {item['link']}")
            if item.get("description"):
                parts.append(item["description"])

            blocks.append(_bulleted_item("  |  ".join(parts)))
        blocks.append(_divider())

    # --- Tasks ---
    if plan.get("tasks"):
        blocks.append(_heading(2, "✅ Tasks"))
        for task in plan["tasks"]:
            priority = task.get("priority", 3)
            emoji = _priority_emoji(priority)
            title = task.get("title", "Untitled")
            due = task.get("due_date", "")
            category = task.get("category", "")
            parts = [f"{emoji} [{category.upper()}] {title}"]
            if due:
                parts.append(f"Due: {due}")
            if task.get("notes"):
                parts.append(task["notes"])
            blocks.append(_bulleted_item("  |  ".join(parts)))
        blocks.append(_divider())

    # --- Events ---
    if plan.get("events"):
        blocks.append(_heading(2, "🎉 Events"))
        for event in plan["events"]:
            parts = [f"🎪 {event.get('title', 'Untitled')}"]
            if event.get("date"):
                parts.append(f"📆 {event['date']}")
            if event.get("location"):
                parts.append(f"📍 {event['location']}")
            if event.get("link"):
                parts.append(f"🔗 {event['link']}")
            if event.get("description"):
                parts.append(event["description"])
            blocks.append(_bulleted_item("  |  ".join(parts)))

    return blocks


def create_notion_page(
    plan: dict[str, Any],
    notion_token: str | None = None,
    parent_page_id: str | None = None,
) -> str:
    """
    Create a Notion page with the weekly plan.
    Returns the URL of the created page.
    """
    token = notion_token or os.environ.get("NOTION_API_KEY", "")
    parent_id = parent_page_id or os.environ.get("NOTION_PARENT_PAGE_ID", "")

    if not token:
        raise ValueError("NOTION_API_KEY is required")
    if not parent_id:
        raise ValueError("NOTION_PARENT_PAGE_ID is required")

    notion = Client(auth=token)

    week_str = datetime.now().strftime("Week of %B %d, %Y")
    title = f"Weekly Planner — {week_str}"

    blocks = build_page_blocks(plan)

    # Notion API allows max 100 blocks per request
    # Create page with first 100 blocks, then append the rest
    first_batch = blocks[:100]
    remaining = blocks[100:]

    page = notion.pages.create(
        parent={"type": "page_id", "page_id": parent_id},
        properties={
            "title": {"title": _rich_text(title)},
        },
        children=first_batch,
    )

    page_id = page["id"]
    page_url = page.get("url", f"https://www.notion.so/{page_id.replace('-', '')}")

    # Append remaining blocks in batches of 100
    for i in range(0, len(remaining), 100):
        batch = remaining[i : i + 100]
        notion.blocks.children.append(block_id=page_id, children=batch)

    logger.info("Created Notion page: %s", page_url)
    return page_url


def run(
    plan: dict[str, Any],
    notion_token: str | None = None,
    parent_page_id: str | None = None,
) -> str:
    """Main entry point. Returns the Notion page URL."""
    return create_notion_page(plan, notion_token, parent_page_id)
