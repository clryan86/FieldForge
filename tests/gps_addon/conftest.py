"""Keep independent test Tcl interpreters on the test's UI thread at teardown."""

import gc
import os

import pytest


@pytest.fixture(scope="session")
def gps_display():
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:
        if os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1":
            pytest.fail("GPS graphical verification requires a functioning Tk display")
        pytest.skip("A display is required; GPS UI tests run in the graphical CI jobs")
    root.destroy()
    gc.collect()


@pytest.fixture(autouse=True)
def collect_destroyed_test_interpreters(request):
    """Each GUI test creates its own Tk interpreter, unlike the one-root app.

    Collect destroyed test-root cycles on their owner thread before a subsequent
    test starts parser workers. Production GC behavior is not modified and no
    warnings or failures are suppressed by this fixture.
    """
    graphical = request.node.path.name in {
        "test_ui.py",
        "test_trip_ui.py",
        "test_review_ui.py",
        "test_local_map_ui.py",
        "test_live_map_ui.py",
        "test_places_ui.py",
        "test_workspace_ui.py",
        "test_bundled_atlas_ui.py",
    }
    if graphical:
        request.getfixturevalue("gps_display")
        gc.collect()
    yield
    if graphical:
        gc.collect()
