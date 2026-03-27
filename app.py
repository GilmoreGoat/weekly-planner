"""
Weekly Planner — Streamlit Dashboard
Supports OpenAI, Anthropic, Google Gemini, and Ollama (local).
"""

import json
import logging
import os
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

st.set_page_config(
    page_title="Weekly Planner",
    page_icon="🗓️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🗓️ Weekly Planner")
    st.markdown("---")

    # ── LLM Provider ────────────────────────────────────────────────────
    st.subheader("🤖 AI Provider")

    provider = st.selectbox(
        "Provider",
        options=["openai", "anthropic", "gemini", "ollama"],
        format_func=lambda p: {
            "openai":    "OpenAI  (GPT-4o, GPT-4-turbo…)",
            "anthropic": "Anthropic  (Claude Sonnet, Haiku…)",
            "gemini":    "Google Gemini  (1.5 Pro, Flash…)",
            "ollama":    "Ollama  (local — no API key needed)",
        }[p],
        index=["openai", "anthropic", "gemini", "ollama"].index(
            os.environ.get("LLM_PROVIDER", "openai")
        ),
        help="Choose which AI service generates your weekly plan.",
    )

    DEFAULT_MODELS = {
        "openai":    ["gpt-4o", "gpt-4-turbo", "gpt-4o-mini", "gpt-3.5-turbo"],
        "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
        "gemini":    ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
        "ollama":    ["llama3", "llama3:70b", "mistral", "phi3", "gemma2"],
    }
    ENV_KEYS = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "ollama": "",
    }

    llm_model = st.selectbox(
        "Model",
        options=DEFAULT_MODELS[provider],
        index=0,
        help="Model to use. You can also type a custom model name below.",
    )
    custom_model = st.text_input(
        "Custom model name (optional)",
        placeholder="e.g. gpt-4-turbo-preview",
        help="Overrides the selection above if filled in.",
    )
    final_model = custom_model.strip() if custom_model.strip() else llm_model

    if provider == "ollama":
        llm_api_key = ""
        ollama_url = st.text_input(
            "Ollama base URL",
            value=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            help="URL of your local Ollama server.",
        )
        st.caption("No API key needed for Ollama.")
    else:
        env_key_name = ENV_KEYS[provider]
        llm_api_key = st.text_input(
            f"{provider.capitalize()} API Key",
            value=os.environ.get(env_key_name, ""),
            type="password",
            help=f"Get your key from the {provider.capitalize()} console.",
        )
        ollama_url = "http://localhost:11434"

        KEY_LINKS = {
            "openai":    "https://platform.openai.com/api-keys",
            "anthropic": "https://console.anthropic.com/",
            "gemini":    "https://aistudio.google.com/app/apikey",
        }
        st.caption(f"[Get a {provider.capitalize()} API key →]({KEY_LINKS[provider]})")

    st.markdown("---")

    # ── Other integrations ───────────────────────────────────────────────
    st.subheader("⚙️ Integrations")

    canvas_token = st.text_input(
        "Canvas API Token",
        value=os.environ.get("CANVAS_API_TOKEN", ""),
        type="password",
        help="Account → Settings → Approved Integrations → New Access Token",
    )
    canvas_base_url = st.text_input(
        "Canvas Base URL",
        value=os.environ.get("CANVAS_BASE_URL", ""),
        placeholder="https://canvas.ucsd.edu",
    )
    canvas_mcp_url = st.text_input(
        "Canvas MCP URL (optional)",
        value=os.environ.get("CANVAS_MCP_URL", ""),
        placeholder="https://ucsd-canvas-server.onrender.com",
    )

    notion_token = st.text_input(
        "Notion API Key",
        value=os.environ.get("NOTION_API_KEY", ""),
        type="password",
    )
    notion_page_id = st.text_input(
        "Notion Parent Page ID",
        value=os.environ.get("NOTION_PARENT_PAGE_ID", ""),
    )

    ig_username = st.text_input(
        "Instagram Username (optional)",
        value=os.environ.get("IG_USERNAME", ""),
    )
    ig_password = st.text_input(
        "Instagram Password (optional)",
        value=os.environ.get("IG_PASSWORD", ""),
        type="password",
    )

    user_timezone = st.text_input(
        "Timezone",
        value=os.environ.get("TIMEZONE", "America/Los_Angeles"),
        help="IANA timezone e.g. America/New_York, Europe/London",
    )

    st.markdown("---")
    st.subheader("📤 Outputs")
    enable_notion = st.checkbox("Create Notion page", value=bool(notion_token and notion_page_id))
    enable_gcal   = st.checkbox("Add to Google Calendar", value=True)

    st.markdown("---")
    st.caption(f"Provider: **{provider}** / {final_model}")


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("🗓️ Weekly Planner")
st.markdown(
    "Upload your **weekly_notes.txt**, choose an AI provider in the sidebar, then click **Run**."
)

col1, col2 = st.columns([2, 1])
with col1:
    notes_file = st.file_uploader("Upload weekly_notes.txt", type=["txt", "md"])
with col2:
    accounts_file = st.file_uploader("Upload accounts.json (optional)", type=["json"])

if notes_file:
    with st.expander("Preview notes file", expanded=False):
        st.text(notes_file.read().decode("utf-8"))
        notes_file.seek(0)

st.markdown("---")
run_button = st.button("▶️  Run Weekly Planner", type="primary", use_container_width=True)

# Session state
for key in ("plan", "notion_url", "gcal_events", "errors"):
    if key not in st.session_state:
        st.session_state[key] = None if key in ("plan", "notion_url") else []

# ---------------------------------------------------------------------------
# Run pipeline
# ---------------------------------------------------------------------------
if run_button:
    if provider != "ollama" and not llm_api_key:
        st.error(f"Please enter your {provider.capitalize()} API key in the sidebar.")
        st.stop()

    # Build the LLM client
    try:
        from src.llm_client import LLMClient
        llm_client = LLMClient.from_sidebar(
            provider=provider,
            api_key=llm_api_key,
            model=final_model,
            ollama_url=ollama_url,
        )
    except Exception as e:
        st.error(f"Failed to initialise {provider} client: {e}")
        st.stop()

    st.session_state.errors = []
    progress = st.progress(0, text="Starting…")
    status = st.empty()

    with tempfile.TemporaryDirectory() as tmpdir:
        notes_path = Path(tmpdir) / "weekly_notes.txt"
        if notes_file:
            notes_path.write_bytes(notes_file.read())
        else:
            default = Path("weekly_notes.txt")
            notes_path.write_text(default.read_text() if default.exists() else "# Weekly Notes\n\n## Goals\n\n## Reminders\n")

        accounts_path = "accounts.json"
        if accounts_file:
            tmp_accounts = Path(tmpdir) / "accounts.json"
            tmp_accounts.write_bytes(accounts_file.read())
            accounts_path = str(tmp_accounts)

        # Step 1 — Notes
        status.info("📝 Parsing weekly notes…")
        progress.progress(10, text="Parsing notes…")
        from src.notes_parser import run as parse_notes
        try:
            notes_data = parse_notes(str(notes_path))
        except Exception as e:
            notes_data = {"goals": [], "reminders": [], "all_items": []}
            st.session_state.errors.append(f"Notes parse error: {e}")

        # Step 2 — Canvas
        status.info("📚 Fetching Canvas assignments…")
        progress.progress(25, text="Fetching Canvas…")
        if canvas_mcp_url:
            os.environ["CANVAS_MCP_URL"] = canvas_mcp_url
        if canvas_base_url:
            os.environ["CANVAS_BASE_URL"] = canvas_base_url
        from src.canvas_integration import run as fetch_canvas
        try:
            canvas_events = fetch_canvas(canvas_token=canvas_token or None, canvas_base_url=canvas_base_url or None)
        except Exception as e:
            canvas_events = []
            st.session_state.errors.append(f"Canvas error: {e}")

        # Step 3 — Instagram
        status.info("📸 Scraping Instagram posts…")
        progress.progress(45, text="Scraping Instagram…")
        from src.instagram_scraper import run as scrape_instagram
        try:
            instagram_events = scrape_instagram(
                accounts_file=accounts_path,
                ig_username=ig_username or None,
                ig_password=ig_password or None,
                llm_client=llm_client,
            )
        except Exception as e:
            instagram_events = []
            st.session_state.errors.append(f"Instagram error: {e}")

        # Step 4 — Orchestrate
        status.info(f"🤖 {provider.capitalize()} is building your weekly plan…")
        progress.progress(65, text="Generating plan…")
        from src.orchestrator import run as orchestrate
        try:
            plan = orchestrate(instagram_events, canvas_events, notes_data, llm_client=llm_client)
            st.session_state.plan = plan
        except Exception as e:
            st.session_state.errors.append(f"Orchestration error: {e}")
            st.error(f"Failed to generate plan: {e}")
            st.stop()

        # Step 5 — Notion
        if enable_notion and notion_token and notion_page_id:
            status.info("📓 Creating Notion page…")
            progress.progress(80, text="Creating Notion page…")
            from src.notion_output import run as create_notion
            try:
                st.session_state.notion_url = create_notion(plan, notion_token=notion_token, parent_page_id=notion_page_id)
            except Exception as e:
                st.session_state.errors.append(f"Notion error: {e}")
        elif enable_notion:
            st.session_state.errors.append("Notion skipped: missing API key or parent page ID")

        # Step 6 — Google Calendar
        if enable_gcal:
            status.info("📅 Adding events to Google Calendar…")
            progress.progress(92, text="Adding to Google Calendar…")
            from src.gcal_output import run as add_gcal
            try:
                st.session_state.gcal_events = add_gcal(plan, timezone=user_timezone or None)
            except Exception as e:
                st.session_state.errors.append(f"Google Calendar error: {e}")

        progress.progress(100, text="Done!")
        status.success("✅ Weekly plan ready!")

# ---------------------------------------------------------------------------
# Display results
# ---------------------------------------------------------------------------
if st.session_state.plan:
    plan = st.session_state.plan

    out_col1, out_col2 = st.columns(2)
    with out_col1:
        if st.session_state.notion_url:
            st.success(f"📓 [Open Notion Page]({st.session_state.notion_url})")
    with out_col2:
        if st.session_state.gcal_events:
            st.success(f"📅 {len(st.session_state.gcal_events)} events added to Google Calendar")

    if st.session_state.errors:
        with st.expander("⚠️ Warnings / Errors", expanded=False):
            for err in st.session_state.errors:
                st.warning(err)

    tab_schedule, tab_tasks, tab_events, tab_summary, tab_raw = st.tabs(
        ["📅 Schedule", "✅ Tasks", "🎉 Events", "📋 Summary", "🔍 Raw JSON"]
    )

    with tab_schedule:
        st.subheader("This Week's Schedule")
        schedule = plan.get("schedule", [])
        if not schedule:
            st.info("No scheduled items found.")
        else:
            for item in schedule:
                priority = item.get("priority", 3)
                emoji = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢"}.get(priority, "⚪")
                with st.container():
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        title = item.get("title", "Untitled")
                        link = item.get("link")
                        st.markdown(f"### {emoji} [{title}]({link})" if link else f"### {emoji} {title}")
                        meta = []
                        if item.get("date"):
                            meta.append(f"📆 {item['date']}" + (f" at {item['time']}" if item.get("time") else ""))
                        if item.get("location"):
                            meta.append(f"📍 {item['location']}")
                        if item.get("source"):
                            meta.append(f"🏷️ {item['source']}")
                        if meta:
                            st.caption("  ·  ".join(meta))
                        if item.get("description"):
                            st.markdown(item["description"])
                    with col_b:
                        st.markdown(f"**Priority:** `{item.get('priority_label','medium')}`")
                        st.markdown(f"**Type:** `{item.get('type','event')}`")
                st.markdown("---")

    with tab_tasks:
        st.subheader("Tasks & To-Dos")
        tasks = plan.get("tasks", [])
        if not tasks:
            st.info("No tasks found.")
        else:
            categories: dict = {}
            for task in tasks:
                categories.setdefault(task.get("category", "other"), []).append(task)
            cat_emojis = {"academic": "📚", "personal": "👤", "reminder": "🔔", "goal": "🎯", "other": "📌"}
            for cat, cat_tasks in categories.items():
                st.markdown(f"#### {cat_emojis.get(cat,'📌')} {cat.capitalize()}")
                for task in cat_tasks:
                    p_emoji = {1:"🔴",2:"🟠",3:"🟡",4:"🟢"}.get(task.get("priority",3),"⚪")
                    due = task.get("due_date","")
                    st.markdown(f"- {p_emoji} **{task.get('title','Untitled')}**" + (f" — due {due}" if due else ""))
                    if task.get("notes"):
                        st.caption(f"  ↳ {task['notes']}")

    with tab_events:
        st.subheader("Campus & Social Events")
        events = plan.get("events", [])
        if not events:
            st.info("No events found.")
        else:
            for event in events:
                title = event.get("title", "Untitled")
                link = event.get("link")
                st.markdown(f"### 🎪 [{title}]({link})" if link else f"### 🎪 {title}")
                meta = []
                if event.get("date"):   meta.append(f"📆 {event['date']}")
                if event.get("location"): meta.append(f"📍 {event['location']}")
                if event.get("source"):  meta.append(f"🏷️ {event['source']}")
                if meta: st.caption("  ·  ".join(meta))
                if event.get("description"): st.write(event["description"])
                st.markdown("---")

    with tab_summary:
        st.subheader("Weekly Summary")
        summary = plan.get("summary", "")
        st.markdown(summary) if summary else st.info("No summary generated.")
        st.markdown("---")
        st.subheader("Stats")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Scheduled Items", len(plan.get("schedule", [])))
        m2.metric("Tasks", len(plan.get("tasks", [])))
        m3.metric("Events", len(plan.get("events", [])))
        if st.session_state.gcal_events:
            m4.metric("Added to GCal", len(st.session_state.gcal_events))

    with tab_raw:
        st.subheader("Raw Plan JSON")
        st.json(plan)
        st.download_button(
            "⬇️ Download plan.json",
            data=json.dumps(plan, indent=2, default=str),
            file_name="weekly_plan.json",
            mime="application/json",
        )
