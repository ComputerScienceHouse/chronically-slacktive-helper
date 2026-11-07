"""Handler for message.im events (DM and thread messages).

Orchestrates the full loop (sync, no async/await):
  1. Add :gear: reaction to the user's message
  2. Look up user's API key from Postgres
  3. Look up or create Open WebUI chat for this thread
  4. Call OWUI completion
  5. Post answer back to Slack thread
  6. Remove :gear: reaction
"""

import logging

from slack_sdk.web import WebClient

from app.async_utils import run_async
from app.db import get_session
from app.models import UserAPIKey
from app.owui.client import OpenWebUIClient

logger = logging.getLogger(__name__)

class MessageHandler:
    def __init__(
        self,
        client: WebClient,
        owui: OpenWebUIClient,
    ):
        self.client = client
        self.owui = owui
        logger.debug(
            "MessageHandler initialized (owui base_url=%s, model=%s)",
            self.owui.base_url,
            self.owui.model,
        )

    def on_message(self, event: dict, context: dict) -> None:
        """Top-level handler invoked for every message.im event."""
        thread_ts = event.get("thread_ts") or event.get("ts")
        channel = event.get("channel")
        user_id = event.get("user")
        text = event.get("text", "").strip()

        if not text:
            logger.debug("Skipping message: empty text")
            return

        logger.info(
            "Processing message: channel=%s thread=%s user=%s text=%r",
            channel,
            thread_ts,
            user_id,
            text,
        )

        # Capture the timestamp of the message we're replying to
        msg_ts = event.get("ts")

        # Add :gear: reaction to the user's message
        try:
            self.client.reactions_add(name="gear", channel=channel, timestamp=msg_ts)
            logger.debug("  Reaction added: :gear:")
        except Exception:
            logger.warning("  Failed to add :gear: reaction")

        # Run the heavy lifting
        self._handle_turn(channel, thread_ts, user_id, text, msg_ts)
        logger.info("Message processing complete")

    def _handle_turn(
        self,
        channel: str,
        thread_ts: str,
        user_id: str,
        text: str,
        msg_ts: str,
    ) -> None:
        """Lookup key, manage chat, call OWUI, post reply."""
        session = get_session()
        try:
            # 1. Look up user's API key
            logger.debug("  Step 1: looking up API key for user %s", user_id)
            user_record = (
                session.query(UserAPIKey)
                .filter(UserAPIKey.slack_user_id == user_id)
                .first()
            )

            if not user_record:
                logger.warning(
                    "  Step 1 FAILED: no API key registered for %s. "
                    "User needs to run /enroll first.",
                    user_id,
                )
                self._post_reply(
                    channel, thread_ts,
                    ":warning: You haven't registered an API key yet. "
                    "Please run `/enroll <your-openwebui-api-key>` first.",
                )
                self._remove_gear(channel, msg_ts)
                return

            logger.debug(
                "  Step 1 OK: found API key for %s (name=%s)",
                user_id,
                user_record.slack_user_name,
            )

            # 2. Re-initialize OWUI client with user's key + model
            owui = OpenWebUIClient(
                base_url=self.owui.base_url,
                api_key=user_record.api_key,
                model=self.owui.model,
            )
            logger.debug(
                "  Step 2: OWUI client ready (base_url=%s, model=%s)",
                owui.base_url,
                owui.model,
            )

            # 3. Look up or create Open WebUI chat for this thread
            logger.debug("  Step 3: looking up thread ↔ chat mapping")

            chat_id = None
            user_message = None
            assistant_message_id = None
            # 4. Create new chat — returns (chat_id, user_message, assistant_msg_id)
            logger.debug("  Step 4: creating new OWUI chat")
            chat_id, user_message, assistant_message_id = run_async(
                owui.create_chat(text)
            )
            logger.debug(
                "  Step 4 OK: created chat_id=%s, assistant_msg_id=%s",
                chat_id,
                assistant_message_id,
            )

            # 5. Trigger completion
            messages = [
                {"role": user_message["role"], "content": user_message["content"]}
            ]
            logger.debug(
                "  Step 5: triggering completion (chat_id=%s, model=%s)",
                chat_id,
                owui.model,
            )
            logger.debug(
                "  Step 5: assistant_message_id=%s", assistant_message_id
            )
            answer = run_async(
                owui.complete(
                    chat_id=chat_id,
                    assistant_message_id=assistant_message_id,
                    messages=messages,
                    user_message=user_message,
                )
            )
            logger.debug("  Step 5 OK: got answer (%d chars)", len(answer))

            # 6. Post reply
            truncated = OpenWebUIClient.truncate(answer)
            logger.debug("  Step 6: posting reply (%d chars)", len(truncated))
            self._post_reply(channel, thread_ts, truncated)
            logger.debug("  Step 6 OK: reply posted")

        except TimeoutError as exc:
            logger.error("  Step FAILED: OWUI timeout — %s", exc)
            self._post_reply(
                channel, thread_ts,
                ":warning: Open WebUI took too long to respond. Please try again."
            )
        except Exception as exc:
            logger.exception("  Step FAILED: unhandled error — %s", exc)
            self._post_reply(
                channel, thread_ts, f":warning: Error: {exc}"
            )
        finally:
            session.close()
            logger.debug("  Reaction removed: :gear:")

    def _post_reply(self, channel: str, thread_ts: str, text: str):
        """Post a message to the Slack thread."""
        try:
            self.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                markdown_text=text,
            )
            logger.debug("    chat_postMessage succeeded")
        except Exception:
            logger.exception("    chat_postMessage failed")

    def _set_status(self, channel: str, thread_ts: str, status: str):
        """Set the Slack agent session status."""
        try:
            self.client.agents.sessions.setStatus(
                channel_id=channel,
                thread_ts=thread_ts,
                status=status,
            )
            logger.debug("    setStatus(%s) succeeded", status)
        except Exception:
            logger.warning("    setStatus(%s) failed", status)
