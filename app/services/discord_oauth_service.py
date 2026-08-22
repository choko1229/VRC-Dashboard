"""ダッシュボードログイン用のDiscord OAuth2クライアント。

既存のDiscord BOTとは別に、このダッシュボード専用に新規作成したDiscordアプリの
Client ID/Secretを使う想定（.envの DISCORD_OAUTH_CLIENT_ID/SECRET）。
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

from app.schemas.discord import DiscordTokenResponse, DiscordUser

logger = logging.getLogger(__name__)

_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
_TOKEN_URL = "https://discord.com/api/oauth2/token"
_USER_ME_URL = "https://discord.com/api/users/@me"


class DiscordOAuthError(Exception):
    """Discord OAuth2フロー中のエラー（トークン交換失敗、ユーザー情報取得失敗等）。"""


def build_authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify",
        "state": state,
        "prompt": "none",
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_token(
    *, client_id: str, client_secret: str, redirect_uri: str, code: str
) -> DiscordTokenResponse:
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                _TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Discordトークン交換に失敗しました: %s", exc)
            raise DiscordOAuthError("Discordとのトークン交換に失敗しました") from exc

    return DiscordTokenResponse.model_validate(response.json())


async def fetch_current_discord_user(*, access_token: str) -> DiscordUser:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                _USER_ME_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Discordユーザー情報の取得に失敗しました: %s", exc)
            raise DiscordOAuthError("Discordユーザー情報の取得に失敗しました") from exc

    return DiscordUser.model_validate(response.json())
