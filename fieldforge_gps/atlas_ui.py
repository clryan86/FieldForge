"""Choose a bundled atlas view without scanning files or opening a receiver."""

import tkinter as tk
from tkinter import ttk

from .bundled_atlas import NOTICE, REGIONS


def choose_atlas(parent, callback):
    window = tk.Toplevel(parent)
    window.title("FieldForge · Included U.S. overview atlas")
    window.geometry("640x400")
    window.minsize(560, 400)
    panel = ttk.Frame(window, padding=20)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="Included U.S. overview atlas",
              font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
    notice = ttk.Label(panel, text=NOTICE, wraplength=580, justify="left")
    notice.pack(fill="x", pady=12)
    panel.bind("<Configure>", lambda e: notice.configure(wraplength=max(300, e.width - 40)))
    choice = tk.StringVar(value=next(iter(REGIONS)))
    picker = ttk.Combobox(panel, textvariable=choice, values=tuple(REGIONS), state="readonly")
    picker.pack(fill="x", pady=(0, 12))

    def open_view():
        region = choice.get()
        if region in REGIONS:
            window.destroy()
            callback(region)

    ttk.Button(panel, text="Open selected overview", command=open_view).pack(anchor="w")
    ttk.Label(panel, text="Made with Natural Earth · public domain · stored in this application").pack(
        anchor="w", pady=(12, 0))
    return window
