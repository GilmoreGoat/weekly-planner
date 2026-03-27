# Weekly Planner Automation System

A Streamlit-based weekly planner that aggregates data from Instagram, Canvas LMS, and your personal notes — then uses Claude AI to create a prioritized schedule. Outputs to Notion and Google Calendar.

Works with **any Canvas school** (UCSD, UCLA, UC Berkeley, NYU, etc.) and any timezone.

## Architecture

```
accounts.json ──► instagram_scraper.py ──┐
                                          ├──► orchestrator.py ──► Notion
weekly_notes.txt ──► notes_parser.py ────┤    (Claude Sonnet)    Google Calendar
                                          │
Canvas MCP / API ──► canvas_integration ──┘
        ▲
   ucsd-canvas-server.onrender.com/sse
```

## Prerequisites

- Python 3.9+ (3.10+ recommended)
- An [Anthropic API key](https://console.anthropic.com/)
- (Optional) UCSD Canvas API token
- (Optional) Notion integration token
- (Optional) Google Cloud project with Calendar API enabled

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <your-repo>
cd weekly-planner
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `IG_USERNAME` / `IG_PASSWORD` | Instagram credentials (optional, for higher rate limits) |
| `CANVAS_API_TOKEN` | Canvas API token (Account → Settings → Approved Integrations) |
| `CANVAS_BASE_URL` | Your school's Canvas domain (e.g. `https://canvas.yourschool.edu`) |
| `CANVAS_MCP_URL` | Optional Canvas MCP SSE server base URL (omit to use REST API directly) |
| `NOTION_API_KEY` | Notion integration token |
| `NOTION_PARENT_PAGE_ID` | ID of the Notion page to create weekly plans under |
| `GOOGLE_CREDENTIALS_FILE` | Path to Google OAuth2 credentials JSON |
| `GOOGLE_TOKEN_FILE` | Where to cache the Google OAuth token (default: `token.json`) |
| `GOOGLE_CALENDAR_ID` | Calendar to add events to (default: `primary`) |
| `TIMEZONE` | IANA timezone for Google Calendar (e.g. `America/New_York`, `Europe/London`) |

### 3. Canvas API Token

1. Log in to your school's Canvas (e.g. `canvas.yourschool.edu`)
2. Go to **Account → Settings → Approved Integrations**
3. Click **+ New Access Token**, give it a name, click **Generate Token**
4. Copy the token to `CANVAS_API_TOKEN` in your `.env`
5. Set `CANVAS_BASE_URL` to your school's Canvas domain (e.g. `https://canvas.yourschool.edu`)

### 4. Notion Integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **+ New integration**, name it "Weekly Planner", select your workspace
3. Copy the **Internal Integration Token** to `NOTION_API_KEY`
4. Open the Notion page where you want weekly plans to appear
5. Click **⋯ → Add connections → Weekly Planner**
6. Copy the page ID from the URL: `notion.so/Your-Page-<PAGE_ID>` → `NOTION_PARENT_PAGE_ID`

### 5. Google Calendar API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable the **Google Calendar API**
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client IDs**
5. Application type: **Desktop app**
6. Download the JSON file and save it as `credentials.json` in the project root
7. Set `GOOGLE_CREDENTIALS_FILE=credentials.json` in `.env`
8. On first run, a browser window will open asking you to authorize access

### 6. Configure Instagram accounts

Edit `accounts.json` with the handles you want to follow:

```json
{
  "accounts": ["somehandle", "another_account"],
  "lookback_days": 7
}
```

Leave `accounts` as an empty array `[]` to skip Instagram scraping.

### 7. Write your weekly notes

Edit `weekly_notes.txt` (or upload it in the dashboard):

```
# Weekly Notes — Week of 2026-03-23

## Goals
- Finish research paper draft
- Study for midterms

## Reminders
- Submit financial aid form by March 30

## Personal Items
- Coffee with Alex on Tuesday at 10am at Price Center
```

---

## Running the Dashboard

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`.

1. Enter your API keys in the sidebar (or they'll be pre-filled from `.env`)
2. Upload `weekly_notes.txt` (or use the default file)
3. Optionally upload a custom `accounts.json`
4. Click **▶️ Run Weekly Planner**
5. View results in the **Schedule / Tasks / Events / Summary** tabs
6. Download the raw JSON plan

---

## Running from the CLI (no Streamlit)

```python
from dotenv import load_dotenv
load_dotenv()

from src.instagram_scraper import run as scrape_ig
from src.canvas_integration import run as fetch_canvas
from src.notes_parser import run as parse_notes
from src.orchestrator import run as orchestrate
from src.notion_output import run as create_notion
from src.gcal_output import run as add_gcal

instagram_events = scrape_ig()
canvas_events    = fetch_canvas()
notes_data       = parse_notes("weekly_notes.txt")
plan             = orchestrate(instagram_events, canvas_events, notes_data)
notion_url       = create_notion(plan)
gcal_events      = add_gcal(plan)

print("Notion page:", notion_url)
print("GCal events added:", len(gcal_events))
```

---

## File Structure

```
weekly-planner/
├── app.py                    # Streamlit dashboard
├── requirements.txt
├── README.md
├── .env.example              # Environment variable template
├── accounts.json             # Instagram handles to scrape
├── weekly_notes.txt          # Your weekly notes template
├── credentials.json          # Google OAuth2 credentials (you create this)
├── token.json                # Google OAuth2 token (auto-generated)
└── src/
    ├── __init__.py
    ├── instagram_scraper.py  # Instaloader + Claude event extraction
    ├── canvas_integration.py # Canvas MCP + REST API fallback
    ├── notes_parser.py       # weekly_notes.txt parser
    ├── orchestrator.py       # Claude AI merge + prioritization
    ├── notion_output.py      # Notion page creation
    └── gcal_output.py        # Google Calendar event creation
```

---

## Notes & Limitations

- **Instagram scraping**: Instagram may rate-limit or block anonymous scraping. Providing credentials reduces this risk. Private accounts cannot be scraped.
- **Canvas MCP**: The MCP server URL is optional and configurable via `CANVAS_MCP_URL`. The integration automatically falls back to the Canvas REST API if the MCP server is unreachable or not configured. Set `CANVAS_BASE_URL` to your school's Canvas domain for the REST fallback to work.
- **Google Calendar OAuth**: The first run will open a browser for authorization. Subsequent runs use the cached `token.json`.
- **Notion blocks**: Notion has a 100-block-per-request limit; the code handles this automatically by batching.
