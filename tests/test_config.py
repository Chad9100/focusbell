import json

import pytest

from focusbell import config
from focusbell.config import DEFAULTS, ConfigError, load, save_value, validate


def test_defaults_when_no_file(tmp_path):
    assert load(tmp_path / "config.json") == DEFAULTS


def test_save_then_load(tmp_path):
    path = tmp_path / "sub" / "config.json"
    assert save_value(path, "work", "50") == 50
    assert save_value(path, "bell", "off") is False
    cfg = load(path)
    assert cfg["work"] == 50 and cfg["bell"] is False and cfg["short"] == 5
    assert json.loads(path.read_text(encoding="utf-8")) == {"work": 50, "bell": False}


@pytest.mark.parametrize(
    "key,value,expected",
    [
        ("work", "25", 25),
        ("work", "12.5", 12.5),
        ("work", 180, 180),
        ("short", "1", 1),
        ("long", "120", 120),
        ("cycles", "4", 4),
        ("cycles", "6.0", 6),
        ("bell", "YES", True),
        ("bell", "0", False),
        ("color", "NEVER", "never"),
    ],
)
def test_valid_values(key, value, expected):
    assert validate(key, value) == expected


@pytest.mark.parametrize(
    "key,value",
    [
        ("work", "0"),
        ("work", "181"),
        ("work", "abc"),
        ("work", "nan"),
        ("work", True),
        ("short", "61"),
        ("long", "0.5"),
        ("cycles", "2.5"),
        ("cycles", "13"),
        ("bell", "maybe"),
        ("color", "rainbow"),
        ("volume", "11"),
    ],
)
def test_invalid_values(key, value):
    with pytest.raises(ConfigError):
        validate(key, value)


def test_range_error_mentions_bounds():
    with pytest.raises(ConfigError, match="between 1 and 180"):
        validate("work", "500")


def test_corrupt_config_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{oops", encoding="utf-8")
    warnings = []
    assert load(path, warnings.append) == DEFAULTS
    assert warnings and "unreadable" in warnings[0]


def test_bad_entries_are_ignored_individually(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"work": 999, "short": 3, "nope": 1}), encoding="utf-8")
    warnings = []
    cfg = load(path, warnings.append)
    assert cfg["work"] == 25 and cfg["short"] == 3
    assert len(warnings) == 2


def test_save_rejects_invalid_and_leaves_file_alone(tmp_path):
    path = tmp_path / "config.json"
    save_value(path, "cycles", "3")
    with pytest.raises(ConfigError):
        save_value(path, "cycles", "99")
    assert load(path)["cycles"] == 3


def test_keys_lists_all_settings():
    assert config.keys() == ["work", "short", "long", "cycles", "bell", "notify", "color", "todo_file",
                             "tally", "weekly_goal"]
