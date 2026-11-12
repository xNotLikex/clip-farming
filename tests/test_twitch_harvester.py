from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from src.harvesters.twitch_clips import TwitchClipHarvester


def _make_resp(status_code=200, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    return resp


def test_helix_last_week_sets_started_at_around_168h():
    harvester = TwitchClipHarvester()
    harvester.client_id = "cid"
    harvester.client_secret = "csec"

    captured_urls = []

    def fake_get(url, headers=None, timeout=10):
        captured_urls.append(url)
        if "helix/users" in url:
            return _make_resp(200, {"data": [{"id": "12345"}]})
        if "helix/clips" in url:
            return _make_resp(200, {"data": []})
        raise AssertionError(f"Unexpected URL: {url}")

    with (
        patch.object(harvester, "_get_app_access_token", return_value="tok"),
        patch.object(harvester.session, "get", side_effect=fake_get),
    ):
        harvester.fetch_clips_helix("trymacs", hours_back=12, time_filter="LAST_WEEK")

    clips_urls = [u for u in captured_urls if "helix/clips" in u]
    assert len(clips_urls) == 1
    qs = parse_qs(urlparse(clips_urls[0]).query)
    started_at = datetime.strptime(qs["started_at"][0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    delta_hours = (datetime.now(UTC) - started_at).total_seconds() / 3600.0
    assert 167.5 <= delta_hours <= 168.5


def test_harvest_channel_passes_time_filter_to_helix():
    harvester = TwitchClipHarvester()
    harvester.client_id = "cid"
    harvester.client_secret = "csec"

    with (
        patch("src.harvesters.twitch_clips.load_config", return_value={"twitch": {}, "autopilot": {}}),
        patch.object(harvester, "fetch_clips_helix", return_value=[]) as mock_helix,
    ):
        harvester.harvest_channel({"name": "nooreax", "time_filter": "LAST_MONTH"})

    mock_helix.assert_called_once()
    assert mock_helix.call_args.kwargs.get("time_filter") == "LAST_MONTH"


def test_helix_error_fallback_forwards_time_filter():
    harvester = TwitchClipHarvester()
    harvester.client_id = "cid"
    harvester.client_secret = "csec"

    def fake_get(url, headers=None, timeout=10):
        if "helix/users" in url:
            return _make_resp(200, {"data": [{"id": "12345"}]})
        if "helix/clips" in url:
            return _make_resp(500, {})
        raise AssertionError(f"Unexpected URL: {url}")

    with (
        patch.object(harvester, "_get_app_access_token", return_value="tok"),
        patch.object(harvester.session, "get", side_effect=fake_get),
        patch.object(harvester, "fetch_clips_gql_fallback", return_value=[]) as mock_gql,
    ):
        harvester.fetch_clips_helix("trymacs", time_filter="ALL_TIME")

    mock_gql.assert_called_once_with("trymacs", time_filter="ALL_TIME")


def test_gql_fallback_enforces_time_filter_allowlist():
    harvester = TwitchClipHarvester()
    captured_queries: list[str] = []

    def fake_post(url, json=None, headers=None, timeout=15):
        captured_queries.append((json or {}).get("query", ""))
        return _make_resp(200, {"data": {"user": {"clips": {"edges": []}}}})

    with patch.object(harvester.session, "post", side_effect=fake_post):
        harvester.fetch_clips_gql_fallback("trymacs", time_filter="LAST_DAY }}) { evil }")

    assert len(captured_queries) == 1
    assert "filter: LAST_DAY" in captured_queries[0]
    assert "evil" not in captured_queries[0]


def test_harvester_session_has_retry_adapter():
    harvester = TwitchClipHarvester()
    adapter = harvester.session.get_adapter("https://api.twitch.tv")
    assert adapter.max_retries.total == 3
    assert 429 in adapter.max_retries.status_forcelist

