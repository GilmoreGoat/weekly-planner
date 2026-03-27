from __future__ import annotations

"""
Instagram scraper using Instaloader.
Reads handles from accounts.json, scrapes posts from the past N days,
and uses the configured LLM to extract structured event objects.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import instaloader

logger = logging.getLogger(__name__)


def load_accounts(accounts_file: str = "accounts.json") -> tuple[list[str], int]:
    with open(accounts_file) as f:
        data = json.load(f)
    return data.get("accounts", []), data.get("lookback_days", 7)


def scrape_posts(
    handles: list[str],
    lookback_days: int,
    ig_username: str | None = None,
    ig_password: str | None = None,
) -> list[dict[str, Any]]:
    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        quiet=True,
    )

    if ig_username and ig_password:
        try:
            L.login(ig_username, ig_password)
            logger.info("Logged into Instagram as %s", ig_username)
        except Exception as e:
            logger.warning("Instagram login failed: %s — continuing as anonymous", e)

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    posts: list[dict[str, Any]] = []

    for handle in handles:
        try:
            profile = instaloader.Profile.from_username(L.context, handle)
            for post in profile.get_posts():
                post_date = post.date_utc.replace(tzinfo=timezone.utc)
                if post_date < cutoff:
                    break
                posts.append({
                    "handle": handle,
                    "shortcode": post.shortcode,
                    "date": post_date.isoformat(),
                    "caption": post.caption or "",
                    "url": f"https://www.instagram.com/p/{post.shortcode}/",
                    "likes": post.likes,
                })
            logger.info("Scraped %d posts from @%s", len(posts), handle)
        except Exception as e:
            logger.error("Failed to scrape @%s: %s", handle, e)

    return posts


def extract_events_with_llm(
    posts: list[dict[str, Any]],
    llm_client: Any,
) -> list[dict[str, Any]]:
    if not posts:
        return []

    posts_text = "\n\n---\n\n".join(
        f"Account: @{p['handle']}\nDate posted: {p['date']}\nURL: {p['url']}\nCaption:\n{p['caption']}"
        for p in posts
    )

    prompt = f"""You are an event extraction assistant. Below are Instagram posts scraped from university/campus accounts.

Extract all events mentioned in these posts. For each event return a JSON object with:
- title: short descriptive event name
- date: ISO 8601 date string (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS), or null if unknown
- location: venue or place string, or null if unknown
- link: URL to more info (use the post URL if no better link is found), or null
- source: the Instagram handle it came from
- description: 1-2 sentence summary of the event

Return a JSON array of event objects. If no events are found, return an empty array [].
Only include actual events (not general posts). Today's date is {datetime.now().strftime('%Y-%m-%d')}.

Posts:
{posts_text}

Return only valid JSON, no markdown fences."""

    raw = llm_client.chat(prompt, max_tokens=2048)
    raw = raw.strip()

    try:
        events = json.loads(raw)
        if not isinstance(events, list):
            events = []
    except json.JSONDecodeError:
        logger.error("LLM returned invalid JSON for event extraction: %s", raw[:200])
        events = []

    for event in events:
        event["type"] = "instagram_event"

    return events


def run(
    accounts_file: str = "accounts.json",
    ig_username: str | None = None,
    ig_password: str | None = None,
    llm_client: Any = None,
) -> list[dict[str, Any]]:
    handles, lookback_days = load_accounts(accounts_file)
    logger.info("Scraping %d handles for the past %d days", len(handles), lookback_days)

    posts = scrape_posts(handles, lookback_days, ig_username, ig_password)
    logger.info("Total posts scraped: %d", len(posts))

    if not posts:
        return []

    if llm_client is None:
        from src.llm_client import LLMClient
        llm_client = LLMClient.from_env()

    events = extract_events_with_llm(posts, llm_client)
    logger.info("Extracted %d events from Instagram posts", len(events))
    return events
