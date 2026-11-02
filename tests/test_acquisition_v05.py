"""Network-free integration tests for Nass v0.5 acquisition provider."""
import json
import pytest
from nass_mcp.acquisition_v05 import fetch_invidious_captions, _origin, acquisition_report


def fake_reader(request, limit, timeout):
    assert request.full_url.startswith("https://example.org/api/v1/captions/QxC5E44QoZY")
    if "?" in request.full_url:
        return b"WEBVTT\\n\\n00:00:01.000 --> 00:00:02.000\\nhello"
    return json.dumps({"captions": [
        {"languageCode": "en", "label": "English", "url": "http://127.0.0.1/private"},
        {"languageCode": "ar", "label": "Arabic"},
    ]}).encode()


def fake_parser(content):
    assert "hello" in content
    return [{"start": 1.0, "end": 2.0, "text": "hello"}]


def test_invidious_rebuilds_url_on_approved_origin():
    segments, origin = fetch_invidious_captions("QxC5E44QoZY", "en", fake_parser,
        instance="https://example.org", reader=fake_reader)
    assert segments[0]["text"] == "hello"
    assert origin == "invidious-captions:en"


def test_invidious_rejects_bad_video_id():
    with pytest.raises(ValueError):
        fetch_invidious_captions("../admin", "en", fake_parser, instance="https://example.org", reader=fake_reader)


@pytest.mark.parametrize("url", ["http://example.org", "https://u:p@example.org",
                                  "https://example.org/path", "https://example.org/?x=1",
                                  "ftp://example.org", ""])
def test_bad_origins(url):
    with pytest.raises(ValueError):
        _origin(url)


def test_disabled_optional_config_has_no_secrets(monkeypatch):
    monkeypatch.setenv("NASS_INVIDIOUS_URL", "https://example.org")
    monkeypatch.setenv("NASS_ENABLE_MWEB_POT", "1")
    data = acquisition_report()
    assert data["invidious_origin_valid"]
    assert data["mweb_pot_opt_in"]
    assert "https://example.org" not in str(data)


def test_no_track_raises():
    def only_english(req, max_size, timeout):
        return json.dumps({"captions": [{"languageCode": "en", "label": "English"}]}).encode()
    with pytest.raises(RuntimeError):
        fetch_invidious_captions("QxC5E44QoZY", "ar", fake_parser,
            instance="https://example.org", reader=only_english)
