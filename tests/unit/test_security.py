"""フェーズ6: Fernet鍵の自動生成・永続化のユニットテスト。"""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.security import get_secret_cipher


def _make_settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


def test_get_secret_cipher_generates_and_persists_key_file(tmp_path: Path) -> None:
    key_file = tmp_path / "fernet.key"
    settings = _make_settings(fernet_master_key="")

    assert not key_file.exists()
    cipher = get_secret_cipher(settings, key_file=key_file)
    assert key_file.exists()

    # 暗号化/復号が実際に機能する
    ciphertext = cipher.encrypt("hello")
    assert cipher.decrypt(ciphertext) == "hello"


def test_get_secret_cipher_reuses_existing_key_file(tmp_path: Path) -> None:
    key_file = tmp_path / "fernet.key"
    settings = _make_settings(fernet_master_key="")

    cipher1 = get_secret_cipher(settings, key_file=key_file)
    ciphertext = cipher1.encrypt("hello")

    # 別のcipherインスタンスでも同じ鍵ファイルを読んで復号できる
    cipher2 = get_secret_cipher(settings, key_file=key_file)
    assert cipher2.decrypt(ciphertext) == "hello"


def test_get_secret_cipher_prefers_explicit_setting_over_file(tmp_path: Path) -> None:
    from cryptography.fernet import Fernet

    key_file = tmp_path / "fernet.key"
    explicit_key = Fernet.generate_key().decode("ascii")
    settings = _make_settings(fernet_master_key=explicit_key)

    get_secret_cipher(settings, key_file=key_file)
    assert not key_file.exists()
