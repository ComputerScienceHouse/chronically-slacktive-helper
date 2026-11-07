"""Handler for assistant_thread_started events.

Shows a welcome message with suggested prompts when a user starts
a new DM thread with the bot.
"""

import logging

from app.owui.client import OpenWebUIClient

logger = logging.getLogger(__name__)


class ThreadHandler:
    def __init__(self, client):
        self.client = client

    def on_assistant_thread_started(self, event: dict, context: dict) -> None:
        """Send a welcome message when a new thread is created."""
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")

        logger.info("New thread started: %s", thread_ts)

        welcome_blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "👋 Welcome to Open WebUI via Slack",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "I can chat with Open WebUI for you! "
                        "Just send a message.\n\n"
                        "Don't forget to register your API key first:\n"
                        "```\n/enroll <your-openwebui-api-key>\n```\n\n"
                        "Suggested prompts:"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "• What's the latest news about AI?\n"
                        "• Help me brainstorm ideas for a project\n"
                        "• Explain quantum computing simply"
                    ),
                },
            },
        ]

        self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            blocks=welcome_blocks,
        )
