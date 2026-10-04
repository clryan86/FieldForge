"""Explicit consent and browser handoff for the optional online workspace."""

import webbrowser
from tkinter import messagebox

from fieldforge.online.models import validate_portal_url


def confirm_connection(parent, url):
    url = validate_portal_url(url)
    return messagebox.askyesno(
        "Connect to the internet?",
        "FieldForge will contact this portal and open its home page in your browser:\n\n"
        + url + "\n\nAddress searches and route coordinates are sent only when you submit them. "
        "Your household records stay on this device.\n\n"
        "Disconnect stops FieldForge's online tools; it does not turn off your internet "
        "or close the browser. Continue online?",
        parent=parent, icon="warning", default="no",
    )


def open_portal(url):
    """Open only a validated portal home; callers keep a copyable URL fallback."""
    try:
        return bool(webbrowser.open(validate_portal_url(url), new=2))
    except (OSError, ValueError, webbrowser.Error):
        return False
