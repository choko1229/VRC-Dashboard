"""Web Push購読用の唯一の素のJSON API（ブラウザのPushManagerが直接呼び出す）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_cipher, get_current_user
from app.core.security import SecretCipher
from app.db.session import get_db
from app.models.dashboard_user import DashboardUser
from app.schemas.webpush import PushSubscriptionIn, UnsubscribeIn
from app.services import app_config_service, webpush_service

router = APIRouter(prefix="/webpush", dependencies=[Depends(get_current_user)])


@router.get("/vapid-public-key")
async def vapid_public_key(
    db: AsyncSession = Depends(get_db), cipher: SecretCipher = Depends(get_cipher)
) -> dict[str, str]:
    _private_key, public_key = await app_config_service.get_or_create_vapid_keys(db, cipher)
    return {"publicKey": public_key}


@router.post("/subscribe")
async def subscribe(
    request: Request,
    body: PushSubscriptionIn,
    db: AsyncSession = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
) -> dict[str, bool]:
    await webpush_service.upsert_subscription(
        db,
        dashboard_user_id=user.id,
        endpoint=body.endpoint,
        p256dh_key=body.keys.p256dh,
        auth_key=body.keys.auth,
        user_agent=request.headers.get("user-agent"),
    )
    return {"success": True}


@router.delete("/subscribe")
async def unsubscribe(body: UnsubscribeIn, db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    await webpush_service.delete_subscription(db, body.endpoint)
    return {"success": True}
