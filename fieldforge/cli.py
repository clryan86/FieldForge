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
from fieldforge.core.snapshot import export_snapshot, restore_snapshot
from fieldforge.knowledge import KnowledgeArticle
from fieldforge.navigation.geo import Waypoint
from fieldforge.planners.evacuation import DestinationPlan, VehiclePlan
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

    knowledge_add = sub.add_parser("knowledge-add", help="Add or update an offline knowledge article")
    knowledge_add.add_argument("slug")
    knowledge_add.add_argument("title")
    knowledge_add.add_argument("body")
    knowledge_add.add_argument("category")
    knowledge_add.add_argument("--tags", default="")
    knowledge_add.add_argument("--source-title", default="")
    knowledge_add.add_argument("--source-url", default="")
    knowledge_add.add_argument("--source-publisher", default="")
    knowledge_add.add_argument("--reviewed-on", default="")
    knowledge_add.add_argument(
        "--safety-level", choices=["reference", "caution", "high_stakes"], default="reference"
    )

    knowledge_search = sub.add_parser("knowledge-search", help="Search the offline knowledge library")
    knowledge_search.add_argument("query")
    knowledge_search.add_argument("--limit", type=int, default=20)

    knowledge_show = sub.add_parser("knowledge-show", help="Show one offline knowledge article")
    knowledge_show.add_argument("slug")

    scenario = sub.add_parser("scenario", help="Generate prioritized actions for a scenario")
    scenario.add_argument("name")

    readiness = sub.add_parser("readiness", help="Calculate transparent preparedness score")
    readiness.add_argument("--power-hours", type=_finite_nonnegative, default=0.0)
    readiness.add_argument("--go-bag", type=_fraction, default=0.0)
    readiness.add_argument("--communications", type=_fraction, default=0.0)
    readiness.add_argument("--evacuation", type=_fraction, default=0.0)

    waypoint_add = sub.add_parser("waypoint-add", help="Store an offline waypoint or rendezvous point")
    waypoint_add.add_argument("name")
    waypoint_add.add_argument("latitude", type=float)
    waypoint_add.add_argument("longitude", type=float)
    waypoint_add.add_argument("--kind", default="waypoint")
    waypoint_add.add_argument("--notes", default="")

    waypoint_list = sub.add_parser("waypoints", help="List stored offline waypoints")
    waypoint_list.add_argument("--kind")

    incident_add = sub.add_parser("incident-add", help="Append an entry to the local incident journal")
    incident_add.add_argument("severity", choices=["info", "warning", "critical"])
    incident_add.add_argument("message")

    incident_list = sub.add_parser("incidents", help="List recent incident-journal entries")
    incident_list.add_argument("--limit", type=int, default=100)

    evacuate = sub.add_parser("evacuation-check", help="Assess one vehicle/destination evacuation plan")
    evacuate.add_argument("vehicle_name")
    evacuate.add_argument("seats", type=int)
    evacuate.add_argument("range_km", type=_finite_nonnegative)
    evacuate.add_argument("destination_name")
    evacuate.add_argument("distance_km", type=_finite_nonnegative)
    evacuate.add_argument("--vehicle-readiness", type=_fraction, default=1.0)
    evacuate.add_argument("--destination-confirmed", action="store_true")

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

    snapshot = sub.add_parser(
        "snapshot", help="Back up the complete FieldForge database, including knowledge and private notes"
    )
    snapshot.add_argument("destination", type=Path)

    snapshot_restore = sub.add_parser(
        "snapshot-restore", help="Restore a complete FieldForge snapshot"
    )
    snapshot_restore.add_argument("source", type=Path)
    snapshot_restore.add_argument(
        "--overwrite", action="store_true", help="Replace the target database after validation"
    )

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
        elif args.command == "knowledge-add":
            article = KnowledgeArticle(
                slug=args.slug, title=args.title, body=args.body, category=args.category,
                tags=tuple(tag.strip() for tag in args.tags.split(",") if tag.strip()),
                source_title=args.source_title, source_url=args.source_url,
                source_publisher=args.source_publisher, reviewed_on=args.reviewed_on,
                safety_level=args.safety_level,
            )
            app.add_knowledge_article(article)
            _emit({"slug": article.slug, "checksum": article.checksum, "status": "stored"})
        elif args.command == "knowledge-search":
            _emit(app.search_knowledge(args.query, args.limit))
        elif args.command == "knowledge-show":
            article = app.knowledge_article(args.slug)
            if article is None:
                raise KeyError(f"knowledge article {args.slug!r} not found")
            _emit(article.__dict__)
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
        elif args.command == "waypoint-add":
            waypoint = app.add_waypoint(
                Waypoint(
                    args.name,
                    args.latitude,
                    args.longitude,
                    kind=args.kind,
                    notes=args.notes,
                )
            )
            _emit(waypoint.as_dict())
        elif args.command == "waypoints":
            _emit([waypoint.as_dict() for waypoint in app.waypoints(args.kind)])
        elif args.command == "incident-add":
            _emit({"id": app.add_incident(args.severity, args.message), "status": "recorded"})
        elif args.command == "incidents":
            _emit(app.incidents(args.limit))
        elif args.command == "evacuation-check":
            assessment = app.assess_evacuation(
                VehiclePlan(
                    args.vehicle_name,
                    seats_available=args.seats,
                    estimated_range_km=args.range_km,
                    readiness_fraction=args.vehicle_readiness,
                ),
                DestinationPlan(
                    args.destination_name,
                    distance_km=args.distance_km,
                    confirmed_available=args.destination_confirmed,
                ),
            )
            _emit(assessment.as_dict())
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
        elif args.command == "snapshot":
            _emit({"snapshot": str(export_snapshot(args.database, args.destination))})
        elif args.command == "snapshot-restore":
            _emit(restore_snapshot(args.source, args.database, overwrite=args.overwrite))
        else:  # pragma: no cover
            parser.error("unknown command")
    except (KeyError, OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
