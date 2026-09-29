"""Command-line interface for FieldForge."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from fieldforge.app import FieldForgeApp
from fieldforge.core.backup import export_backup, restore_backup
from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
from fieldforge.planners.resources import (
    battery_runtime_hours,
    generator_runtime_hours,
    solar_daily_energy_wh,
)


def _default_database_path() -> Path:
    override = os.environ.get("FIELDFORGE_DB")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".fieldforge" / "fieldforge.db"


def _finite_nonnegative(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _fraction(value: str) -> float:
    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fieldforge",
        description="Offline-first emergency preparedness and survival operations toolkit.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=_default_database_path(),
        help="SQLite database path (default: ~/.fieldforge/fieldforge.db)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create or verify the local FieldForge database")
    sub.add_parser("dashboard", help="Print a compact readiness/resource snapshot")
    sub.add_parser("members", help="List household members")

    add_member = sub.add_parser("add-member", help="Add a household member")
    add_member.add_argument("name")
    add_member.add_argument("--water-liters", type=float, default=3.78541)
    add_member.add_argument("--calories", type=int, default=2000)
    add_member.add_argument("--notes", default="")
    add_member.add_argument("--child", action="store_true")
    add_member.add_argument("--pet", action="store_true")

    inventory = sub.add_parser("inventory", help="List inventory")
    inventory.add_argument("--category", choices=[category.value for category in InventoryCategory])

    add_item = sub.add_parser("add-item", help="Add an inventory item")
    add_item.add_argument("name")
    add_item.add_argument("category", choices=[category.value for category in InventoryCategory])
    add_item.add_argument("quantity", type=_finite_nonnegative)
    add_item.add_argument("unit")
    add_item.add_argument("--calories-per-unit", type=_finite_nonnegative, default=0.0)
    add_item.add_argument("--liters-per-unit", type=_finite_nonnegative, default=0.0)
    add_item.add_argument("--watt-hours-per-unit", type=_finite_nonnegative, default=0.0)
    add_item.add_argument("--minimum", type=_finite_nonnegative, default=0.0)
    add_item.add_argument("--expires")
    add_item.add_argument("--location", default="")
    add_item.add_argument("--notes", default="")

    sub.add_parser("water", help="Calculate current household water runway")
    sub.add_parser("food", help="Calculate current household food/calorie runway")
    sub.add_parser("alerts", help="List low-stock and expiring inventory alerts")

    scenario = sub.add_parser("scenario", help="Generate prioritized actions for a scenario")
    scenario.add_argument("name")

    readiness = sub.add_parser("readiness", help="Calculate transparent preparedness score")
    readiness.add_argument("--power-hours", type=_finite_nonnegative, default=0.0)
    readiness.add_argument("--go-bag", type=_fraction, default=0.0)
    readiness.add_argument("--communications", type=_fraction, default=0.0)
    readiness.add_argument("--evacuation", type=_fraction, default=0.0)

    battery = sub.add_parser("battery-runtime", help="Estimate battery runtime")
    battery.add_argument("watt_hours", type=_finite_nonnegative)
    battery.add_argument("load_watts", type=float)
    battery.add_argument("--usable", type=_fraction, default=0.85)
    battery.add_argument("--efficiency", type=_fraction, default=0.90)

    generator = sub.add_parser("generator-runtime", help="Estimate generator runtime")
    generator.add_argument("fuel", type=_finite_nonnegative)
    generator.add_argument("consumption_per_hour", type=float)
    generator.add_argument("--reserve", type=_fraction, default=0.15)

    solar = sub.add_parser("solar", help="Estimate daily solar harvest")
    solar.add_argument("panel_watts", type=_finite_nonnegative)
    solar.add_argument("peak_sun_hours", type=_finite_nonnegative)
    solar.add_argument("--efficiency", type=_fraction, default=0.75)

    backup = sub.add_parser("backup", help="Export a portable JSON backup")
    backup.add_argument("destination", type=Path)

    restore = sub.add_parser("restore", help="Restore a portable JSON backup into this database")
    restore.add_argument("source", type=Path)

    return parser


def _emit(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        app = FieldForgeApp(args.database)

        if args.command == "init":
            _emit({"database": str(args.database), "status": "ready"})
        elif args.command == "dashboard":
            _emit(app.dashboard_snapshot())
        elif args.command == "members":
            _emit([member.as_dict() for member in app.members()])
        elif args.command == "add-member":
            member = app.add_member(
                HouseholdMember(
                    name=args.name,
                    daily_water_liters=args.water_liters,
                    daily_calories=args.calories,
                    notes=args.notes,
                    is_child=args.child,
                    is_pet=args.pet,
                )
            )
            _emit(member.as_dict())
        elif args.command == "inventory":
            category = InventoryCategory(args.category) if args.category else None
            _emit([item.as_dict() for item in app.inventory(category)])
        elif args.command == "add-item":
            expires = date.fromisoformat(args.expires) if args.expires else None
            item = app.add_item(
                InventoryItem(
                    name=args.name,
                    category=InventoryCategory(args.category),
                    quantity=args.quantity,
                    unit=args.unit,
                    calories_per_unit=args.calories_per_unit,
                    liters_per_unit=args.liters_per_unit,
                    watt_hours_per_unit=args.watt_hours_per_unit,
                    minimum_quantity=args.minimum,
                    expires_on=expires,
                    location=args.location,
                    notes=args.notes,
                )
            )
            _emit(item.as_dict())
        elif args.command == "water":
            _emit(app.water_status().as_dict())
        elif args.command == "food":
            _emit(app.food_status().as_dict())
        elif args.command == "alerts":
            _emit(app.alerts())
        elif args.command == "scenario":
            _emit(app.scenario(args.name))
        elif args.command == "readiness":
            _emit(
                app.readiness(
                    backup_power_hours=args.power_hours,
                    go_bag_fraction=args.go_bag,
                    communications_fraction=args.communications,
                    evacuation_plan_fraction=args.evacuation,
                ).as_dict()
            )
        elif args.command == "battery-runtime":
            _emit(
                {
                    "runtime_hours": battery_runtime_hours(
                        args.watt_hours,
                        args.load_watts,
                        usable_fraction=args.usable,
                        inverter_efficiency=args.efficiency,
                    )
                }
            )
        elif args.command == "generator-runtime":
            _emit(
                {
                    "runtime_hours": generator_runtime_hours(
                        args.fuel,
                        args.consumption_per_hour,
                        reserve_fraction=args.reserve,
                    )
                }
            )
        elif args.command == "solar":
            _emit(
                {
                    "daily_energy_wh": solar_daily_energy_wh(
                        args.panel_watts,
                        args.peak_sun_hours,
                        system_efficiency=args.efficiency,
                    )
                }
            )
        elif args.command == "backup":
            _emit({"backup": str(export_backup(app.db, args.destination))})
        elif args.command == "restore":
            _emit(restore_backup(app.db, args.source))
        else:  # pragma: no cover
            parser.error("unknown command")
    except (KeyError, OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
