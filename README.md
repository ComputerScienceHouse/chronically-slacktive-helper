# Slack Agent → Open WebUI Bridge

A Python bridge that connects Slack DMs/threads to an Open WebUI instance.
Users register their Open WebUI API key via `/enroll`, then chat with AI
models through Slack. Single Flask app, HTTP webhook mode (no sockets).

## Architecture

```
Slack user ──DM/thread──► Single Flask app (Bolt HTTP mode)
                                 │
                                 ├─ /slack/events  → event webhook
                                 ├─ /slack/enroll  → slash command
                                 │
                                 ├─ message handler
                                 │    1. setStatus("processing")
                                 │    2. look up user API key (Postgres)
                                 │    3. create/lookup OWUI chat
                                 │    4. trigger completion
                                 │    5. post reply to Slack
                                 │    6. setStatus("active")
                                 │
                                 └─ assistant_thread_started → welcome message
```

One webhook URL handles everything.

## Requirements

- Python 3.10+
- PostgreSQL 14+
- Running Open WebUI instance
- Slack workspace (Developer Program sandbox works)

## Quick Start

### 1. Create a Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App**
2. **Do not enable Socket Mode** (we use HTTP webhook mode)
3. Under **Bot Token Scopes**, add:
   - `chat:write`
   - `chat:write.public`
   - `im:read`
   - `mpim:read`
   - `assistant:write`
4. Under **Event Subscriptions**, enable it, set **Request URL** to:
   ```
   https://<your-domain>/slack/events
   ```
   Subscribe to bot events:
   - `message.im`
   - `assistant_thread_started`
5. Install the app to your workspace → copy the **Bot Token** (`xoxb-...`)
6. Under **Slash Commands**, create one:
   - Command: `/enroll`
   - Request URL: `https://<your-domain>/slack/events` (same URL!)
   - Short Description: `Register your Open WebUI API key`
   - Usage Hint: `<api_key>`

Bolt routes both events and slash commands through the same webhook endpoint.

### 2. Set up the database

```bash
createdb openwebui_slack
psql openwebui_slack -f migrations/001_initial.sql
```

Or run the app directly — SQLAlchemy creates tables automatically.

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Install and run

```bash
pip install -r requirements.txt
python run.py
```

### 5. Test

In Slack:
```
/enroll your-openwebui-api-key
```

Then DM the bot with a message — it will respond via Open WebUI.

## Project Structure

```
app/
  config.py          — Config from environment
  db.py              — SQLAlchemy engine & session
  models.py          — DB models (UserAPIKey, ThreadChatMapping)
  handlers/
    message.py       — message.im handler (core loop)
    thread.py        — assistant_thread_started welcome handler
  owui/
    client.py        — Open WebUI REST API client
    __init__.py      — exports OpenWebUIClient
migrations/
  001_initial.sql    — Initial Postgres migration
run.py               — Entry point (Bolt HTTP mode + Flask)
.env.example         — Environment template
requirements.txt     — Python dependencies
```

## Phases

| Phase | Description                    | Status  |
|-------|--------------------------------|---------|
| 0     | Prerequisites                  | ✓ Setup |
| 1     | Open WebUI client library      | ✓ Done  |
| 2     | Slack agent skeleton           | ✓ Done  |
| 3     | Wire the loop together         | ✓ Done  |
| 4     | Multi-turn follow-ups          | Next    |
| 5     | UX polish                      | Future  |
| 6     | Hardening                      | Future  |
| 7     | Test & ship                    | Future  |
