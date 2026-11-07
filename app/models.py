"""Database models for the Slack ↔ Open WebUI bridge."""

import uuid

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db import Base


class UserAPIKey(Base):
    """Maps a Slack user to their Open WebUI API key."""

    __tablename__ = "user_api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slack_user_id = Column(String, unique=True, nullable=False, index=True)
    slack_user_name = Column(String, nullable=True)
    api_key = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

