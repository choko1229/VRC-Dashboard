"""DB管理設定(app_setting)の読み書き。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting


async def get_setting(db: AsyncSession, key: str) -> str | None:
    setting = await db.get(AppSetting, key)
    return setting.value if setting is not None else None


async def set_setting(
    db: AsyncSession, key: str, value: str | None, *, value_type: str = "string"
) -> None:
    setting = await db.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=value, value_type=value_type)
        db.add(setting)
    else:
        setting.value = value
        setting.value_type = value_type
    await db.commit()
