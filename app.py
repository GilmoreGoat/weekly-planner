"""
Weekly Planner — Streamlit Dashboard

Tabs: Schedule | Tasks | Events | Summary
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Weekly Planner",
    page_icon="🗓️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar — configuration
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🗓️ Weekly Planner")
    st.markdown("---")

    st.subheader("⚙️ Configuration")

    anthropic_key = st.text_input(
        "Anthropic API Key",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        type="password",
        help="Your Anthropic API key for Claude",
    )

    canvas_token = st.text_input(
        "Canvas API Token",
        value=os.environ.get("CANVAS_API_TOKEN", ""),
        type="password",
        help="Your Canvas API token (Account → Settings → Approved Integrations)",
    )

    canvas_base_url = st.text_input(
        "Canvas Base URL",
        value=os.environ.get("CANVAS_BASE_URL", ""),
        placeholder="https://canvas.yourschool.edu",
        help="Your school's Canvas domain (e.g. canvas.ucsd.edu)",
    )

    canvas_mcp_url = st.text_input(
        "Canvas MCP URL (optional)",
        value=os.environ.get("CANVAS_MCP_URL", ""),
        placeholder="https://ucsd-canvas-server.onrender.com",
        help="Base URL of a Canvas MCP SSE server. Leave blank to use Canvas REST API directly.",
    )

    notion_token = st.text_input(
        "Notion API Key",
        value=os.environ.get("NOTION_API_KEY", ""),
        type="password",
        help="Your Notion integration token",
    )

    notion_page_id = st.text_input(
        "Notion Parent Page ID",
        value=os.environ.get("NOTION_PARENT_PAGE_ID", ""),
        help="The Notion page ID where the weekly plan will be created",
    )

    ig_username = st.text_input(
        "Instagram Username (optional)",
        value=os.environ.get("IG_USERNAME", ""),
        help="For authenticated scraping (higher rate limits)",
    )
    ig_password = st.text_input(
        "Instagram Password (optional)",
        value=os.environ.get("IG_PASSWORD", ""),
        type="password",
    )

    user_timezone = st.text_input(
        "Timezone",
        value=os.environ.get("TIMEZONE", "America/Los_Angeles"),
        help="IANA timezone name for Google Calendar events (e.g. America/New_York, Europe/London)",
    )

    st.markdown("---")
    st.subheader("📤 Outputs")
    enable_notion = st.checkbox("Create Notion page", value=True)
    enable_gcal = st.checkbox("Add to Google Calendar", value=True)

    st.markdown("---")
    st.caption("Powered by Claude Sonnet 4.6")


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("🗓️ Weekly Planner")
st.markdown(
    "Upload your **weekly_notes.txt**, configure your API keys in the sidebar, then click **Run**."
)

col1, col2 = st.columns([2, 1])

with col1:
    notes_file = st.file_uploader(
        "Upload weekly_notes.txt",
        type=["txt", "md"],
        help="A text or markdown file with your goals, reminders, and personal appointments",
    )

with col2:
    accounts_file = st.file_uploader(
        "Upload accounts.json (optional)",
        type=["json"],
        help="JSON file with Instagram handles to scrape",
    )

# Show a preview of the notes
if notes_file:
    with st.expander("Preview notes file", expanded=False):
        st.text(notes_file.read().decode("utf-8"))
        notes_file.seek(0)

st.markdown("---")

run_button = st.button("▶️  Run Weekly Planner", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------
if "plan" not in st.session_state:
    st.session_state.plan = None
if "notion_url" not in st.session_state:
    st.session_state.notion_url = None
if "gcal_events" not in st.session_state:
    st.session_state.gcal_events = []
if "errors" not in st.session_state:
    st.session_state.errors = []

# ---------------------------------------------------------------------------
# Run pipeline
# ---------------------------------------------------------------------------
if run_button:
    if not anthropic_key:
        st.error("Please enter your Anthropic API key in the sidebar.")
        st.stop()

    os.environ["ANTHROPIC_API_KEY"] = anthropic_key

    st.session_state.errors = []
    progress = st.progress(0, text="Starting...")
    status = st.empty()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Save uploaded files to temp dir
        notes_path = Path(tmpdir) / "weekly_notes.txt"
        if notes_file:
            notes_path.write_bytes(notes_file.read())
        else:
            # Use default if it exists
            default = Path("weekly_notes.txt")
            if default.exists():
                notes_path.write_text(default.read_text())
            else:
                notes_path.write_text("# Weekly Notes\n\n## Goals\n\n## Reminders\n")

        accounts_path = "accounts.json"
        if accounts_file:
            tmp_accounts = Path(tmpdir) / "accounts.json"
            tmp_accounts.write_bytes(accounts_file.read())
            accounts_path = str(tmp_accounts)

        # ── Step 1: Parse notes ──────────────────────────────────────────
        status.info("📝 Parsing weekly notes...")
        progress.progress(10, text="Parsing notes...")
        from src.notes_parser import run as parse_notes
        try:
            notes_data = parse_notes(str(notes_path))
        except Exception as e:
            notes_data = {"goals": [], "reminders": [], "all_items": []}
            st.session_state.errors.append(f"Notes parse error: {e}")

        # ── Step 2: Canvas ───────────────────────────────────────────────
        status.info("📚 Fetching Canvas assignments...")
        progress.progress(25, text="Fetching Canvas assignments...")
        # Allow sidebar fields to override env vars for this session
        if canvas_mcp_url:
            os.environ["CANVAS_MCP_URL"] = canvas_mcp_url
        if canvas_base_url:
            os.environ["CANVAS_BASE_URL"] = canvas_base_url
        from src.canvas_integration import run as fetch_canvas
        try:
            canvas_events = fetch_canvas(
                canvas_token=canvas_token or None,
                canvas_base_url=canvas_base_url or None,
            )
        except Exception as e:
            canvas_events = []
            st.session_state.errors.append(f"Canvas error: {e}")

        # ── Step 3: Instagram ────────────────────────────────────────────
        status.info("📸 Scraping Instagram posts...")
        progress.progress(45, text="Scraping Instagram...")
        from src.instagram_scraper import run as scrape_instagram
        try:
            instagram_events = scrape_instagram(
                accounts_file=accounts_path,
                ig_username=ig_username or None,
                ig_password=ig_password or None,
            )
        except Exception as e:
            instagram_events = []
            st.session_state.errors.append(f"Instagram error: {e}")

        # ── Step 4: Orchestrate ──────────────────────────────────────────
        status.info("🤖 Claude is building your weekly plan...")
        progress.progress(65, text="Claude orchestrating plan...")
        from src.orchestrator import run as orchestrate
        try:
            plan = orchestrate(instagram_events, canvas_events, notes_data)
            st.session_state.plan = plan
        except Exception as e:
            st.session_state.errors.append(f"Orchestration error: {e}")
            st.error(f"Failed to generate plan: {e}")
            st.stop()

        # ── Step 5: Notion ───────────────────────────────────────────────
        if enable_notion and notion_token and notion_page_id:
            status.info("📓 Creating Notion page...")
            progress.progress(80, text="Creating Notion page...")
            from src.notion_output import run as create_notion
            try:
                notion_url = create_notion(
                    plan,
                    notion_token=notion_token,
                    parent_page_id=notion_page_id,
                )
                st.session_state.notion_url = notion_url
            except Exception as e:
                st.session_state.errors.append(f"Notion error: {e}")
        elif enable_notion:
            st.session_state.errors.append(
                "Notion skipped: missing API key or parent page ID"
            )

        # ── Step 6: Google Calendar ──────────────────────────────────────
        if enable_gcal:
            status.info("📅 Adding events to Google Calendar...")
            progress.progress(92, text="Adding to Google Calendar...")
            from src.gcal_output import run as add_gcal
            try:
                gcal_events = add_gcal(plan, timezone=user_timezone or None)
                st.session_state.gcal_events = gcal_events
            except Exception as e:
                st.session_state.errors.append(f"Google Calendar error: {e}")

        progress.progress(100, text="Done!")
        status.success("✅ Weekly plan ready!")

# ---------------------------------------------------------------------------
# Display results
# ---------------------------------------------------------------------------
if st.session_state.plan:
    plan = st.session_state.plan

    # Output links
    out_col1, out_col2 = st.columns(2)
    with out_col1:
        if st.session_state.notion_url:
            st.success(f"📓 [Open Notion Page]({st.session_state.notion_url})")
    with out_col2:
        if st.session_state.gcal_events:
            st.success(f"📅 {len(st.session_state.gcal_events)} events added to Google Calendar")

    # Errors
    if st.session_state.errors:
        with st.expander("⚠️ Warnings / Errors", expanded=False):
            for err in st.session_state.errors:
                st.warning(err)

    # Tabs
    tab_schedule, tab_tasks, tab_events, tab_summary, tab_raw = st.tabs(
        ["📅 Schedule", "✅ Tasks", "🎉 Events", "📋 Summary", "🔍 Raw JSON"]
    )

    # ── Schedule tab ────────────────────────────────────────────────────
    with tab_schedule:
        st.subheader("This Week's Schedule")
        schedule = plan.get("schedule", [])
        if not schedule:
            st.info("No scheduled items found.")
        else:
            for item in schedule:
                priority = item.get("priority", 3)
                colors = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢"}
                emoji = colors.get(priority, "⚪")

                with st.container():
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        title = item.get("title", "Untitled")
                        link = item.get("link")
                        if link:
                            st.markdown(f"### {emoji} [{title}]({link})")
                        else:
                            st.markdown(f"### {emoji} {title}")

                        meta_parts = []
                        if item.get("date"):
                            time_part = f" at {item['time']}" if item.get("time") else ""
                            meta_parts.append(f"📆 {item['date']}{time_part}")
                        if item.get("location"):
                            meta_parts.append(f"📍 {item['location']}")
                        if item.get("source"):
                            meta_parts.append(f"🏷️ {item['source']}")
                        if meta_parts:
                            st.caption("  ·  ".join(meta_parts))
                        if item.get("description"):
                            st.markdown(item["description"])

                    with col_b:
                        label = item.get("priority_label", "medium")
                        st.markdown(f"**Priority:** `{label}`")
                        st.markdown(f"**Type:** `{item.get('type', 'event')}`")

                st.markdown("---")

    # ── Tasks tab ───────────────────────────────────────────────────────
    with tab_tasks:
        st.subheader("Tasks & To-Dos")
        tasks = plan.get("tasks", [])
        if not tasks:
            st.info("No tasks found.")
        else:
            # Group by category
            categories: dict[str, list] = {}
            for task in tasks:
                cat = task.get("category", "other")
                categories.setdefault(cat, []).append(task)

            cat_emojis = {
                "academic": "📚",
                "personal": "👤",
                "reminder": "🔔",
                "goal": "🎯",
                "other": "📌",
            }

            for cat, cat_tasks in categories.items():
                emoji = cat_emojis.get(cat, "📌")
                st.markdown(f"#### {emoji} {cat.capitalize()}")
                for task in cat_tasks:
                    priority = task.get("priority", 3)
                    p_colors = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢"}
                    p_emoji = p_colors.get(priority, "⚪")

                    due = task.get("due_date", "")
                    due_str = f" — due {due}" if due else ""
                    notes = task.get("notes", "")

                    st.markdown(f"- {p_emoji} **{task.get('title', 'Untitled')}**{due_str}")
                    if notes:
                        st.caption(f"  ↳ {notes}")
                st.markdown("")

    # ── Events tab ──────────────────────────────────────────────────────
    with tab_events:
        st.subheader("Campus & Social Events")
        events = plan.get("events", [])
        if not events:
            st.info("No events found.")
        else:
            for event in events:
                with st.container():
                    title = event.get("title", "Untitled")
                    link = event.get("link")
                    if link:
                        st.markdown(f"### 🎪 [{title}]({link})")
                    else:
                        st.markdown(f"### 🎪 {title}")

                    meta = []
                    if event.get("date"):
                        meta.append(f"📆 {event['date']}")
                    if event.get("location"):
                        meta.append(f"📍 {event['location']}")
                    if event.get("source"):
                        meta.append(f"🏷️ {event['source']}")
                    if meta:
                        st.caption("  ·  ".join(meta))
                    if event.get("description"):
                        st.write(event["description"])
                    st.markdown("---")

    # ── Summary tab ─────────────────────────────────────────────────────
    with tab_summary:
        st.subheader("Weekly Summary")
        summary = plan.get("summary", "")
        if summary:
            st.markdown(summary)
        else:
            st.info("No summary generated.")

        st.markdown("---")
        st.subheader("Stats")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Scheduled Items", len(plan.get("schedule", [])))
        m2.metric("Tasks", len(plan.get("tasks", [])))
        m3.metric("Events", len(plan.get("events", [])))
        if st.session_state.gcal_events:
            m4.metric("Added to GCal", len(st.session_state.gcal_events))

    # ── Raw JSON tab ─────────────────────────────────────────────────────
    with tab_raw:
        st.subheader("Raw Plan JSON")
        st.json(plan)
        st.download_button(
            "⬇️ Download plan.json",
            data=json.dumps(plan, indent=2, default=str),
            file_name="weekly_plan.json",
            mime="application/json",
        )
