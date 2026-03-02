#!/usr/bin/env python3
"""
Prolific Study Status Notifier → Slack
Polls all Prolific studies and sends a Slack notification when a study goes ACTIVE (live) or ends (COMPLETED / AWAITING REVIEW).
Run via cron every 2-3 minutes: */2 * * * * /usr/bin/python3 /path/to/prolific_slack_notifier.py
"""

import json
import os
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ── CONFIG ──────────────────────────────────────────────────────────────────
PROLIFIC_API_TOKEN = os.environ.get("PROLIFIC_API_TOKEN", "YOUR_PROLIFIC_TOKEN_HERE")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "YOUR_SLACK_WEBHOOK_URL_HERE")

# Where to store seen study IDs (persists between runs)
STATE_FILE = Path(__file__).parent / ".prolific_seen_studies.json"

# Notify when study goes live (ACTIVE) or when it's done (AWAITING REVIEW = essentially finished)
# API returns "AWAITING REVIEW" with a space, not underscore
NOTIFY_STATUSES = {"ACTIVE", "AWAITING_REVIEW", "AWAITING REVIEW"}

# Prolific API base
PROLIFIC_API_BASE = "https://api.prolific.com/api/v1"

# User-Agent for Prolific API (Cloudflare may block generic clients)
# Override with PROLIFIC_USER_AGENT env var to try a different one
PROLIFIC_USER_AGENT = os.environ.get(
    "PROLIFIC_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)

# Set PROLIFIC_DEBUG=1 to log request URL and headers (token redacted)
PROLIFIC_DEBUG = os.environ.get("PROLIFIC_DEBUG", "").strip().lower() in ("1", "true", "yes")

# ── LOGGING ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── HELPERS ─────────────────────────────────────────────────────────────────

def api_get(endpoint: str) -> dict:
    """Make an authenticated GET request to the Prolific API."""
    url = f"{PROLIFIC_API_BASE}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Token {PROLIFIC_API_TOKEN}",
        "Accept": "application/json",
        "User-Agent": PROLIFIC_USER_AGENT,
    }
    if PROLIFIC_DEBUG:
        log.info("Prolific API request: GET %s", url)
        log.info("User-Agent: %s", PROLIFIC_USER_AGENT)
        log.info("Authorization: Token %s...", (PROLIFIC_API_TOKEN[:8] + "..." if len(PROLIFIC_API_TOKEN) > 8 else "(redacted)"))
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def send_slack_message(text: str, blocks: Optional[list] = None) -> None:
    """Send a message to Slack via incoming webhook."""
    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    data = json.dumps(payload).encode()
    req = Request(SLACK_WEBHOOK_URL, data=data, headers={
        "Content-Type": "application/json",
    })
    with urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            log.error(f"Slack returned status {resp.status}")


def load_state() -> dict:
    """Load previously seen study statuses from disk."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            log.warning("State file corrupted, starting fresh")
    return {"seen": {}}  # {study_id: last_known_status}


def save_state(state: dict) -> None:
    """Persist state to disk."""
    STATE_FILE.write_text(json.dumps(state, indent=2))


def format_reward(reward_cents: int, currency: str = "USD") -> str:
    """Convert reward from cents to dollars/pounds."""
    symbol = "£" if currency == "GBP" else "$"
    return f"{symbol}{reward_cents / 100:.2f}"


def build_slack_blocks(study: dict, status: str) -> tuple[str, list]:
    """Build a rich Slack notification for a study that just went ACTIVE or COMPLETED/AWAITING_REVIEW."""
    name = study.get("name", "Untitled Study")
    internal = study.get("internal_name", "")
    study_id = study.get("id", "unknown")
    reward = study.get("reward", 0)
    places_total = study.get("total_available_places", 0)
    places_taken = study.get("places_taken", 0)
    submissions = study.get("number_of_submissions", 0)
    published_at = study.get("published_at", "")
    study_url = f"https://app.prolific.com/researcher/workspaces/studies/{study_id}"

    if status == "ACTIVE":
        emoji, label = "🟢", "ACTIVE"
        fallback = f"🟢 Study ACTIVE: {name} — {places_taken}/{places_total} places taken — {format_reward(reward)}/participant"
    else:
        # status may be "AWAITING REVIEW" (API) or "AWAITING_REVIEW"
        emoji, label = "🔴", "ENDED" if status == "COMPLETED" else "AWAITING REVIEW"
        fallback = f"🔴 Study {label}: {name} — {submissions} submissions — {places_taken}/{places_total} places"

    header_text = f"{emoji} {label}: {name}" if len(name) <= 120 else f"{emoji} {label}: {name[:117]}..."

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Study name:*\n{name}"},
                {"type": "mrkdwn", "text": f"*Status:*\n`{status}`"},
                {"type": "mrkdwn", "text": f"*Reward:*\n{format_reward(reward)}/participant"},
                {"type": "mrkdwn", "text": f"*Places:*\n{places_taken}/{places_total}"},
                {"type": "mrkdwn", "text": f"*Submissions:*\n{submissions}"},
                {"type": "mrkdwn", "text": f"*Published:*\n{published_at or 'N/A'}"},
            ]
        },
    ]

    if internal:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Internal name: _{internal}_"}]
        })

    blocks.append({
        "type": "actions",
        "elements": [{
            "type": "button",
            "text": {"type": "plain_text", "text": "View Study on Prolific"},
            "url": study_url,
            "style": "primary",
        }]
    })

    blocks.append({"type": "divider"})

    return fallback, blocks


# ── MAIN ────────────────────────────────────────────────────────────────────

def main():
    log.info("Checking Prolific studies...")

    # Validate config
    if "YOUR_" in PROLIFIC_API_TOKEN or "YOUR_" in SLACK_WEBHOOK_URL:
        log.error("Please set PROLIFIC_API_TOKEN and SLACK_WEBHOOK_URL (env vars or edit the script)")
        sys.exit(1)

    # Load previous state
    state = load_state()
    seen = state.get("seen", {})

    # Fetch ALL studies from Prolific
    try:
        data = api_get("/studies/")
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
        except Exception:
            pass
        log.error("Prolific API error: %s %s", e.code, e.reason)
        if body and "Cloudflare" in body and "1010" in body:
            log.error("Cloudflare blocked the request (Error 1010). Try:")
            log.error("  1. Run with PROLIFIC_DEBUG=1 to see the request being sent")
            log.error("  2. Try a different network (e.g. phone hotspot) in case your IP is restricted")
            log.error("  3. Try: export PROLIFIC_USER_AGENT=\"curl/8.0.0\" then run again")
        elif body:
            log.error("Response: %s", body[:500] + "..." if len(body) > 500 else body)
        sys.exit(1)
    except URLError as e:
        log.error(f"Network error: {e.reason}")
        sys.exit(1)

    studies = data.get("results", [])
    log.info(f"Found {len(studies)} studies total")

    new_active_count = 0
    updated_seen = {}

    for study in studies:
        study_id = study.get("id")
        current_status = study.get("status")
        if not study_id or not current_status:
            continue

        previous_status = seen.get(study_id)
        updated_seen[study_id] = current_status

        # Check if this study just transitioned to a notify-worthy status
        if current_status in NOTIFY_STATUSES and previous_status != current_status:
            # Skip notification on first run (when we have no previous state)
            # to avoid spamming about all currently-active studies
            if previous_status is None and len(seen) > 0:
                # We have state but haven't seen this study before — it's new, notify
                pass
            elif previous_status is None and len(seen) == 0:
                # First run ever — just record state, don't spam
                log.info(f"  First run: recording {study.get('name', study_id)} as {current_status}")
                continue
            
            log.info(f"  Notify ({current_status}): {study.get('name', study_id)} (was: {previous_status or 'unseen'})")

            try:
                fallback, blocks = build_slack_blocks(study, current_status)
                send_slack_message(fallback, blocks)
                new_active_count += 1
            except Exception as e:
                log.error(f"  Failed to send Slack notification: {e}")

    # Save updated state
    state["seen"] = updated_seen
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    log.info(f"Done. {new_active_count} new notification(s) sent. State saved.")


if __name__ == "__main__":
    main()
