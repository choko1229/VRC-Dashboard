"""デスクトップエージェントのログ監視（滞在中インスタンスの追跡・退出漏れ検知）のユニットテスト。

VRChatを強制終了/クラッシュさせると"OnLeftRoom"がログに出力されないままプロセスが消え、
退出イベントを送れなくなる（サーバー側の経過時間表示が際限なく伸び続けるバグの根本原因）。
GameLogWatcherはVRChatプロセスの生死を定期的に確認し、消えていたら退出イベントを
補って送信することでこれを防ぐ。
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pytest

from desktop_agent import gamelog_watcher
from desktop_agent.gamelog_parser import ParsedEvent
from desktop_agent.gamelog_watcher import GameLogWatcher


def _make_watcher(**overrides: object) -> GameLogWatcher:
    kwargs: dict[str, object] = {
        "server_url": "https://example.com",
        "api_key": "dummy",
        "log_dir": Path("dummy"),
        "state_file": Path("dummy_state.json"),
    }
    kwargs.update(overrides)
    return GameLogWatcher(**kwargs)  # type: ignore[arg-type]


def test_instance_join_sets_in_room() -> None:
    watcher = _make_watcher()
    watcher._handle_parsed_event(
        ParsedEvent(event_type="instance_join", occurred_at=datetime.now(), location="wrld_a:1")
    )
    assert watcher._in_room is True


def test_instance_leave_clears_in_room() -> None:
    watcher = _make_watcher()
    watcher._handle_parsed_event(
        ParsedEvent(event_type="instance_join", occurred_at=datetime.now(), location="wrld_a:1")
    )
    watcher._handle_parsed_event(
        ParsedEvent(event_type="instance_leave", occurred_at=datetime.now())
    )
    assert watcher._in_room is False


def test_check_vrchat_still_running_noop_when_not_in_room(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_is_running() -> bool:
        nonlocal calls
        calls += 1
        return False

    monkeypatch.setattr(gamelog_watcher, "is_vrchat_running", fake_is_running)
    watcher = _make_watcher()
    watcher._last_process_check_at = time.monotonic() - 1000

    watcher._check_vrchat_still_running()

    assert calls == 0
    assert watcher._buffer == []


def test_check_vrchat_still_running_noop_when_process_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gamelog_watcher, "is_vrchat_running", lambda: True)
    watcher = _make_watcher()
    watcher._in_room = True
    watcher._last_process_check_at = time.monotonic() - 1000

    watcher._check_vrchat_still_running()

    assert watcher._in_room is True
    assert watcher._buffer == []


def test_check_vrchat_still_running_synthesizes_leave_when_process_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gamelog_watcher, "is_vrchat_running", lambda: False)
    watcher = _make_watcher()
    watcher._in_room = True
    watcher._last_process_check_at = time.monotonic() - 1000

    watcher._check_vrchat_still_running()

    assert watcher._in_room is False
    assert len(watcher._buffer) == 1
    assert watcher._buffer[0]["event_type"] == "instance_leave"


def test_check_vrchat_still_running_respects_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_is_running() -> bool:
        nonlocal calls
        calls += 1
        return False

    monkeypatch.setattr(gamelog_watcher, "is_vrchat_running", fake_is_running)
    watcher = _make_watcher(process_check_interval_seconds=1000)
    watcher._in_room = True
    watcher._last_process_check_at = time.monotonic()

    watcher._check_vrchat_still_running()
    watcher._check_vrchat_still_running()

    assert calls == 0
    assert watcher._in_room is True
