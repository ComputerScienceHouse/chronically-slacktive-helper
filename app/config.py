"""Application configuration loaded from environment."""

import os


class Config:
    SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
    SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
    OPENWEBUI_BASE_URL = os.environ.get(
        "OPENWEBUI_BASE_URL", "http://localhost:8080"
    )
    DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/openwebui_slack",
    )
    OWUI_DEFAULT_MODEL = os.environ.get(
        "OWUI_DEFAULT_MODEL", "Qwen3.6-35B-A3B"
    )
    PORT = int(os.environ.get("PORT", "8081"))
    SLACK_SLASH_COMMAND_PATH = os.environ.get(
        "SLACK_SLASH_COMMAND_PATH", "/slack/enroll"
    )
