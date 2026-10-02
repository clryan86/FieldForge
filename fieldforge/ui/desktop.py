"""Tkinter desktop dashboard for offline FieldForge operation."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fieldforge.app import FieldForgeApp
from fieldforge.core.emergency_actions import ActionStore
from fieldforge.core.household import HouseholdService
from fieldforge.core.supplies import SuppliesService
from fieldforge.planners.resources import battery_runtime_hours, solar_daily_energy_wh


def _database_path() -> Path:
    override = os.environ.get("FIELDFORGE_DB")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".fieldforge" / "fieldforge.db"


def run() -> None:
    """Launch the local desktop application.

    Tkinter is imported lazily so headless CLI installations can still use the
    rest of FieldForge without GUI support.
    """
    import tkinter as tk
    from tkinter import messagebox, ttk

    from fieldforge.ui.assistant import add_ask_library_tab
    from fieldforge.ui.emergency_actions import ActionWorkspace
    from fieldforge.ui.household import HouseholdTab
    from fieldforge.ui.knowledge import KnowledgeTab
    from fieldforge.ui.pathways import add_pathways_tab
    from fieldforge.ui.places import PlacesTab
    from fieldforge.ui.recovery import add_recovery_tab
    from fieldforge.ui.recreation import add_recreation_tab
    from fieldforge.ui.supplies import SuppliesTab

    app = FieldForgeApp(_database_path())
    supplies = SuppliesService(app.db.path)
    root = tk.Tk()
    root.title("FieldForge — Offline Emergency Operations")
    root.geometry("1240x800")
    root.minsize(1000, 700)

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure("Header.TLabel", font=("TkDefaultFont", 18, "bold"))
    style.configure("Metric.TLabel", font=("TkDefaultFont", 16, "bold"))
    style.configure("Emergency.TButton", font=("TkDefaultFont", 11, "bold"), padding=10)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=10, pady=10)

    dashboard_tab = ttk.Frame(notebook, padding=16)
    inventory_tab = ttk.Frame(notebook, padding=16)
    planners_tab = ttk.Frame(notebook, padding=16)
    emergency_tab = ttk.Frame(notebook, padding=16)
    notebook.add(dashboard_tab, text="Dashboard")
    notebook.add(inventory_tab, text="Inventory")
    notebook.add(planners_tab, text="Power Planner")
    notebook.add(emergency_tab, text="Emergency Mode")
    knowledge_tab = KnowledgeTab(notebook, app.knowledge)
    notebook.add(knowledge_tab, text="Knowledge Library")
    pathways_tab = add_pathways_tab(notebook, knowledge_tab)
    add_ask_library_tab(notebook, app.knowledge)
    recovery_tab = add_recovery_tab(notebook, app.db.path, knowledge_tab, pathways_tab)
    add_recreation_tab(notebook, app.db.path)
    places_panel = PlacesTab(notebook, app.db.path)
    notebook.add(places_panel, text="Places")

    # A compact-window selector keeps every section reachable when notebook
    # tabs extend past the right edge. It uses the same tab-change save guards.
    section_bar = ttk.Frame(root, name="section_navigation", padding=(10, 4))
    ttk.Label(section_bar, text="Go to section").pack(side="left", padx=(0, 8))
    section_choice = tk.StringVar(value="Dashboard")
    section_picker = ttk.Combobox(section_bar, name="choice", textvariable=section_choice,
                                  values=[notebook.tab(tab, "text") for tab in notebook.tabs()],
                                  state="readonly", width=28)
    section_picker.pack(side="left", fill="x", expand=True)
    section_visible = False

    def select_section(_event):
        for tab in notebook.tabs():
            if notebook.tab(tab, "text") == section_choice.get():
                notebook.select(tab)
                break

    def sync_section(_event):
        if notebook.select():
            section_choice.set(notebook.tab(notebook.select(), "text"))

    def compact_navigation(event):
        nonlocal section_visible
        if event.widget is root:
            wanted = event.width < 1160
            if wanted != section_visible:
                section_visible = wanted
                if wanted:
                    section_bar.pack(fill="x", before=notebook)
                else:
                    section_bar.pack_forget()

    section_picker.bind("<<ComboboxSelected>>", select_section)
    notebook.bind("<<NotebookTabChanged>>", sync_section, add=True)
    root.bind("<Configure>", compact_navigation, add=True)

    def close_application() -> None:
        if (not supplies_panel.can_close() or not household_panel.can_close()
                or not emergency_panel.can_close() or not places_panel.can_close() or not recovery_tab.can_close()):
            return
        if knowledge_tab.busy:
            messagebox.showinfo(
                "Pack operation in progress",
                "Finish the local knowledge-pack operation before closing.",
                parent=root,
            )
        elif knowledge_tab.save_current() and pathways_tab.save_current():
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_application)

    # Dashboard -------------------------------------------------------------
    ttk.Label(dashboard_tab, text="FieldForge Readiness Dashboard", style="Header.TLabel").pack(
        anchor="w"
    )
    ttk.Label(
        dashboard_tab,
        text="Local planning estimates: recorded stock, 10% reserve, and saved household daily allowances.",
    ).pack(anchor="w", pady=(2, 16))

    metrics = ttk.Frame(dashboard_tab)
    metrics.pack(fill="x")
    for column in range(4):
        metrics.columnconfigure(column, weight=1)

    member_value = tk.StringVar(value="0")
    item_value = tk.StringVar(value="0")
    water_value = tk.StringVar(value="—")
    food_value = tk.StringVar(value="—")
    metric_specs = (
        ("Household profiles", member_value),
        ("Inventory", item_value),
        ("Water estimate", water_value),
        ("Food estimate", food_value),
    )
    for column, (label, variable) in enumerate(metric_specs):
        box = ttk.LabelFrame(metrics, text=label, padding=14)
        box.grid(row=0, column=column, sticky="nsew", padx=4)
        ttk.Label(box, textvariable=variable, style="Metric.TLabel").pack()

    alert_box = ttk.LabelFrame(dashboard_tab, text="Planning inputs and stock alerts", padding=10)
    alert_box.pack(fill="both", expand=True, pady=(16, 8))
    alert_text = tk.Text(alert_box, height=16, wrap="word", state="disabled")
    alert_text.pack(fill="both", expand=True)

    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def refresh_dashboard() -> None:
        try:
            snapshot = supplies.dashboard()
        except (ValueError, OSError, sqlite3.Error) as exc:
            for variable in (member_value, item_value, water_value, food_value):
                variable.set("Check data")
            _set_text(alert_text, "Could not calculate from current records. No stale estimate is shown.\n\n" + str(exc))
            return
        member_value.set(str(snapshot["household_members"]))
        item_value.set(str(snapshot["inventory_items"]))
        water_value.set(snapshot["water"]["label"])
        food_value.set(snapshot["food"]["label"])
        lines = ["PLANNING ASSUMPTIONS", "The estimates are arithmetic, not a safety or nutrition assessment.",
                 "Stock is multiplied by its amount per unit, with a 10% reserve held back."]
        for resource in ("water", "food"):
            value = snapshot[resource]
            lines.append(f"{resource.title()}: saved daily allowance = {value['daily_need']:g} {value['unit']}/day.")
            if value["warnings"]:
                lines.extend(["", resource.upper() + " INPUTS NEED REVIEW", *value["warnings"]])
        if not snapshot["household_members"]:
            lines.extend(["", "Add or edit household planning allowances in Inventory → Household."])
        low_stock, dated = snapshot["low_stock"], snapshot["dated"]
        if low_stock:
            lines.extend(["", "LOW STOCK"])
            lines.extend(f"• {item.name}: {item.quantity:g} {item.unit} (threshold {item.minimum_quantity:g})" for item in low_stock)
        if dated:
            lines.extend(["", "RECORDED DATES PASSED OR WITHIN 30 DAYS"])
            lines.extend(f"• {item.name}: {item.expires_on}" for item in dated)
        lines.extend(["", "Review inputs hides the headline estimate when amounts are missing or a recorded date has passed.",
                      "A missing or future date does not establish stock safety. Keep unusable stock out of recorded usable quantities.",
                      "No alerts is not proof of complete preparedness. Refresh to pick up changes from other windows."])
        _set_text(alert_text, "\n".join(lines))

    ttk.Button(dashboard_tab, text="Refresh", command=refresh_dashboard).pack(anchor="e")

    # Inventory -------------------------------------------------------------
    inventory_pages = ttk.Notebook(inventory_tab)
    inventory_pages.pack(fill="both", expand=True)
    supplies_panel = SuppliesTab(inventory_pages, supplies, on_change=refresh_dashboard)
    household_panel = HouseholdTab(inventory_pages, HouseholdService(app.db.path), on_change=refresh_dashboard)
    inventory_pages.add(supplies_panel, text="Supplies")
    inventory_pages.add(household_panel, text="Household")
    original_backup_guard = recovery_tab.before_backup

    def save_before_backup() -> bool:
        return (supplies_panel.can_close() and household_panel.can_close()
                and emergency_panel.can_close() and places_panel.can_close() and original_backup_guard())

    recovery_tab.before_backup = save_before_backup

    # Power planner ---------------------------------------------------------
    ttk.Label(planners_tab, text="Emergency Power Planner", style="Header.TLabel").pack(anchor="w")
    ttk.Label(
        planners_tab,
        text="Runtime estimates expose conservative derating assumptions and do not replace equipment manuals.",
    ).pack(anchor="w", pady=(2, 16))

    planner_grid = ttk.Frame(planners_tab)
    planner_grid.pack(anchor="w")
    wh_var = tk.StringVar(value="1000")
    load_var = tk.StringVar(value="100")
    panel_var = tk.StringVar(value="400")
    sun_var = tk.StringVar(value="5")
    runtime_var = tk.StringVar(value="Battery runtime: —")
    solar_var = tk.StringVar(value="Daily solar: —")

    for row, (label, variable) in enumerate((
        ("Battery capacity (Wh)", wh_var),
        ("Critical load (W)", load_var),
        ("Solar array (W)", panel_var),
        ("Peak sun hours", sun_var),
    )):
        ttk.Label(planner_grid, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(planner_grid, textvariable=variable, width=16).grid(row=row, column=1, sticky="w", padx=8)

    def calculate_power() -> None:
        try:
            runtime = battery_runtime_hours(float(wh_var.get()), float(load_var.get()))
            solar = solar_daily_energy_wh(float(panel_var.get()), float(sun_var.get()))
        except ValueError as exc:
            messagebox.showerror("Invalid power input", str(exc))
            return
        runtime_var.set(f"Battery runtime: {runtime:.2f} hours")
        solar_var.set(f"Daily solar: {solar:.0f} Wh/day")

    ttk.Button(planner_grid, text="Calculate", command=calculate_power).grid(row=4, column=0, pady=12, sticky="w")
    ttk.Label(planner_grid, textvariable=runtime_var, style="Metric.TLabel").grid(row=5, column=0, columnspan=3, sticky="w", pady=6)
    ttk.Label(planner_grid, textvariable=solar_var, style="Metric.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=6)

    # Emergency mode --------------------------------------------------------
    emergency_panel = ActionWorkspace(emergency_tab, ActionStore(app.db.path))
    emergency_panel.pack(fill="both", expand=True)

    refresh_dashboard()
    root.mainloop()


if __name__ == "__main__":
    run()
