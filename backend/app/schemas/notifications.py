from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class NotificationSeverity(str, Enum):
    ACTION = "action"
    ERROR = "error"
    INFO = "info"


class NotificationItem(BaseModel):
    id: str
    source: Literal["audit", "system"]
    audit_log_id: int | None = None
    event: str
    title: str
    summary: str | None = None
    severity: NotificationSeverity
    href: str | None = None
    created_at: datetime
    is_unread: bool


class NotificationsResponse(BaseModel):
    items: list[NotificationItem]
    unread_count: int
    last_read_at: datetime | None = None


class MarkNotificationsReadResponse(BaseModel):
    unread_count: int = 0
