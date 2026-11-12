import yaml

from src import config


def _setup_temp_config_dir(tmp_path, monkeypatch, initial_data: dict) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "config.yaml"
    cfg_file.write_text(yaml.safe_dump(initial_data), encoding="utf-8")

    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config, "ensure_directories", lambda: None)
    monkeypatch.setattr(config, "_CONFIG_CACHE", None)
    monkeypatch.setattr(config, "_CONFIG_CACHE_MTIME_NS", None)
    monkeypatch.setattr(config, "_CONFIG_CACHE_PATH", None)


def test_load_config_uses_mtime_cache_and_returns_deepcopy(tmp_path, monkeypatch):
    _setup_temp_config_dir(
        tmp_path,
        monkeypatch,
        {"twitch": {"client_id": "abc"}, "streamers": ["a"]},
    )

    parse_calls = 0
    real_safe_load = yaml.safe_load

    def counting_safe_load(stream):
        nonlocal parse_calls
        parse_calls += 1
        return real_safe_load(stream)

    monkeypatch.setattr(yaml, "safe_load", counting_safe_load)

    first = config.load_config()
    first["streamers"].append("mutated")
    second = config.load_config()

    assert parse_calls == 1
    assert second["streamers"] == ["a"]


def test_save_config_invalidates_cache(tmp_path, monkeypatch):
    _setup_temp_config_dir(tmp_path, monkeypatch, {"twitch": {"client_id": "old"}})

    assert config.load_config()["twitch"]["client_id"] == "old"
    config.save_config({"twitch": {"client_id": "new"}})
    assert config.load_config()["twitch"]["client_id"] == "new"


def test_env_var_secret_overrides(tmp_path, monkeypatch):
    _setup_temp_config_dir(
        tmp_path,
        monkeypatch,
        {
            "twitch": {"client_id": "file_id", "client_secret": "file_secret"},
            "ai": {"api_key": "file_gemini"},
        },
    )

    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "env_secret")
    monkeypatch.setenv("GEMINI_API_KEY", "env_gemini")

    loaded = config.load_config()
    assert loaded["twitch"]["client_id"] == "file_id"
    assert loaded["twitch"]["client_secret"] == "env_secret"
    assert loaded["ai"]["api_key"] == "env_gemini"
