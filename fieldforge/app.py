"""Application service layer for FieldForge."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
from fieldforge.core.readiness import ReadinessScore, readiness_score
from fieldforge.db.database import FieldForgeDatabase
from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.navigation.geo import Waypoint
from fieldforge.planners.evacuation import (
    DestinationPlan,
    EvacuationAssessment,
    VehiclePlan,
    assess_evacuation,
)
from fieldforge.planners.resources import ResourceRunway, food_runway, water_runway
from fieldforge.scenarios.engine import available_scenarios, scenario_actions


class FieldForgeApp:
    def __init__(self, database_path: str | Path) -> None:
        self.db = FieldForgeDatabase(database_path)
        self.knowledge = KnowledgeLibrary(database_path)

    def add_knowledge_article(self, article: KnowledgeArticle) -> None:
        self.knowledge.upsert(article)

    def search_knowledge(self, query: str, limit: int = 20) -> list[dict[str, object]]:
        return [result.__dict__ for result in self.knowledge.search(query, limit)]

    def knowledge_article(self, slug: str) -> KnowledgeArticle | None:
        return self.knowledge.get(slug)

    def add_member(self, member: HouseholdMember) -> HouseholdMember:
        return self.db.add_member(member)

    def add_item(self, item: InventoryItem) -> InventoryItem:
        return self.db.add_inventory_item(item)

    def members(self) -> list[HouseholdMember]:
        return self.db.list_members()

    def inventory(self, category: InventoryCategory | None = None) -> list[InventoryItem]:
        return self.db.list_inventory(category)

    def add_waypoint(self, waypoint: Waypoint) -> Waypoint:
        return self.db.add_waypoint(waypoint)

    def waypoints(self, kind: str | None = None) -> list[Waypoint]:
        return self.db.list_waypoints(kind)

    def add_incident(self, severity: str, message: str) -> int:
        return self.db.add_incident_entry(severity, message)

    def incidents(self, limit: int = 100) -> list[dict[str, object]]:
        return self.db.list_incident_entries(limit)

    def water_status(self, reserve_fraction: float = 0.10) -> ResourceRunway:
        return water_runway(self.members(), self.inventory(), reserve_fraction=reserve_fraction)

    def food_status(self, reserve_fraction: float = 0.10) -> ResourceRunway:
        return food_runway(self.members(), self.inventory(), reserve_fraction=reserve_fraction)

    def alerts(self, *, expiry_days: int = 30) -> dict[str, list[dict[str, object]]]:
        if expiry_days < 0:
            raise ValueError("expiry_days cannot be negative")
        cutoff = date.today() + timedelta(days=expiry_days)
        return {
            "low_stock": [item.as_dict() for item in self.db.low_stock_items()],
            "expiring": [item.as_dict() for item in self.db.expiring_items(cutoff)],
        }

    def scenario(self, name: str) -> dict[str, object]:
        actions = scenario_actions(name)
        return {
            "scenario": name,
            "actions": [action.as_dict() for action in actions],
            "notice": (
                "FieldForge is a planning aid. Official emergency instructions and immediate "
                "life-safety needs take precedence."
            ),
        }

    def scenario_names(self) -> tuple[str, ...]:
        return available_scenarios()

    def assess_evacuation(
        self,
        vehicle: VehiclePlan,
        destination: DestinationPlan,
    ) -> EvacuationAssessment:
        return assess_evacuation(len(self.members()), vehicle, destination)

    def readiness(
        self,
        *,
        backup_power_hours: float = 0.0,
        go_bag_fraction: float = 0.0,
        communications_fraction: float = 0.0,
        evacuation_plan_fraction: float = 0.0,
    ) -> ReadinessScore:
        water = self.water_status()
        food = self.food_status()
        return readiness_score(
            water_days=water.days_remaining or 0.0,
            food_days=food.days_remaining or 0.0,
            backup_power_hours=backup_power_hours,
            go_bag_fraction=go_bag_fraction,
            communications_fraction=communications_fraction,
            evacuation_plan_fraction=evacuation_plan_fraction,
        )

    def dashboard_snapshot(self) -> dict[str, object]:
        water = self.water_status().as_dict()
        food = self.food_status().as_dict()
        alerts = self.alerts()
        return {
            "household_members": len(self.members()),
            "inventory_items": len(self.inventory()),
            "waypoints": len(self.waypoints()),
            "incident_entries": len(self.incidents()),
            "water": water,
            "food": food,
            "alerts": alerts,
            "available_scenarios": list(self.scenario_names()),
            "knowledge_articles": self.knowledge.count(),
        }
