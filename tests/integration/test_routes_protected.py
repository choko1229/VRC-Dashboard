"""フェーズ2/3で追加したルーターも未認証時に/loginへリダイレクトされることの確認。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

PROTECTED_PATHS = [
    "/friends",
    "/friends/groups/manage",
    "/avatars",
    "/avatars/tags/manage",
    "/settings/vrchat",
    "/settings/notifications",
    "/settings/general",
    "/schedule",
]


@pytest.mark.parametrize("path", PROTECTED_PATHS)
async def test_protected_route_redirects_when_unauthenticated(
    client: AsyncClient, path: str
) -> None:
    response = await client.get(path, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
