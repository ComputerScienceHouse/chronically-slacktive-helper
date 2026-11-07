"""Async client for the Open WebUI REST API.

Implements the Backend-Controlled API Flow:
  1. POST /api/v1/chats/new           — create chat with user message + assistant placeholder
  2. POST /api/chat/completions       — trigger completion (stream or poll)
  3. POST /api/v1/chats/{chatId}      — append turn for multi-turn
  4. GET  /api/v1/chats/{chatId}      — fetch final chat
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

# Slack truncation limit
MAX_SLACK_MESSAGE = 3500


class OpenWebUIClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        logger.debug(
            "OpenWebUIClient created (base=%s, key=%s, model=%s)",
            self.base_url,
            self.api_key[:10] + "...",
            self.model,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_message_tree(self, prompt: str) -> dict:
        """Build the message + history structure with UUIDs.

        OWUI requires:
          - Caller-generated UUIDs for each message id
          - `childrenIds` on every message (camelCase)
          - `currentId` in history (camelCase)
          - An assistant placeholder alongside the user message
        """
        user_msg_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        timestamp = int(datetime.now(timezone.utc).timestamp())

        user_msg_obj = {
            "id": user_msg_id,
            "role": "user",
            "content": prompt,
            "parentId": None,
            "childrenIds": [assistant_id],
            "timestamp": timestamp,
            "models": [self.model],
        }
        
        assistant_msg_obj = {
            "id": assistant_id,
            "role": "assistant",
            "content": "",
            "parentId": user_msg_id,
            "model": self.model,
            "modelName": self.model,
            "modelIdx": 0,
            "childrenIds": [],
            "done": False,
            "timestamp": timestamp+1
        }

        return {
            "messages": [
                user_msg_obj,
                assistant_msg_obj,
            ],
            "history": {
                "messages": {
                    user_msg_id: user_msg_obj,
                    assistant_id: assistant_msg_obj,
                },
                "currentId": assistant_id,
            },
        }

    def _build_complete_payload(
        self,
        chat_id: str,
        assistant_message_id: str,
        user_message: dict,
    ) -> dict:
        """Build the payload for POST /api/chat/completions.

        Generates a fresh session_id for every call.
        """
        messages = [{"role": user_message["role"], "content": user_message["content"]}]

        payload = {
            "chat_id": chat_id,
            "id": assistant_message_id,
            "user_message": user_message,
            "messages": messages,
            "model": self.model,
            "stream": True,
            "background_tasks": {
                "title_generation": True,
                "tags_generation": False,
                "follow_up_generation": False,
            },
            "features": {
                "code_interpreter": True,
                "web_search": True,
                "image_generation": False,
                "memory": True,
            },
            "tool_ids":[
                "server:mcp:wiki"
            ],
            "variables": {
                "{{USER_NAME}}": "",
                "{{USER_LANGUAGE}}": "en-US",
                "{{CURRENT_DATETIME}}": datetime.now(timezone.utc).isoformat(),
                "{{CURRENT_TIMEZONE}}": "America/New_York",
            },
            "session_id": str(uuid.uuid4()),  # fresh per call
        }
        return payload

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def create_chat(
        self, prompt: str
    ) -> Tuple[str, dict, str]:
        """Create a new chat and return ``(chat_id, user_message, assistant_msg_id)``.

        POST /api/v1/chats/new

        The API expects the payload wrapped in a top-level "chat" key.
        """
        logger.debug("create_chat: prompt=%r", prompt[:100])
        tree = self._build_message_tree(prompt)

        payload = {"chat": tree}

        url = f"{self.base_url}/api/v1/chats/new"
        logger.debug("create_chat: POST %s", url)
        headers = self._get_headers()

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                logger.debug("create_chat: response status=%d", resp.status)
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "create_chat: error %d — %s",
                        resp.status,
                        body[:500],
                    )
                    resp.raise_for_status()
                data = await resp.json()
                chat_id = data["id"]
                assistant_msg_id = tree["messages"][1]["id"]
                user_message = tree["messages"][0]
                logger.debug(
                    "create_chat: OK (chat_id=%s, assistant_msg_id=%s)",
                    chat_id,
                    assistant_msg_id,
                )
                return chat_id, user_message, assistant_msg_id


    async def complete(
        self,
        chat_id: str,
        assistant_message_id: str,
        messages: list[dict],
        user_message: dict,
    ) -> str:
        """Trigger completion and return the assistant's final text.

        POST /api/chat/completions  (trigger)
        GET  /api/v1/chats/{chatId} (poll for result)

        The API requires all fields: chat_id, id, user_message, messages,
        model, background_tasks, features, variables, session_id.
        """
        payload = self._build_complete_payload(
            chat_id, assistant_message_id, user_message
        )

        url = f"{self.base_url}/api/chat/completions"
        logger.debug(
            "complete: POST %s, chat_id=%s, session_id=%s",
            url,
            chat_id,
            payload["session_id"],
        )

        headers = self._get_headers()

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                logger.debug("complete: trigger response status=%d", resp.status)
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "complete: trigger error %d — %s",
                        resp.status,
                        body[:500],
                    )
                    resp.raise_for_status()

            # Poll for the result
            result = await self._poll_until_complete(
                session, chat_id, assistant_message_id, timeout=300.0, poll_interval=5.0
            )
        logger.debug("complete: OK (%d chars)", len(result))
        return result

    async def _poll_until_complete(
        self,
        session: aiohttp.ClientSession,
        chat_id: str,
        assistant_message_id: str,
        timeout: float = 300.0,
        poll_interval: float = 5.0,
    ) -> str:
        """Poll GET /api/v1/chats/{chatId} until the assistant has content."""
        start = asyncio.get_running_loop().time()
        while True:
            url = f"{self.base_url}/api/v1/chats/{chat_id}"
            async with session.get(url, headers=self._get_headers()) as resp:
                logger.debug("_poll_until_complete: status=%d", resp.status)
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "_poll_until_complete: error %d — %s",
                        resp.status,
                        body[:500],
                    )
                    resp.raise_for_status()
                data = await resp.json()

            # Find the latest assistant message with content
            if data.get("chat", {}).get("history", {}).get("messages", {}).get(assistant_message_id, {}).get("done", False):
                return data.get("chat", {}).get("history", {}).get("messages", {}).get(assistant_message_id, {}).get("content", "Content Not Found")

            if asyncio.get_running_loop().time() - start > timeout:
                raise TimeoutError(
                    f"Chat {chat_id} did not complete within {timeout}s"
                )
            logger.debug("_poll_until_complete: still waiting...")
            await asyncio.sleep(poll_interval)

    async def append_turn(
        self,
        chat_id: str,
        user_prompt: str,
    ) -> Tuple[dict, str]:
        """Append a user→assistant pair to an existing chat.

        POST /api/v1/chats/{chatId}

        The API expects the payload wrapped in a top-level "chat" key.

        Returns ``(user_message, assistant_message_id)`` — the IDs come from
        the tree we build here, matching how create_chat works.
        """
        logger.debug(
            "append_turn: chat_id=%s, prompt=%r",
            chat_id,
            user_prompt[:100],
        )
        tree = self._build_message_tree(user_prompt)

        payload = {
            "id": chat_id,
            "chat": tree,
        }

        url = f"{self.base_url}/api/v1/chats/{chat_id}"
        logger.debug("append_turn: POST %s", url)
        headers = self._get_headers()

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                logger.debug("append_turn: response status=%d", resp.status)
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "append_turn: error %d — %s",
                        resp.status,
                        body[:500],
                    )
                    resp.raise_for_status()
                user_message = tree["messages"][0]
                assistant_msg_id = tree["messages"][1]["id"]
                logger.debug(
                    "append_turn: OK (user_msg_id=%s, assistant_msg_id=%s)",
                    user_message["id"],
                    assistant_msg_id,
                )
                return user_message, assistant_msg_id

    async def get_final_chat(self, chat_id: str) -> dict:
        """Fetch a completed chat.

        GET /api/v1/chats/{chatId}
        """
        url = f"{self.base_url}/api/v1/chats/{chat_id}"
        logger.debug("get_final_chat: GET %s", url)
        headers = self._get_headers()

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                logger.debug("get_final_chat: response status=%d", resp.status)
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "get_final_chat: error %d — %s",
                        resp.status,
                        body[:500],
                    )
                    resp.raise_for_status()
                data = await resp.json()
                return data

    async def wait_for_completion(
        self,
        chat_id: str,
        timeout: float = 120.0,
        poll_interval: float = 2.0,
    ) -> str:
        """Poll GET /api/v1/chats/{chatId} until the assistant has content.

        Fallback for when streaming is not suitable.
        """
        start = asyncio.get_running_loop().time()
        while True:
            chat_data = await self.get_final_chat(chat_id)
            messages = chat_data.get("messages", [])
            # Find the latest assistant message with content
            for msg in reversed(messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    return msg["content"]

            if asyncio.get_running_loop().time() - start > timeout:
                raise TimeoutError(
                    f"Chat {chat_id} did not complete within {timeout}s"
                )
            await asyncio.sleep(poll_interval)

    @staticmethod
    def truncate(text: str, max_len: int = MAX_SLACK_MESSAGE) -> str:
        """Truncate text to *max_len* chars, preserving word boundaries."""
        if len(text) <= max_len:
            return text
        return text[:max_len].rsplit(" ", 1)[0] + "…"
