from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from fieldforge_gps.live_map import centered, live_status, outside_follow_box
from fieldforge_gps.mercator import MercatorView
from fieldforge_gps.nmea import parse_sentence
from fieldforge_gps.review_map import View
from fieldforge_gps.session import Session, Snapshot

from .test_nmea import gga, rmc
from .test_session import WALL


def snapshot(**changes):
    base = Snapshot(
        "serial", "Receiver-reported position.", parse_sentence(rmc()), 1, 0, 0, 0, None, "", True
    )
    return replace(base, **changes)


def eligible(s, **kwargs):
    return live_status(s, consent=True, wgs84_confirmed=True, **kwargs)


def test_serial_running_fresh_fix_eligible():
    s = snapshot()
    result = eligible(s)
    assert result.code == "fix" and result.position is s.position
    assert "not independently verified" in result.message


@pytest.mark.parametrize("value", [False, None, 1, "yes"])
def test_strict_display_consent(value):
    assert live_status(snapshot(), consent=value, wgs84_confirmed=True).position is None


@pytest.mark.parametrize("value", [False, None, 1, "yes"])
def test_strict_datum_confirmation(value):
    assert live_status(snapshot(), consent=True, wgs84_confirmed=value).position is None


def test_no_source_is_not_live():
    assert eligible(None).code == "disconnected"


@pytest.mark.parametrize("running", [False, True])
def test_recordings_never_enter_live_layer(running):
    result = eligible(snapshot(mode="recorded", running=running, recording_sha256="a" * 64))
    assert result.code == "recorded" and result.position is None
    assert "NOT LIVE" in result.message


@pytest.mark.parametrize("mode", ["gpx", "demo", "bluetooth", "", None])
def test_unknown_mode_is_not_a_serial_fix(mode):
    assert eligible(snapshot(mode=mode)).position is None


@pytest.mark.parametrize("running", [False, None, 1])
def test_stopped_or_non_boolean_running_refused(running):
    assert eligible(snapshot(running=running)).position is None


def test_no_fix_keeps_receiver_diagnostic():
    result = eligible(snapshot(position=None, status="Stale receiver position — hidden; waiting."))
    assert result.code == "no-fix" and result.message.startswith("Stale")


@pytest.mark.parametrize(
    "changes",
    [
        {"latitude": float("nan")},
        {"longitude": float("inf")},
        {"latitude": True},
        {"latitude": "10"},
        {"longitude": None},
        {"latitude": 91},
        {"latitude": -91},
        {"longitude": 181},
        {"longitude": -181},
        {"timestamp": None},
        {"timestamp": datetime(2026, 10, 2)},
        {"timestamp": "2026-10-02T12:00:00Z"},
        {"valid": False},
        {"valid": 1},
        {"family": "GGA"},
    ],
)
def test_malformed_fix_refused(changes):
    result = eligible(snapshot(position=replace(parse_sentence(rmc()), **changes)))
    assert result.code == "invalid" and result.position is None


@pytest.mark.parametrize("latitude", [86, 90, -86, -90])
def test_polar_fix_allowed_only_on_coarse_overview(latitude):
    s = snapshot(position=replace(parse_sentence(rmc()), latitude=latitude))
    assert eligible(s).position is not None
    result = eligible(s, mercator=True)
    assert result.position is None and result.code == "polar"


@pytest.mark.parametrize("view", [View(0, 0, 100), MercatorView(0, 0, 8)])
def test_center_preserves_projection_scale_and_wraps_dateline(view):
    p = replace(parse_sentence(rmc()), longitude=180)
    new = centered(view, p)
    assert new.longitude == -180 and new.latitude == 10
    assert type(new) is type(view)
    assert (new.span if isinstance(new, View) else new.level) == (
        view.span if isinstance(view, View) else view.level
    )


def test_center_does_not_clamp_poles_into_mercator():
    with pytest.raises(ValueError):
        centered(MercatorView(), replace(parse_sentence(rmc()), latitude=90))


def test_follow_dead_zone_and_seam():
    p = replace(parse_sentence(rmc()), latitude=0, longitude=-179.9)
    view = MercatorView(179.9, 0, 2)
    assert not outside_follow_box(view, p, 1000, 500)
    p = replace(p, longitude=0)
    assert outside_follow_box(view, p, 1000, 500)


@pytest.mark.parametrize("dimensions", [(0, 10), (10, -1), (True, 10), (10, 1.5)])
def test_follow_dimensions_validated(dimensions):
    with pytest.raises(ValueError):
        outside_follow_box(View(), parse_sentence(rmc()), *dimensions)


def test_session_age_exact_threshold_and_repeat_does_not_refresh():
    now = [0.0]
    session = Session("serial", clock=lambda: now[0], utc_now=lambda: WALL)
    session._running = True  # Unit test of the Session snapshot / policy boundary.
    session._feed(rmc())
    now[0] = 4.999
    assert eligible(session.snapshot()).position
    session._feed(rmc())
    now[0] = 5.0
    assert eligible(session.snapshot()).position is None


@pytest.mark.parametrize("offset", [-11, 11, 3600])
def test_session_clock_mismatch_not_displayed(offset):
    session = Session("serial", clock=lambda: 0, utc_now=lambda: WALL + timedelta(seconds=offset))
    session._running = True
    session._feed(rmc())
    assert eligible(session.snapshot()).position is None


@pytest.mark.parametrize(
    "invalid", [rmc(status="V"), gga(quality="0"), b"$GNRMC,bad*00\r\n", rmc(mode="S")]
)
def test_no_fix_corruption_and_simulation_hide_previous_fix(invalid):
    session = Session("serial", clock=lambda: 0, utc_now=lambda: WALL)
    session._running = True
    session._feed(rmc())
    assert eligible(session.snapshot()).position
    session._feed(invalid)
    assert eligible(session.snapshot()).position is None
