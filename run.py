"""Entry point — single Flask app with Bolt in HTTP mode.

One server, one port. Handles:
  - Slack events webhook: POST /slack/events
  - Slack slash command:   POST /slack/enroll
  - Event verification:     GET  /slack/events (challenge)

Usage:
    export SLACK_BOT_TOKEN=xoxb-...
    export SLACK_SIGNING_SECRET=...
    export OPENWEBUI_BASE_URL=http://localhost:8080
    export DATABASE_URL=postgresql://...
    export PORT=8081

    python run.py

Register a single webhook URL with Slack:
    https://<your-domain>/slack/events
    (This URL handles both events and slash commands — Bolt routes automatically.)
"""

import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------
# Logging — DEBUG level for troubleshooting
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
from app.config import Config

# ------------------------------------------------------------------
# Database
# ------------------------------------------------------------------
from app.db import init_db
init_db(database_url=Config.DATABASE_URL)

# ------------------------------------------------------------------
# Bolt app — registers event + command listeners.
# ------------------------------------------------------------------
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")

logger.info("=== Slack App Starting ===")
logger.info("  Bot token present: %s", bool(BOT_TOKEN))
logger.info("  Signing secret present: %s", bool(SIGNING_SECRET))
logger.info("  OPENWEBUI_BASE_URL: %s", Config.OPENWEBUI_BASE_URL)
logger.info("  DATABASE_URL: %s", Config.DATABASE_URL[:30] + "...")

bolt_app = App(
    token=BOT_TOKEN,
    signing_secret=SIGNING_SECRET,
)

# ------------------------------------------------------------------
# Route all Slack webhook traffic to Bolt
# ------------------------------------------------------------------
from flask import Flask, request

flask_app = Flask(__name__)
flask_app.config.from_object(Config)

slack_handler = SlackRequestHandler(bolt_app)


@flask_app.route("/slack/events", methods=["GET", "POST"])
def slack_events():
    """Route all Slack webhook traffic through Bolt."""
    logger.debug("=== Incoming Slack request ===")
    logger.debug("  method:   %s", request.method)
    logger.debug("  path:     %s", request.path)
    logger.debug("  headers:  %s", dict(request.headers))
    logger.debug("  data len: %d bytes", len(request.data))
    logger.debug("  raw body: %s", request.data.decode("utf-8", errors="replace")[:500])

    try:
        result = slack_handler.handle(request)
        logger.debug("  response status: %s", result.status_code)
        return result
    except Exception as exc:
        logger.exception("Error handling Slack request:")
        from flask import make_response
        return make_response(f"Error: {exc}", 500)


# ------------------------------------------------------------------
# Event + command listeners (all sync — no async/await)
# ------------------------------------------------------------------

from app.owui.client import OpenWebUIClient
from app.handlers.message import MessageHandler
from app.handlers.thread import ThreadHandler

owui_client = OpenWebUIClient(
    base_url=Config.OPENWEBUI_BASE_URL,
    api_key="",  # overridden per user in MessageHandler
    model=Config.OWUI_DEFAULT_MODEL,
)

msg_handler = MessageHandler(client=bolt_app.client, owui=owui_client)
thread_handler = ThreadHandler(client=bolt_app.client)


@bolt_app.event("app_mention")
def handle_message(body: dict):
    """Handle incoming bot messages (text)."""
    logger.debug("=== message event received ===")
    logger.debug("  body keys: %s", list(body.keys()))
    event = body.get("event")
    if not event:
        logger.warning("  No 'event' in body!")
        return

    logger.debug("  event type: %s", event.get("type"))
    subtype = event.get("subtype", "")
    logger.debug("  subtype: %s", subtype)
    logger.debug("  text: %r", event.get("text", "").strip())
    logger.debug("  user: %s", event.get("user"))
    logger.debug("  channel: %s", event.get("channel"))
    logger.debug("  thread_ts: %s", event.get("thread_ts"))

    if subtype == "bot_message":
        logger.debug("  skipping bot_message subtype")
        return
    if not event.get("text", "").strip():
        logger.debug("  skipping empty text")
        return

    msg_handler.on_message(event, {})
    logger.debug("  message handler finished")


@bolt_app.command("/enroll")
def handle_enroll(ack, body, say):
    """Register a Slack user's Open WebUI API key."""
    logger.debug("=== /enroll command received ===")
    logger.debug("  body keys: %s", list(body.keys()))
    ack()  # Acknowledge immediately
    logger.debug("  acknowledged")

    text = (body.get("text") or "").strip()
    user_id = body.get("user_id")
    user_name = body.get("user_name", "unknown")

    logger.debug("  text: %r (len=%d)", text, len(text))
    logger.debug("  user_id: %s", user_id)
    logger.debug("  user_name: %s", user_name)

    if not text or len(text) < 10:
        say(":warning: Usage: `/enroll <your-openwebui-api-key>`")
        logger.warning("  enroll failed: invalid or missing API key")
        return

    if not user_id:
        say(":warning: Could not identify your user ID.")
        logger.warning("  enroll failed: no user_id in body")
        return

    from app.db import get_session
    from app.models import UserAPIKey

    session = get_session()
    try:
        user = (
            session.query(UserAPIKey)
            .filter(UserAPIKey.slack_user_id == user_id)
            .first()
        )

        if user:
            user.api_key = text
            user.slack_user_name = user_name
            action = "updated"
        else:
            user = UserAPIKey(
                slack_user_id=user_id,
                slack_user_name=user_name,
                api_key=text,
            )
            session.add(user)
            action = "created"

        session.commit()

        say(
            f"API key {action} for {user_name}. "
            "You can now DM the bot to start chatting."
        )
        logger.info("Enrolled user %s (%s) — %s", user_id, action, user_name)

    except Exception as exc:
        session.rollback()
        logger.exception("Enroll failed for %s: %s", user_id, exc)
        say(f":warning: Database error: {exc}")
    finally:
        session.close()


# ------------------------------------------------------------------
# Run
# ------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8081"))

    logger.info("Starting Slack ↔ Open WebUI bridge")
    logger.info("  Flask: http://0.0.0.0:%d", port)
    logger.info("  Webhook URL to register with Slack:")
    logger.info("    https://<your-domain>/slack/events")

    flask_app.run(host="0.0.0.0", port=port)
