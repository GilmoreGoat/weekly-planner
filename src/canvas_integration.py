from __future__ import annotations

"""
Canvas integration via a Canvas MCP server (SSE transport).
The MCP server URL is configurable via CANVAS_MCP_URL env var.
Falls back to direct Canvas REST API if MCP is unavailable.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Configurable via env — default points to the UCSD community MCP server,
# but any Canvas MCP SSE endpoint works.
_MCP_BASE = os.environ.get(
    "CANVAS_MCP_URL", "https://ucsd-canvas-server.onrender.com"
).rstrip("/")
MCP_SSE_URL = f"{_MCP_BASE}/sse"
MCP_MESSAGES_URL = f"{_MCP_BASE}/messages"


# ---------------------------------------------------------------------------
# MCP SSE client helpers
# ---------------------------------------------------------------------------

def _mcp_call(tool_name: str, arguments: dict[str, Any], session_id: str, timeout: int = 30) -> Any:
    """
    Send a JSON-RPC tools/call request to the MCP server and return the result.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    url = f"{MCP_MESSAGES_URL}?sessionId={session_id}"
    resp = httpx.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")
    return data.get("result")


def _start_mcp_session(timeout: int = 20) -> str:
    """
    Connect to the SSE endpoint and read the first event which contains the session ID.
    Returns the session ID string.
    """
    with httpx.Client(timeout=timeout) as client:
        with client.stream("GET", MCP_SSE_URL, headers={"Accept": "text/event-stream"}) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    data_str = line[len("data:"):].strip()
                    # The first SSE data event contains the session endpoint URL
                    # e.g. data: /messages?sessionId=abc123
                    if "sessionId=" in data_str:
                        session_id = data_str.split("sessionId=")[-1].strip()
                        return session_id
    raise RuntimeError("Could not obtain MCP session ID from SSE endpoint")


def fetch_via_mcp(canvas_token: str) -> list[dict[str, Any]]:
    """
    Connect to the UCSD Canvas MCP server and fetch upcoming assignments.
    """
    logger.info("Connecting to Canvas MCP at %s", MCP_SSE_URL)
    session_id = _start_mcp_session()
    logger.info("MCP session established: %s", session_id)

    # Initialize the MCP session
    init_payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "weekly-planner", "version": "1.0.0"},
        },
    }
    url = f"{MCP_MESSAGES_URL}?sessionId={session_id}"
    httpx.post(url, json=init_payload, timeout=15).raise_for_status()

    # Fetch upcoming assignments using the MCP tool
    result = _mcp_call(
        "get_upcoming_assignments",
        {"api_token": canvas_token},
        session_id,
    )

    assignments = _parse_mcp_result(result)
    logger.info("Fetched %d assignments via MCP", len(assignments))
    return assignments


def _parse_mcp_result(result: Any) -> list[dict[str, Any]]:
    """Parse the MCP tool result into a list of assignment dicts."""
    if result is None:
        return []

    # MCP returns content as a list of text/resource items
    content = result.get("content", [])
    assignments = []

    for item in content:
        if item.get("type") == "text":
            text = item.get("text", "")
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    assignments.extend(data)
                elif isinstance(data, dict):
                    assignments.append(data)
            except json.JSONDecodeError:
                # Plain text — create a simple assignment item
                assignments.append({"title": text, "due_at": None, "course": "Unknown"})

    return assignments


# ---------------------------------------------------------------------------
# Direct Canvas REST API fallback
# ---------------------------------------------------------------------------

def fetch_via_rest_api(canvas_token: str, canvas_base_url: str) -> list[dict[str, Any]]:
    """
    Fall back to Canvas REST API directly to fetch upcoming assignments.
    """
    logger.info("Falling back to Canvas REST API at %s", canvas_base_url)
    headers = {"Authorization": f"Bearer {canvas_token}"}
    assignments: list[dict[str, Any]] = []

    with httpx.Client(headers=headers, timeout=30) as client:
        # Get active courses
        courses_resp = client.get(
            f"{canvas_base_url}/api/v1/courses",
            params={"enrollment_state": "active", "per_page": 50},
        )
        courses_resp.raise_for_status()
        courses = courses_resp.json()

        now = datetime.now(timezone.utc).isoformat()

        for course in courses:
            if not isinstance(course, dict):
                continue
            course_id = course.get("id")
            course_name = course.get("name", "Unknown Course")

            try:
                assign_resp = client.get(
                    f"{canvas_base_url}/api/v1/courses/{course_id}/assignments",
                    params={
                        "bucket": "upcoming",
                        "per_page": 50,
                        "order_by": "due_at",
                    },
                )
                assign_resp.raise_for_status()
                for a in assign_resp.json():
                    if isinstance(a, dict):
                        assignments.append(
                            {
                                "title": a.get("name", "Untitled"),
                                "due_at": a.get("due_at"),
                                "course": course_name,
                                "course_id": course_id,
                                "assignment_id": a.get("id"),
                                "html_url": a.get("html_url"),
                                "points_possible": a.get("points_possible"),
                                "submission_types": a.get("submission_types", []),
                            }
                        )
            except Exception as e:
                logger.warning("Failed to fetch assignments for course %s: %s", course_name, e)

    logger.info("Fetched %d assignments via REST API", len(assignments))
    return assignments


def normalize_assignments(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize Canvas assignments into the shared event schema."""
    events = []
    for a in raw:
        events.append(
            {
                "type": "canvas_assignment",
                "title": a.get("title") or a.get("name") or "Untitled Assignment",
                "date": a.get("due_at"),
                "location": None,
                "link": a.get("html_url"),
                "source": "Canvas",
                "description": f"Assignment for {a.get('course', 'Unknown Course')}"
                + (f" — {a.get('points_possible')} pts" if a.get("points_possible") else ""),
                "course": a.get("course"),
            }
        )
    return events


def run(
    canvas_token: str | None = None,
    canvas_base_url: str | None = None,
) -> list[dict[str, Any]]:
    """Main entry point: fetch Canvas assignments and return normalized events."""
    token = canvas_token or os.environ.get("CANVAS_API_TOKEN", "")
    base_url = canvas_base_url or os.environ.get("CANVAS_BASE_URL", "")
    if not base_url:
        logger.warning("CANVAS_BASE_URL not set — Canvas REST API fallback unavailable")
        base_url = "https://canvas.instructure.com"  # generic Instructure default

    if not token:
        logger.warning("No Canvas API token provided — skipping Canvas integration")
        return []

    raw: list[dict[str, Any]] = []

    # Try MCP first, fall back to REST
    try:
        raw = fetch_via_mcp(token)
    except Exception as e:
        logger.warning("MCP fetch failed (%s), falling back to REST API", e)
        try:
            raw = fetch_via_rest_api(token, base_url)
        except Exception as e2:
            logger.error("Canvas REST API also failed: %s", e2)
            return []

    return normalize_assignments(raw)
