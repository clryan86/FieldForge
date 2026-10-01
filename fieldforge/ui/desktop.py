"""Tkinter desktop dashboard for offline FieldForge operation."""

from __future__ import annotations

import os
from pathlib import Path

from fieldforge.app import FieldForgeApp
from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
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
    from fieldforge.ui.knowledge import KnowledgeTab
    from fieldforge.ui.pathways import add_pathways_tab
    from fieldforge.ui.recovery import add_recovery_tab

    app = FieldForgeApp(_database_path())
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

    def close_application() -> None:
        if not recovery_tab.can_close():
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
        text="All values are calculated locally from your stored household and inventory data.",
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
        ("Household", member_value),
        ("Inventory", item_value),
        ("Water runway", water_value),
        ("Food runway", food_value),
    )
    for column, (label, variable) in enumerate(metric_specs):
        box = ttk.LabelFrame(metrics, text=label, padding=14)
        box.grid(row=0, column=column, sticky="nsew", padx=4)
        ttk.Label(box, textvariable=variable, style="Metric.TLabel").pack()

    alert_box = ttk.LabelFrame(dashboard_tab, text="Readiness alerts", padding=10)
    alert_box.pack(fill="both", expand=True, pady=(16, 8))
    alert_text = tk.Text(alert_box, height=16, wrap="word", state="disabled")
    alert_text.pack(fill="both", expand=True)

    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def refresh_dashboard() -> None:
        snapshot = app.dashboard_snapshot()
        member_value.set(str(snapshot["household_members"]))
        item_value.set(str(snapshot["inventory_items"]))
        water = snapshot["water"]["days_remaining"]
        food = snapshot["food"]["days_remaining"]
        water_value.set("—" if water is None else f"{water:.1f} days")
        food_value.set("—" if food is None else f"{food:.1f} days")
        lines: list[str] = []
        low_stock = snapshot["alerts"]["low_stock"]
        expiring = snapshot["alerts"]["expiring"]
        if low_stock:
            lines.append("LOW STOCK")
            lines.extend(f"  • {item['name']}: {item['quantity']} {item['unit']}" for item in low_stock)
        if expiring:
            if lines:
                lines.append("")
            lines.append("EXPIRING WITHIN 30 DAYS")
            lines.extend(f"  • {item['name']}: {item['expires_on']}" for item in expiring)
        if not lines:
            lines.append("No current low-stock or 30-day expiration alerts.")
        _set_text(alert_text, "\n".join(lines))

    ttk.Button(dashboard_tab, text="Refresh", command=refresh_dashboard).pack(anchor="e")

    # Inventory -------------------------------------------------------------
    top_inventory = ttk.Frame(inventory_tab)
    top_inventory.pack(fill="x")
    ttk.Label(top_inventory, text="Inventory", style="Header.TLabel").pack(side="left")

    columns = ("id", "name", "category", "quantity", "unit", "location")
    tree = ttk.Treeview(inventory_tab, columns=columns, show="headings", height=16)
    for col, width in (("id", 55), ("name", 260), ("category", 120), ("quantity", 90), ("unit", 90), ("location", 180)):
        tree.heading(col, text=col.replace("_", " ").title())
        tree.column(col, width=width, anchor="w")
    tree.pack(fill="both", expand=True, pady=(12, 8))

    form = ttk.LabelFrame(inventory_tab, text="Add supply", padding=10)
    form.pack(fill="x")
    name_var = tk.StringVar()
    category_var = tk.StringVar(value=InventoryCategory.OTHER.value)
    quantity_var = tk.StringVar(value="1")
    unit_var = tk.StringVar(value="each")
    location_var = tk.StringVar()

    ttk.Label(form, text="Name").grid(row=0, column=0, sticky="w")
    ttk.Entry(form, textvariable=name_var, width=28).grid(row=1, column=0, padx=(0, 8), sticky="ew")
    ttk.Label(form, text="Category").grid(row=0, column=1, sticky="w")
    ttk.Combobox(
        form,
        textvariable=category_var,
        values=[category.value for category in InventoryCategory],
        state="readonly",
        width=16,
    ).grid(row=1, column=1, padx=(0, 8), sticky="ew")
    ttk.Label(form, text="Quantity").grid(row=0, column=2, sticky="w")
    ttk.Entry(form, textvariable=quantity_var, width=10).grid(row=1, column=2, padx=(0, 8))
    ttk.Label(form, text="Unit").grid(row=0, column=3, sticky="w")
    ttk.Entry(form, textvariable=unit_var, width=12).grid(row=1, column=3, padx=(0, 8))
    ttk.Label(form, text="Location").grid(row=0, column=4, sticky="w")
    ttk.Entry(form, textvariable=location_var, width=18).grid(row=1, column=4, padx=(0, 8))
    form.columnconfigure(0, weight=1)

    def refresh_inventory() -> None:
        for node in tree.get_children():
            tree.delete(node)
        for item in app.inventory():
            tree.insert(
                "",
                "end",
                values=(item.id, item.name, item.category.value, item.quantity, item.unit, item.location),
            )
        refresh_dashboard()

    def add_inventory() -> None:
        try:
            item = InventoryItem(
                name=name_var.get(),
                category=InventoryCategory(category_var.get()),
                quantity=float(quantity_var.get()),
                unit=unit_var.get(),
                location=location_var.get(),
            )
            app.add_item(item)
        except ValueError as exc:
            messagebox.showerror("Invalid supply", str(exc))
            return
        name_var.set("")
        quantity_var.set("1")
        location_var.set("")
        refresh_inventory()

    ttk.Button(form, text="Add Supply", command=add_inventory).grid(row=1, column=5, sticky="e")

    household = ttk.LabelFrame(inventory_tab, text="Quick household setup", padding=10)
    household.pack(fill="x", pady=(8, 0))
    member_name_var = tk.StringVar()
    ttk.Entry(household, textvariable=member_name_var, width=30).pack(side="left", padx=(0, 8))

    def add_member() -> None:
        try:
            app.add_member(HouseholdMember(member_name_var.get()))
        except ValueError as exc:
            messagebox.showerror("Invalid household member", str(exc))
            return
        member_name_var.set("")
        refresh_dashboard()

    ttk.Button(household, text="Add Household Member", command=add_member).pack(side="left")

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
    ttk.Label(emergency_tab, text="Emergency Mode", style="Header.TLabel").pack(anchor="w")
    ttk.Label(
        emergency_tab,
        text="Use this as a local checklist. Official warnings, evacuation orders, and emergency services take precedence.",
        wraplength=900,
    ).pack(anchor="w", pady=(2, 12))

    scenario_row = ttk.Frame(emergency_tab)
    scenario_row.pack(fill="x")
    scenario_var = tk.StringVar(value=app.scenario_names()[0])
    scenario_picker = ttk.Combobox(
        scenario_row,
        textvariable=scenario_var,
        values=list(app.scenario_names()),
        state="readonly",
        width=28,
    )
    scenario_picker.pack(side="left", padx=(0, 8))
    emergency_text = tk.Text(emergency_tab, height=24, wrap="word", state="disabled")
    emergency_text.pack(fill="both", expand=True, pady=(10, 0))

    def load_scenario() -> None:
        payload = app.scenario(scenario_var.get())
        lines = [payload["notice"], ""]
        for index, action in enumerate(payload["actions"], start=1):
            lines.append(f"{index}. [{action['priority'].upper()}] {action['title']}")
            lines.append(f"   {action['reason']}")
            lines.append("")
        _set_text(emergency_text, "\n".join(lines))

    ttk.Button(
        scenario_row,
        text="LOAD EMERGENCY CHECKLIST",
        style="Emergency.TButton",
        command=load_scenario,
    ).pack(side="left")

    refresh_inventory()
    load_scenario()
    root.mainloop()


if __name__ == "__main__":
    run()
