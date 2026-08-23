"""VRChat自体の通知（招待・フレンドリクエスト・グループイベント等）の取込・一覧・アクション。

命名は既存の`app.notifications.*`（Discord/webpush向けの、このアプリ自身が送る通知の
配信システム）との混同を避けるため、`vrchat_notification_service`とする。

VRChatが公式に仕様公開しているのはPipelineの"notification"イベント（招待/招待リクエスト/
フレンドリクエスト/メッセージ/Boop/投票キック等7種類）のみ。それ以外
（notification-v2/economy-update/group-*等）は非公式のため、フィールド抽出に失敗した/
未知の種類は`notification_type`に生のtype文字列、`raw_details`に生JSONを保存し、
一覧側は汎用フォールバック表示（削除のみ）にする。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_command import AgentCommand
from app.models.vrchat_notification import VRChatNotification
from app.services.vrchat.client import VRChatAPIError, VRChatClient

logger = logging.getLogger(__name__)

_PAGE_SIZE = 50

# notification_type -> (表示ラベル, アクション種別)。
# アクション種別: "join"(位置情報がある場合エージェント経由でインスタンス参加) /
#   "accept_friend"(フレンドリクエスト承諾) / "respond_invite"(招待リクエストへ招待を送り返す) /
#   "none"(削除のみ)。未知のtypeはデフォルトで(生のtype文字列, "none")にフォールバックする。
_TYPE_META: dict[str, tuple[str, str]] = {
    "requestInvite": ("招待リクエスト", "respond_invite"),
    "invite": ("招待", "join"),
    "requestInviteResponse": ("招待リクエストへの返信", "join"),
    "inviteResponse": ("招待への返信", "none"),
    "friendRequest": ("フレンドリクエスト", "accept_friend"),
    "message": ("メッセージ", "none"),
    "boop": ("Boop", "none"),
    "voteToKick": ("投票キック", "none"),
    "friend_add": ("フレンド追加", "none"),
    "economy_update": ("エコノミーの通知", "none"),
    "instance_queue_joined": ("キューに参加", "none"),
    "instance_queue_ready": ("キューの準備が完了", "none"),
    "group_change": ("グループ変更", "none"),
}


def get_type_label(notification_type: str) -> str:
    return _TYPE_META.get(notification_type, (notification_type, "none"))[0]


def get_type_action(notification_type: str) -> str:
    return _TYPE_META.get(notification_type, (notification_type, "none"))[1]


def known_type_choices() -> list[tuple[str, str]]:
    """フィルタープルダウン用の (type, label) 一覧。"""
    return [(t, label) for t, (label, _action) in _TYPE_META.items()]


@dataclass
class _ParsedNotification:
    vrchat_notification_id: str
    pipeline_event: str
    notification_type: str
    sender_user_id: str | None = None
    sender_display_name: str | None = None
    group_name: str | None = None
    image_url: str | None = None
    message: str | None = None
    location: str | None = None
    raw_details: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _as_dict(value: object) -> dict[str, Any]:
    """detailsが文字列化されたJSONの場合とdictの場合の両方を吸収する。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except ValueError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _extract_location(details: dict[str, Any]) -> str | None:
    location = details.get("location")
    if isinstance(location, str) and location:
        return location
    world_id = details.get("worldId")
    instance_id = details.get("instanceId")
    if isinstance(world_id, str) and isinstance(instance_id, str):
        return f"{world_id}:{instance_id}"
    return None


def _parse_notification_v1(content: dict[str, Any]) -> _ParsedNotification | None:
    notification_id = content.get("id")
    notification_type = content.get("type")
    if not isinstance(notification_id, str) or not isinstance(notification_type, str):
        return None
    details = _as_dict(content.get("details"))
    created_at_raw = content.get("created_at")
    occurred_at = datetime.now(UTC)
    if isinstance(created_at_raw, str):
        try:
            occurred_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        except ValueError:
            pass

    return _ParsedNotification(
        vrchat_notification_id=notification_id,
        pipeline_event="notification",
        notification_type=notification_type,
        sender_user_id=(
            content.get("senderUserId") if isinstance(content.get("senderUserId"), str) else None
        ),
        sender_display_name=(
            content.get("senderUsername")
            if isinstance(content.get("senderUsername"), str)
            else None
        ),
        image_url=details.get("imageUrl") if isinstance(details.get("imageUrl"), str) else None,
        message=content.get("message") if isinstance(content.get("message"), str) else None,
        location=_extract_location(details),
        raw_details=json.dumps(content, default=str, ensure_ascii=False),
        occurred_at=occurred_at,
    )


def _parse_notification_v2(content: dict[str, Any]) -> _ParsedNotification | None:
    notification_id = content.get("id")
    if not isinstance(notification_id, str):
        return None
    notification_type = content.get("type") or content.get("category") or "notification-v2"

    return _ParsedNotification(
        vrchat_notification_id=notification_id,
        pipeline_event="notification-v2",
        notification_type=str(notification_type),
        sender_user_id=(
            content.get("senderUserId") if isinstance(content.get("senderUserId"), str) else None
        ),
        sender_display_name=(
            content.get("senderUsername")
            if isinstance(content.get("senderUsername"), str)
            else None
        ),
        group_name=(
            content.get("groupName") if isinstance(content.get("groupName"), str) else None
        ),
        image_url=content.get("imageUrl") if isinstance(content.get("imageUrl"), str) else None,
        message=(
            content.get("message")
            if isinstance(content.get("message"), str)
            else content.get("title") if isinstance(content.get("title"), str) else None
        ),
        raw_details=json.dumps(content, default=str, ensure_ascii=False),
    )


def _synthetic(
    *, pipeline_event: str, notification_type: str, content: dict[str, Any], **overrides: Any
) -> _ParsedNotification:
    """VRChatのNotificationオブジェクトを持たないPipelineイベント（friend-add/economy-update等）
    から、疑似的な通知行を作る。生のtype/IDを持たないため、IDはuuid4で毎回発行する
    （再配信されると重複行になり得るが、この種のイベントは頻度が低く実害は小さい）。
    """
    return _ParsedNotification(
        vrchat_notification_id=f"synthetic:{uuid.uuid4().hex}",
        pipeline_event=pipeline_event,
        notification_type=notification_type,
        raw_details=json.dumps(content, default=str, ensure_ascii=False),
        **overrides,
    )


def _parse_friend_add(content: dict[str, Any]) -> _ParsedNotification | None:
    user = content.get("user")
    user_dict = user if isinstance(user, dict) else {}
    display_name = user_dict.get("displayName") or content.get("displayName")
    return _synthetic(
        pipeline_event="friend-add",
        notification_type="friend_add",
        content=content,
        sender_user_id=content.get("userId") if isinstance(content.get("userId"), str) else None,
        sender_display_name=str(display_name) if display_name else None,
        message="フレンドになりました。",
    )


def _parse_economy_update(content: dict[str, Any]) -> _ParsedNotification | None:
    message = content.get("description") or content.get("message")
    return _synthetic(
        pipeline_event="economy-update",
        notification_type="economy_update",
        content=content,
        message=str(message) if message else None,
    )


def _parse_instance_queue_joined(content: dict[str, Any]) -> _ParsedNotification | None:
    return _synthetic(
        pipeline_event="instance-queue-joined",
        notification_type="instance_queue_joined",
        content=content,
        message="インスタンスへの参加待ちに入りました。",
        location=content.get("location") if isinstance(content.get("location"), str) else None,
    )


def _parse_instance_queue_ready(content: dict[str, Any]) -> _ParsedNotification | None:
    return _synthetic(
        pipeline_event="instance-queue-ready",
        notification_type="instance_queue_ready",
        content=content,
        message="インスタンスへの参加準備ができました。",
        location=content.get("location") if isinstance(content.get("location"), str) else None,
    )


def _parse_group_change(pipeline_event: str) -> Any:
    def _parser(content: dict[str, Any]) -> _ParsedNotification | None:
        group = content.get("group")
        group_dict = group if isinstance(group, dict) else {}
        group_name = group_dict.get("name") or content.get("groupName")
        return _synthetic(
            pipeline_event=pipeline_event,
            notification_type="group_change",
            content=content,
            group_name=str(group_name) if group_name else None,
        )

    return _parser


_PARSERS: dict[str, Any] = {
    "notification": _parse_notification_v1,
    "notification-v2": _parse_notification_v2,
    "friend-add": _parse_friend_add,
    "economy-update": _parse_economy_update,
    "instance-queue-joined": _parse_instance_queue_joined,
    "instance-queue-ready": _parse_instance_queue_ready,
    "group-joined": _parse_group_change("group-joined"),
    "group-left": _parse_group_change("group-left"),
    "group-member-updated": _parse_group_change("group-member-updated"),
    "group-role-updated": _parse_group_change("group-role-updated"),
}

# 通知そのものではなく、既存通知に対する操作の同期用イベント。
# このダッシュボードから操作した分は自前でDB更新するため、ここではVRChat公式アプリ/VRCX側で
# 操作された結果を追従させる（is_hiddenの更新のみ）。
_HIDE_SYNC_EVENTS = frozenset(
    ("see-notification", "hide-notification", "response-notification", "notification-v2-delete")
)


async def ingest(db: AsyncSession, *, pipeline_event: str, content: dict[str, Any]) -> None:
    if pipeline_event in _HIDE_SYNC_EVENTS:
        await _mark_hidden_from_sync_event(db, content)
        return

    parser = _PARSERS.get(pipeline_event)
    if parser is None:
        return
    parsed = parser(content)
    if parsed is None:
        return
    await _upsert(db, parsed)


async def _mark_hidden_from_sync_event(db: AsyncSession, content: dict[str, Any]) -> None:
    notification_id = content.get("notificationId") or content.get("id")
    if not isinstance(notification_id, str):
        return
    row = (
        await db.execute(
            select(VRChatNotification).where(
                VRChatNotification.vrchat_notification_id == notification_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return
    row.is_hidden = True
    await db.commit()


async def _upsert(db: AsyncSession, parsed: _ParsedNotification) -> None:
    existing = (
        await db.execute(
            select(VRChatNotification).where(
                VRChatNotification.vrchat_notification_id == parsed.vrchat_notification_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    db.add(
        VRChatNotification(
            vrchat_notification_id=parsed.vrchat_notification_id,
            pipeline_event=parsed.pipeline_event,
            notification_type=parsed.notification_type,
            sender_user_id=parsed.sender_user_id,
            sender_display_name=parsed.sender_display_name,
            group_name=parsed.group_name,
            image_url=parsed.image_url,
            message=parsed.message,
            location=parsed.location,
            raw_details=parsed.raw_details,
            occurred_at=parsed.occurred_at,
        )
    )
    await db.commit()


async def get_notifications(
    db: AsyncSession,
    *,
    page: int = 0,
    notification_type: str | None = None,
    q: str = "",
    sort_dir: str = "desc",
) -> tuple[list[VRChatNotification], bool]:
    """通知一覧の1ページ分を取得する。(結果, 次ページの有無) を返す。"""
    query = select(VRChatNotification).where(VRChatNotification.is_hidden.is_(False))

    if notification_type:
        query = query.where(VRChatNotification.notification_type == notification_type)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(
            (VRChatNotification.sender_display_name.ilike(term))
            | (VRChatNotification.message.ilike(term))
            | (VRChatNotification.group_name.ilike(term))
        )

    order_col = VRChatNotification.occurred_at
    query = query.order_by(order_col.asc() if sort_dir == "asc" else order_col.desc())
    query = query.offset(page * _PAGE_SIZE).limit(_PAGE_SIZE + 1)

    rows = list((await db.execute(query)).scalars().all())
    has_more = len(rows) > _PAGE_SIZE
    return rows[:_PAGE_SIZE], has_more


async def enqueue_join_command(db: AsyncSession, *, location: str) -> None:
    db.add(
        AgentCommand(
            command_type="join_instance",
            payload_json=json.dumps({"location": location}),
        )
    )
    await db.commit()


async def accept(db: AsyncSession, client: VRChatClient | None, row: VRChatNotification) -> None:
    """通知を承諾する。「参加」系アクションはVRChatとの接続が無くても実行できる
    （デスクトップエージェントへの委譲のみで完結するため）。フレンドリクエスト承諾/招待リクエストへの
    応答はVRChat REST APIが必要なため、clientが無い場合は何もしない。
    """
    action = get_type_action(row.notification_type)
    if action == "accept_friend" and client is not None:
        try:
            await client.accept_friend_request(row.vrchat_notification_id)
        except VRChatAPIError:
            logger.warning("フレンドリクエストの承諾に失敗しました: %s", row.vrchat_notification_id)
        row.is_hidden = True
    elif action == "respond_invite" and client is not None:
        try:
            await client.respond_to_invite(row.vrchat_notification_id)
        except VRChatAPIError:
            logger.warning("招待リクエストへの応答に失敗しました: %s", row.vrchat_notification_id)
        row.is_hidden = True
    elif action == "join" and row.location:
        await enqueue_join_command(db, location=row.location)
    await db.commit()


async def decline(db: AsyncSession, client: VRChatClient | None, row: VRChatNotification) -> None:
    """拒否/削除の両方に使う（承諾以外は「非表示にする」という同じ操作のため）。"""
    if client is not None:
        try:
            await client.hide_notification(row.vrchat_notification_id)
        except VRChatAPIError:
            logger.warning("通知の削除に失敗しました: %s", row.vrchat_notification_id)
    row.is_hidden = True
    await db.commit()
