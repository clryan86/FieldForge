"""Connection consent defaults to staying offline; handoffs validate their URL."""

import pytest

from fieldforge.ui import portal_connection


def test_confirmation_names_destination_and_defaults_to_no(monkeypatch):
    calls = []
    monkeypatch.setattr(portal_connection.messagebox, "askyesno", lambda *args, **kw: calls.append((args, kw)) or False)
    assert not portal_connection.confirm_connection(None, "https://maps.example.org/")
    args, options = calls[0]
    assert args[0] == "Connect to the internet?"
    assert "https://maps.example.org" in args[1] and "browser" in args[1]
    assert options["default"] == "no" and options["icon"] == "warning"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "https://user:password@example.org", "http://remote.example.org"])
def test_invalid_handoff_never_launches_browser(monkeypatch, url):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid URL reached browser launcher")
    monkeypatch.setattr(portal_connection.webbrowser, "open", forbidden)
    assert not portal_connection.open_portal(url)


def test_browser_failure_returns_copyable_link_fallback(monkeypatch):
    calls = []
    def failed(url, **kwargs):
        calls.append((url, kwargs))
        raise OSError("No desktop browser")
    monkeypatch.setattr(portal_connection.webbrowser, "open", failed)
    assert not portal_connection.open_portal("https://maps.example.org")
    assert calls == [("https://maps.example.org", {"new": 2})]
