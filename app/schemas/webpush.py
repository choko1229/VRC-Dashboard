"""ブラウザのPushSubscription.toJSON()に対応するスキーマ。"""

from __future__ import annotations

from pydantic import BaseModel


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


class UnsubscribeIn(BaseModel):
    endpoint: str
