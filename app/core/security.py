"""暗号化・セッショントークン関連のユーティリティ。

- VRChatのauthtoken等はFernet(AES-128-CBC+HMAC)でアプリ層暗号化してからDBへ保存する。
- ダッシュボードのセッションは「生トークンはCookieのみ・DBにはハッシュ値のみ」を保存する
  伝統的なサーバーサイドセッション方式（JWT等の自己署名トークンは使わない）。
  これによりセッションの即時失効（ログアウト・不正利用時の強制ログアウト）が可能になる。
- Fernetの鍵自体は「DBに保存された秘密情報を復号するための鍵」であるため、DBには
  保存できない。.envで明示指定しない場合はdata/fernet.keyに自動生成して永続化する
  （dataディレクトリはDBファイルと同様、デプロイ時にボリューム永続化される想定）。
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings

logger = logging.getLogger(__name__)

_DEFAULT_KEY_FILE = Path("data/fernet.key")


class SecretCipher:
    """DBに保存する秘密情報（VRChatトークン等）のアプリ層暗号化を担うラッパー。"""

    def __init__(self, fernet_master_key: str) -> None:
        self._fernet = Fernet(fernet_master_key.encode("utf-8"))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("復号に失敗しました。鍵が一致しないか値が破損しています。") from exc


def _load_or_create_key_file(key_file: Path) -> str:
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()

    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key().decode("ascii")
    key_file.write_text(key, encoding="utf-8")
    logger.info("Fernet鍵を新規生成し%sへ保存しました", key_file)
    return key


def get_secret_cipher(settings: Settings, *, key_file: Path = _DEFAULT_KEY_FILE) -> SecretCipher:
    key = settings.fernet_master_key or _load_or_create_key_file(key_file)
    return SecretCipher(key)


def generate_session_token() -> str:
    """Cookieに載せる高エントロピーな生トークンを生成する。"""
    return secrets.token_urlsafe(32)


def hash_session_token(raw_token: str) -> str:
    """DBに保存するためのトークンハッシュ（生トークンはDBに保存しない）。"""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_oauth_state() -> str:
    """Discord OAuth2のCSRF対策用stateパラメータを生成する。"""
    return secrets.token_urlsafe(24)
