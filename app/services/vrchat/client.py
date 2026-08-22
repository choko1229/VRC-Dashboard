"""VRChat非公式REST APIクライアント。

エンドポイント仕様はコミュニティ整備のドキュメント(https://vrchat.community/)に基づく。
非公式APIのため予告なく変更されうる点に注意（requirements.md参照）。
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Literal
from urllib.parse import quote

import httpx

from app.schemas.vrchat import (
    VRChatAvatar,
    VRChatCalendarEvent,
    VRChatFavorite,
    VRChatFavoriteGroup,
    VRChatInstance,
    VRChatUser,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.vrchat.cloud/api/1"
TwoFactorMethod = Literal["totp", "emailOtp"]


class VRChatAPIError(Exception):
    """VRChat APIとの通信で予期しないエラーが発生した。"""


class VRChatAuthError(Exception):
    """認証情報が誤っている、またはセッションが無効。"""


class TwoFactorRequired(Exception):
    """ログインに2段階認証コードの入力が必要。"""

    def __init__(self, methods: list[str]) -> None:
        self.methods = methods
        super().__init__(f"2段階認証が必要です: {methods}")


class VRChatClient:
    """1回のログインセッションに対応するVRChat APIクライアント。

    auth_cookie/two_factor_cookieは呼び出し側（ログインルート）が
    ログイン成功後にFernet暗号化してDBへ保存する。
    """

    def __init__(
        self,
        *,
        user_agent: str,
        auth_cookie: str | None = None,
        two_factor_cookie: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._user_agent = user_agent
        cookies = httpx.Cookies()
        if auth_cookie:
            cookies.set("auth", auth_cookie, domain="api.vrchat.cloud")
        if two_factor_cookie:
            cookies.set("twoFactorAuth", two_factor_cookie, domain="api.vrchat.cloud")

        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={"User-Agent": user_agent},
            cookies=cookies,
            timeout=timeout,
        )
        self._world_name_cache: dict[str, str] = {}

    async def __aenter__(self) -> VRChatClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def auth_cookie(self) -> str | None:
        return self._client.cookies.get("auth", domain="api.vrchat.cloud")

    @property
    def two_factor_cookie(self) -> str | None:
        return self._client.cookies.get("twoFactorAuth", domain="api.vrchat.cloud")

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("VRChat APIへの接続に失敗しました: %s %s (%s)", method, path, exc)
            raise VRChatAPIError(f"VRChat APIへの接続に失敗しました: {path}") from exc

        if response.status_code == 401:
            raise VRChatAuthError("VRChatの認証情報が無効です")
        if response.status_code >= 400:
            logger.warning(
                "VRChat APIがエラーを返しました: %s %s -> %s", method, path, response.status_code
            )
            raise VRChatAPIError(f"VRChat APIエラー: {path} ({response.status_code})")
        return response

    async def login(self, username: str, password: str) -> VRChatUser:
        """ユーザー名/パスワードでログインする。

        2段階認証が必要な場合はTwoFactorRequiredを送出する
        （呼び出し側はverify_two_factor()を呼ぶこと）。
        """
        credentials = f"{quote(username, safe='')}:{quote(password, safe='')}"
        basic_auth = base64.b64encode(credentials.encode("utf-8")).decode("ascii")

        response = await self._request(
            "GET", "/auth/user", headers={"Authorization": f"Basic {basic_auth}"}
        )
        data = response.json()

        requires_2fa = data.get("requiresTwoFactorAuth")
        if requires_2fa:
            raise TwoFactorRequired(methods=list(requires_2fa))

        return VRChatUser.model_validate(data)

    async def verify_two_factor(self, method: TwoFactorMethod, code: str) -> None:
        """2段階認証コードを検証し、twoFactorAuth Cookieを確定させる。"""
        path_method = "totp" if method == "totp" else "emailotp"
        await self._request(
            "POST", f"/auth/twofactorauth/{path_method}/verify", json={"code": code}
        )

    async def get_current_user(self) -> VRChatUser:
        response = await self._request("GET", "/auth/user")
        return VRChatUser.model_validate(response.json())

    async def get_user(self, vrchat_user_id: str) -> VRChatUser:
        """指定ユーザーのフルプロフィール（bio/アカウント作成日/会員ランク等を含む）を取得する。

        フレンド一覧(/auth/user/friends)の簡易オブジェクトには含まれない項目を
        補完するため、フレンド詳細モーダル表示時に個別取得する用途を想定。
        """
        response = await self._request("GET", f"/users/{vrchat_user_id}")
        return VRChatUser.model_validate(response.json())

    async def get_friends(self, *, offline: bool = False) -> list[VRChatUser]:
        """フレンド一覧を取得する（ページングして全件回収）。"""
        friends: list[VRChatUser] = []
        offset = 0
        page_size = 100
        while True:
            response = await self._request(
                "GET",
                "/auth/user/friends",
                params={"offline": str(offline).lower(), "n": page_size, "offset": offset},
            )
            page = response.json()
            friends.extend(VRChatUser.model_validate(item) for item in page)
            if len(page) < page_size:
                break
            offset += page_size
        return friends

    async def get_favorite_friend_groups(self) -> list[VRChatFavoriteGroup]:
        response = await self._request(
            "GET", "/favorite/groups", params={"type": "friend", "n": 100}
        )
        return [VRChatFavoriteGroup.model_validate(item) for item in response.json()]

    async def get_favorite_friends(self) -> list[VRChatFavorite]:
        """フレンドのお気に入り（グループ所属）一覧をページングして全件取得する。"""
        favorites: list[VRChatFavorite] = []
        offset = 0
        page_size = 100
        while True:
            response = await self._request(
                "GET",
                "/favorites",
                params={"type": "friend", "n": page_size, "offset": offset},
            )
            page = response.json()
            favorites.extend(VRChatFavorite.model_validate(item) for item in page)
            if len(page) < page_size:
                break
            offset += page_size
        return favorites

    async def get_own_avatars(self) -> list[VRChatAvatar]:
        """自分がアップロード済みのアバター一覧をページングして全件取得する。"""
        avatars: list[VRChatAvatar] = []
        offset = 0
        page_size = 100
        while True:
            response = await self._request(
                "GET",
                "/avatars",
                params={
                    "user": "me",
                    "releaseStatus": "all",
                    "n": page_size,
                    "offset": offset,
                },
            )
            page = response.json()
            avatars.extend(VRChatAvatar.model_validate(item) for item in page)
            if len(page) < page_size:
                break
            offset += page_size
        return avatars

    async def get_group_calendar_events(self, vrchat_group_id: str) -> list[VRChatCalendarEvent]:
        """指定したVRChatグループのカレンダーイベント一覧をページングして全件取得する。

        エンドポイント: GET /calendar/{groupId}（vrchat.community ドキュメント準拠）。
        """
        events: list[VRChatCalendarEvent] = []
        offset = 0
        page_size = 60
        while True:
            response = await self._request(
                "GET",
                f"/calendar/{vrchat_group_id}",
                params={"n": page_size, "offset": offset},
            )
            page = response.json()
            events.extend(VRChatCalendarEvent.model_validate(item) for item in page)
            if len(page) < page_size:
                break
            offset += page_size
        return events

    async def get_world_name(self, world_id: str) -> str | None:
        """ワールド名を取得する（同一インスタンス内はメモリキャッシュする）。"""
        if world_id in self._world_name_cache:
            return self._world_name_cache[world_id]

        try:
            response = await self._request("GET", f"/worlds/{world_id}")
        except VRChatAPIError:
            return None

        name = response.json().get("name")
        if isinstance(name, str):
            self._world_name_cache[world_id] = name
        return name if isinstance(name, str) else None

    async def get_instance(self, location: str) -> VRChatInstance | None:
        """インスタンスの現在人数等を取得する（サイドバーの「同じインスタンス」表示用）。

        エンドポイント: GET /instances/{location}。非公開インスタンス等で取得できない
        場合はNoneを返す（呼び出し側は人数表示を省略する）。
        """
        try:
            response = await self._request("GET", f"/instances/{quote(location, safe='')}")
        except VRChatAPIError:
            return None
        return VRChatInstance.model_validate(response.json())
