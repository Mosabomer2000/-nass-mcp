import json
import pytest
from urllib.parse import urlsplit, parse_qs
from nass_mcp.acquisition_v05 import _invidious_base, acquisition_report, fetch_invidious_captions

VID = "QxC5E44QoZY"
def parse_vtt(txt):
    return [{"start":1.0,"end":2.0,"text":"السلام عليكم"}] if "-->" in txt else []

def test_arabic_track_and_no_cross_origin_fetch():
    calls=[]
    def reader(req, size, timeout):
        calls.append(req.full_url)
        if len(calls)==1:
            return json.dumps({"captions":[{"label":"Arabic","languageCode":"ar","url":"https://attacker.example"}]}).encode()
        return b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n"
    seg, source = fetch_invidious_captions(VID,"ar",parse_vtt,instance="https://invidious.example",reader=reader)
    assert source=="invidious-captions:ar" and seg[0]["text"]=="السلام عليكم"
    assert all(urlsplit(u).hostname=="invidious.example" for u in calls)
    assert parse_qs(urlsplit(calls[1]).query)["label"] == ["Arabic"]

def test_no_auto_translation():
    with pytest.raises(RuntimeError,match="no captions"):
        fetch_invidious_captions(VID,"ar",parse_vtt,instance="https://invidious.example",
            reader=lambda *_: b'{"captions":[{"label":"English","languageCode":"en"}]}')

@pytest.mark.parametrize("url",[
    "http://remote.example","https://user:pass@remote.example",
    "https://remote.example/subpath","file:///tmp/x","https://remote.example?token=1"])
def test_reject_untrusted_origin(url):
    with pytest.raises(ValueError):
        _invidious_base(url)

def test_local_http_allowed():
    assert _invidious_base("http://127.0.0.1:3000/")=="http://127.0.0.1:3000"

def test_no_request_on_invalid_id():
    with pytest.raises(ValueError):
        fetch_invidious_captions("../../../etc/passwd","ar",parse_vtt,
            instance="https://invidious.example",reader=lambda *_: b"")

def test_invalid_vtt_rejected():
    i=0
    def reader(*_):
        nonlocal i
        i+=1
        return b'{"captions":[{"label":"Arabic","languageCode":"ar"}]}' if i==1 else b"WEBVTT\n"
    with pytest.raises(RuntimeError,match="no valid WebVTT"):
        fetch_invidious_captions(VID,"ar",parse_vtt,instance="https://invidious.example",reader=reader)

def test_config_report_hides_upstream(monkeypatch):
    monkeypatch.setenv("NASS_INVIDIOUS_URL","https://private-instance.example")
    monkeypatch.setenv("NASS_ENABLE_MWEB_POT","1")
    report=acquisition_report()
    assert report["invidious_url_valid"] and report["mweb_pot_enabled"]
    assert "private-instance" not in repr(report)
