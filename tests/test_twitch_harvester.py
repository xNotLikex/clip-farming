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
        patch("src.harvesters.twitch_clips.requests.get", side_effect=fake_get),
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
        patch("src.harvesters.twitch_clips.requests.get", side_effect=fake_get),
        patch.object(harvester, "fetch_clips_gql_fallback", return_value=[]) as mock_gql,
    ):
        harvester.fetch_clips_helix("trymacs", time_filter="ALL_TIME")

    mock_gql.assert_called_once_with("trymacs", time_filter="ALL_TIME")
