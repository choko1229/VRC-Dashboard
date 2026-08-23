"""ローカルエージェントのVRChatログ解析ロジックのユニットテスト。"""

from __future__ import annotations

from datetime import datetime

from desktop_agent.gamelog_parser import parse_line, parse_timestamp, world_id_from_location


def test_parse_timestamp() -> None:
    assert parse_timestamp("2026.08.17 00:17:53 Log        -  something") == datetime(
        2026, 8, 17, 0, 17, 53
    )


def test_parse_timestamp_returns_none_for_unrecognized_line() -> None:
    assert parse_timestamp("no timestamp here") is None


def test_parse_line_instance_join() -> None:
    line = (
        "2026.08.17 00:17:53 Log        -  [Behaviour] Joining "
        "wrld_12345678-1234-1234-1234-123456789012:12345~region(jp)"
    )
    event = parse_line(line)
    assert event is not None
    assert event.event_type == "instance_join"
    assert event.location == "wrld_12345678-1234-1234-1234-123456789012:12345~region(jp)"


def test_parse_line_world_name() -> None:
    line = "2026.08.17 00:17:53 Log        -  [Behaviour] Joining or Creating Room: FUJIYAMA"
    event = parse_line(line)
    assert event is not None
    assert event.event_type == "world_name"
    assert event.world_name == "FUJIYAMA"


def test_parse_line_left_room() -> None:
    line = "2026.08.17 00:33:00 Log        -  [Behaviour] OnLeftRoom"
    event = parse_line(line)
    assert event is not None
    assert event.event_type == "instance_leave"


def test_parse_line_player_joined_with_user_id() -> None:
    line = (
        "2026.08.17 00:18:00 Log        -  [Behaviour] OnPlayerJoined れーめーざくろ "
        "(usr_abcd1234-ab12-ab12-ab12-abcdef123456)"
    )
    event = parse_line(line)
    assert event is not None
    assert event.event_type == "player_join"
    assert event.player_name == "れーめーざくろ"
    assert event.player_vrchat_user_id == "usr_abcd1234-ab12-ab12-ab12-abcdef123456"


def test_parse_line_player_joined_without_user_id() -> None:
    line = "2026.08.17 00:18:00 Log        -  [Behaviour] OnPlayerJoined 34人が参加"
    event = parse_line(line)
    assert event is not None
    assert event.event_type == "player_join"
    assert event.player_name == "34人が参加"
    assert event.player_vrchat_user_id is None


def test_parse_line_player_left() -> None:
    line = "2026.08.17 00:33:00 Log        -  [Behaviour] OnPlayerLeft tukino1"
    event = parse_line(line)
    assert event is not None
    assert event.event_type == "player_leave"
    assert event.player_name == "tukino1"


def test_parse_line_video_play() -> None:
    line = (
        "2026.08.17 00:30:00 Log        -  [Video Playback] Attempting to resolve URL "
        "'https://www.youtube.com/watch?v=xFoTFCHU70s'"
    )
    event = parse_line(line)
    assert event is not None
    assert event.event_type == "video_play"
    assert event.detail == "https://www.youtube.com/watch?v=xFoTFCHU70s"


def test_parse_line_returns_none_for_unrelated_log_line() -> None:
    line = "2026.08.17 00:00:00 Log        -  [Behaviour] Something unrelated happened"
    assert parse_line(line) is None


def test_world_id_from_location() -> None:
    assert world_id_from_location("wrld_abc:12345~region(jp)") == "wrld_abc"


def test_world_id_from_location_without_instance_part() -> None:
    assert world_id_from_location("wrld_abc") == "wrld_abc"
