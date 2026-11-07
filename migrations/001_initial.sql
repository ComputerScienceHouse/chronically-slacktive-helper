-- Initial migration: create tables for user API keys and thread↔chat mappings

CREATE TABLE IF NOT EXISTS user_api_keys (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slack_user_id TEXT        NOT NULL UNIQUE,
    slack_user_name TEXT,
    api_key       TEXT        NOT NULL,
    created_at    TIMESTAMP   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS thread_chat_mappings (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slack_thread_ts TEXT       NOT NULL UNIQUE,
    slack_channel_id TEXT       NOT NULL,
    chat_id        TEXT         NOT NULL,
    user_api_key_id UUID        NOT NULL REFERENCES user_api_keys(id),
    created_at     TIMESTAMP    NOT NULL DEFAULT now(),
    updated_at     TIMESTAMP    NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_thread_chat_mappings_thread_ts
    ON thread_chat_mappings(slack_thread_ts);

CREATE INDEX IF NOT EXISTS idx_thread_chat_mappings_user_key
    ON thread_chat_mappings(user_api_key_id);
