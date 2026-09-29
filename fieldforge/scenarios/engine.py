"""Emergency scenario action generation.

Actions are preparedness prompts, not substitutes for official emergency
instructions. When authorities issue evacuation or shelter orders, those orders
supersede FieldForge scenario output.
"""

from __future__ import annotations

from fieldforge.core.models import EmergencyAction, Priority

_SCENARIOS: dict[str, tuple[EmergencyAction, ...]] = {
    "power_outage": (
        EmergencyAction("Confirm immediate life-safety needs", Priority.CRITICAL, "Identify hazards and medical-device dependencies first."),
        EmergencyAction("Preserve refrigerator and freezer temperature", Priority.HIGH, "Keep doors closed and consolidate cold storage only when necessary."),
        EmergencyAction("Switch to the critical-load power plan", Priority.HIGH, "Reserve finite battery or generator energy for essential loads."),
        EmergencyAction("Check carbon-monoxide precautions", Priority.CRITICAL, "Combustion equipment must never be operated in unsafe enclosed spaces."),
        EmergencyAction("Record outage start and resource status", Priority.MEDIUM, "A timestamp improves fuel, food, and battery planning."),
    ),
    "evacuation": (
        EmergencyAction("Follow official evacuation instructions", Priority.CRITICAL, "Official hazard information takes precedence over local planning tools."),
        EmergencyAction("Account for every household member", Priority.CRITICAL, "Prevent separation and confirm transport needs."),
        EmergencyAction("Take medications, documents, water, and go-bags", Priority.HIGH, "Prioritize irreplaceable and immediately necessary supplies."),
        EmergencyAction("Select primary and alternate destinations", Priority.HIGH, "Avoid relying on a single route or destination."),
        EmergencyAction("Notify the designated external contact", Priority.MEDIUM, "A contact outside the affected area can help coordinate separated members."),
    ),
    "severe_weather": (
        EmergencyAction("Check official warnings before conditions worsen", Priority.CRITICAL, "Hazard-specific instructions can change quickly."),
        EmergencyAction("Move people and essential supplies to the safest available area", Priority.HIGH, "Reduce exposure before travel becomes dangerous."),
        EmergencyAction("Charge communication and lighting equipment", Priority.HIGH, "Grid power and cellular service may fail."),
        EmergencyAction("Stage water, food, medications, and flashlights", Priority.MEDIUM, "Keep essentials accessible if movement becomes difficult."),
    ),
    "vehicle_stranded": (
        EmergencyAction("Evaluate traffic, weather, injury, and environmental hazards", Priority.CRITICAL, "The safest choice depends on immediate surroundings."),
        EmergencyAction("Contact emergency assistance when available", Priority.HIGH, "Provide location, people, vehicle description, and urgent medical needs."),
        EmergencyAction("Conserve fuel and battery power", Priority.HIGH, "Finite energy may be needed for heat, signaling, or communication."),
        EmergencyAction("Make the vehicle conspicuous without creating new hazards", Priority.MEDIUM, "Visibility can help rescuers locate the vehicle."),
    ),
    "lost_outdoors": (
        EmergencyAction("Stop, assess, and avoid aimless travel", Priority.HIGH, "Unplanned movement can increase separation from known search areas."),
        EmergencyAction("Address injury, exposure, and immediate shelter needs", Priority.CRITICAL, "Life-safety threats come before navigation."),
        EmergencyAction("Preserve communication battery and send location if possible", Priority.HIGH, "Coordinates and a concise status message can accelerate rescue."),
        EmergencyAction("Create visible and audible signals", Priority.MEDIUM, "Systematic signaling can improve detection."),
    ),
}


def available_scenarios() -> tuple[str, ...]:
    return tuple(sorted(_SCENARIOS))


def scenario_actions(name: str) -> list[EmergencyAction]:
    key = name.strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return list(_SCENARIOS[key])
    except KeyError as exc:
        raise ValueError(f"unknown scenario {name!r}; choose from {', '.join(available_scenarios())}") from exc
