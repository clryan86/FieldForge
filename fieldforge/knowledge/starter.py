"""Small, locally bundled starter library, not a complete survival curriculum.

No downloads, auto-overwrites, or fabricated editorial review dates. Source links
are attribution only; all article text is stored in this Python package so wheels
and source checkouts behave alike. See docs/STARTER_LIBRARY.md for scope/rights.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from fieldforge.knowledge.library import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.packs import export_pack

STARTER_VERSION = "2026-10-01.1"
STARTER_PREFIX = "starter-v1-"
NOTICE = "AI-drafted starter text; not independently reviewed by a subject specialist."
RIGHTS = (
    "Original FieldForge text, not a reproduction of the linked source. "
    "Project redistribution license not yet selected; linked sources retain their own terms."
)


def _article(slug: str, title: str, category: str, body: str, *,
             tags: tuple[str, ...], source_title: str = "FieldForge original worksheet",
             source_url: str = "", source_publisher: str = "FieldForge",
             safety_level: str = "reference") -> KnowledgeArticle:
    attribution = (
        f"\n\nSOURCE\n{source_title}\n{source_url}\nSource consulted: 2026-10-01. "
        "This is a short original summary, not the full source document. "
        "The source publisher has not reviewed or endorsed this summary."
        if source_url else "\n\nORIGIN\nOriginal FieldForge planning/learning exercise."
    )
    return KnowledgeArticle(
        slug=STARTER_PREFIX + slug, title=title, category=category,
        body=f"{NOTICE}\n\n{body.strip()}{attribution}",
        tags=("starter", *tags), source_title=source_title, source_url=source_url,
        source_publisher=source_publisher, reviewed_on="", safety_level=safety_level,
        license=RIGHTS,
    )


def starter_articles() -> tuple[KnowledgeArticle, ...]:
    """Return validated original summaries and practical worksheets, fully offline."""
    return (
        _article("start", "Start here: what this starter library can do", "start here", """
This collection is a small beginning, not the complete FieldForge vision. It contains readable references and worksheets; it is not an installed AI model, a medical textbook, or a full civilization-rebuilding course.

CHOOSE A TASK
For preparation: search for 'contact', 'water', or 'packing'.
For managing supplies: search for 'inventory' or 'power budget'.
For learning practical foundations: search for 'measurement', 'compost', or 'teaching'.
For keeping equipment information: search for 'maintenance'.

USE THE LIBRARY
Leave the search box blank to browse everything. Choose a category to narrow the list. Open an article, bookmark it, and write local observations in its private note. Distinguish what you measured from what you assumed.

BEFORE RELYING ON AN ARTICLE
Read its scope and source. A link identifies where a summary came from; it does not mean the complete source has been downloaded. An empty review date means no independent editorial review is recorded. Follow current local emergency instructions and equipment manuals rather than treating a starter summary as a complete procedure.

TRY IT
Open 'Inventory: count usable supplies and calculate runway'. Work through the fictional example. Then record your own units and assumptions in a note. Do not enter passwords or other unnecessary sensitive information.
""", tags=("orientation", "prepare", "learn")),
        _article("contacts", "Emergency planning: a contact and meeting card", "emergency planning", """
Prepare a short written plan while everyone can discuss it calmly. The Pennsylvania Emergency Management Agency recommends one nearby contact and another outside your area, meeting locations, and plans that include children, older adults, disabled people, and animals.

Write the contacts and meeting places on paper as well as storing them locally. Discuss how to get to a meeting place without your usual vehicle. Do not assume a shelter accepts animals or meets every access need; check ahead. Follow official evacuation instructions.

For routine family check-ins when networks are congested, a text may get through more easily than a call. Neither method is guaranteed. Agree on a fallback meeting plan before an outage.

CARD TEMPLATE
Local contact / number:
Out-of-area contact / number:
Nearby meeting place:
Meeting place outside the neighborhood:
Accessible transport and backup:
Who helps each person and animal:
Date checked with household:

Use fictional details when practicing in a shared demonstration database. Keep real contact information in private notes, not in articles you intend to distribute.
""", tags=("contacts", "communication", "prepare"),
                 source_title="PEMA / Ready PA — Make A Plan",
                 source_url="https://www.pa.gov/agencies/ready/get-prepared/make-a-plan",
                 source_publisher="Pennsylvania Emergency Management Agency", safety_level="caution"),
        _article("water-storage", "Water: build and label an emergency supply", "water and sanitation", """
CDC recommends storing at least one US gallon per person per day for three days, and a two-week supply when feasible. This is a household planning allowance, not a medical instruction about how much any individual should drink. Allow for pets, heat, illness, and other needs.

Unopened commercially bottled water is CDC's most reliable emergency option. For stored tap water, use suitable food-grade containers and follow the source's cleaning and sanitizing instructions before filling. Never repurpose a container that held toxic chemicals.

Label containers with their contents and storage date. Keep them cool, out of sunlight, and away from fuel or pesticides. CDC recommends replacing home-filled stored water every six months; observe the date on commercially bottled water.

PLANNING EXAMPLE
For four people for three days: 4 x 3 x 1 = 12 US gallons, before additional needs. Record container capacity and number of containers; 'one jug' is not a volume.

STORAGE RECORD
Container ID / usable volume / filled or purchased date / replacement date / storage location.

This article covers storage, not treatment of an unknown or contaminated water source.
""", tags=("water", "storage", "prepare"),
                 source_title="CDC — How to Create an Emergency Water Supply",
                 source_url="https://www.cdc.gov/water-emergency/about/how-to-create-and-store-an-emergency-water-supply.html",
                 source_publisher="Centers for Disease Control and Prevention", safety_level="high_stakes"),
        _article("water-limits", "Water: disinfection is not chemical decontamination", "water and sanitation", """
Water that looks clear is not necessarily safe. EPA distinguishes killing disease-causing microorganisms from removing chemical contamination. Boiling or chemical disinfection does not remove heavy metals, salts, and most other chemical contaminants.

Use a known safe emergency supply when available. Follow the local water authority's specific instructions. Do not assume boiling makes floodwater, industrially contaminated water, or any unknown source safe. A household filter is not a universal contaminant-removal device.

RECORD BEFORE CHOOSING A RESPONSE
Where did this water come from?
What is the actual advisory, its date, and its issuing authority?
Is the concern microorganisms, chemicals, or unknown?
Is a known safe alternative available?
What exactly does the treatment equipment's documentation say it removes?

This is a decision-boundary reference, not a treatment protocol. It deliberately does not supply chemical doses. Use the complete current instructions for the identified hazard, product, and concentration. A cloth filter may remove visible particles; that alone is not proof of drinking-water safety.
""", tags=("water", "contamination", "stabilize"),
                 source_title="EPA — Emergency Disinfection of Drinking Water",
                 source_url="https://www.epa.gov/ground-water-and-drinking-water/emergency-disinfection-drinking-water",
                 source_publisher="US Environmental Protection Agency", safety_level="high_stakes"),
        _article("generator", "Power outages: avoid generator carbon monoxide", "energy", """
Fuel-burning portable generators produce carbon monoxide, which can be fatal. CPSC warns against operating them in homes, garages, basements, sheds, or other enclosed spaces. Opening a door or window does not make indoor use safe. Do not burn charcoal indoors either.

CDC advises keeping a generator outdoors at least 20 feet from doors, windows, and vents. Direct exhaust away from buildings. This minimum is not a guarantee under every wind or site condition; obey the equipment manual and local safety guidance. Keep working carbon-monoxide alarms in the home. An automatic generator shutoff does not replace safe placement.

BEFORE AN OUTAGE
Locate the manual, identify a suitable outdoor site, and plan a safe power arrangement with a qualified electrician. This summary does not teach house wiring, refueling, or operation in wet weather. Do not improvise a connection to household wiring.

If a carbon-monoxide alarm sounds, move everyone outside to fresh air and call emergency services. Do not remain inside to diagnose the alarm or go back in until emergency responders permit it.

Additional source: CDC — Use a Generator Safely
https://www.cdc.gov/natural-disasters/psa-toolkit/use-a-generator-safely.html
Alarm response: CPSC — Carbon Monoxide Fact Sheet
https://www.cpsc.gov/safety-education/safety-guides/carbon-monoxide/carbon-monoxide-fact-sheet
""", tags=("generator", "carbon monoxide", "prepare"),
                 source_title="CPSC — Generators and Engine-Driven Tools; CDC generator safety",
                 source_url="https://www.cpsc.gov/Safety-Education/Safety-Guides/Carbon-Monoxide-Home/Generators-and-Engine-Driven-Tools",
                 source_publisher="US Consumer Product Safety Commission; CDC", safety_level="high_stakes"),
        _article("packing", "Outdoor preparedness: check systems, not just a bag", "outdoor preparedness", """
The National Park Service describes ten equipment systems for outdoor trips. Use them as a planning check rather than assuming a packed bag makes a trip safe.

Check navigation, sun protection, extra clothing, lighting, first-aid supplies, permitted fire-starting equipment, repair tools, extra food, water, and emergency shelter. Adapt equipment to the trip, weather, terrain, and participants. Fire equipment is not permission to light a fire.

Before leaving, tell a trusted person your route and expected return. Carry a physical map and learn to use your navigation tools before the trip. Bring backup power where needed; a phone alone is not a complete navigation plan.

PRACTICE CHECK
For each system, record: item / location / condition / who can use it / missing parts.
Test lights and inspect packed supplies. Check dates where applicable. Match personal medical supplies to an existing care plan rather than improvising treatment from this checklist.

This article is a packing overview. It is not a wilderness rescue procedure or a substitute for training and destination-specific guidance.
""", tags=("packing", "navigation", "shelter", "prepare"),
                 source_title="National Park Service — Ten Essentials",
                 source_url="https://www.nps.gov/articles/10essentials.htm",
                 source_publisher="US National Park Service", safety_level="caution"),
        _article("compost", "Agriculture: start a household compost record", "agriculture", """
EPA describes backyard composting as a balance of carbon-rich dry material, nitrogen-rich fresh material, moisture, and air. Dry leaves are one example of 'browns'; fruit and vegetable scraps are examples of 'greens'.

Choose a well-drained, accessible site. Break large scraps into smaller pieces. EPA suggests at least two to three volumes of browns for each volume of greens, with food scraps covered by browns. Keep the mix damp, not waterlogged, and turn it periodically to admit air. If it smells bad, excess moisture or insufficient air may be involved; add dry browns and mix.

For a simple backyard pile, exclude meat, dairy, grease, pet waste, diseased plants, treated wood, and herbicide-treated material. Do not assume a warm pile has sterilized its contents. This is not a system for processing human waste.

PILE LOG
Start date / ingredients and rough volumes / moisture observations / turning dates / changes in odor and appearance.

Finished compost is dark and crumbly with an earthy smell. EPA also describes a curing period. Consult the complete source before judging readiness. Compost is a soil amendment, not a guarantee of crop nutrition or food safety.
""", tags=("compost", "soil", "learn", "rebuild"),
                 source_title="EPA — Composting At Home",
                 source_url="https://www.epa.gov/recycle/composting-home",
                 source_publisher="US Environmental Protection Agency", safety_level="caution"),
        _article("inventory", "Inventory: count usable supplies and calculate runway", "logistics", """
This worksheet estimates how long a stock lasts under stated assumptions. It is arithmetic, not a safety guarantee or a prescription for rationing.

RECORD THE UNIT
Write 'six sealed containers, each 2 liters', not just 'six waters'. List the location, counted date, condition, and intended use. Separate damaged, contaminated, or otherwise unusable stock; do not count it as available.

FORMULA
Usable amount = counted usable stock x (1 - reserve fraction).
Estimated days = usable amount / expected daily use.

FICTIONAL EXAMPLE
A workshop has 40 identical clean cloths. A 10 percent reserve leaves 36 for routine use. At six cloths per day, estimated runway is 36 / 6 = 6 days. At nine per day it is only 4 days. The consumption assumption matters.

WHEN THE NUMBER IS UNKNOWN
Zero or unknown daily use does not justify displaying 'unlimited'. Mark the estimate unknown and measure use. Keep units consistent: liters divided by liters per day gives days; containers divided by liters per day does not.

NEXT ACTION
Count one category, record the assumption, calculate both normal and higher-use cases, and set a date to recount. Do not reduce medically required supplies based on this exercise.
""", tags=("inventory", "runway", "arithmetic", "stabilize")),
        _article("power-budget", "Energy: make a simple daily power budget", "energy", """
This worksheet accounts for energy; it is not a wiring or battery-construction guide. A watt measures power. A watt-hour measures energy: watts multiplied by hours.

LIST LOADS
For each device, record the measured or documented power, hours used per day, and whether the load is steady or intermittent. Note starting surges separately; an energy total does not prove an inverter can start a device.

FICTIONAL EXAMPLE
One 8-watt lamp for 5 hours uses 40 watt-hours. A 20-watt device for 3 hours uses 60 watt-hours. Together they need 100 watt-hours per day before conversion losses and other loads.

RUNTIME ESTIMATE
If 400 watt-hours are genuinely available at the output, a constant 50-watt load would run for 400 / 50 = 8 hours in the idealized calculation. Rated battery capacity is not necessarily usable output energy. Temperature, age, operating limits, and losses can change the result.

KEEP A RESERVE
Record uncertain values as uncertain. Do not use this worksheet to guarantee operation of life-support equipment; obtain a device-specific backup plan from its supplier and care team. Use approved equipment and a qualified electrician for installation.
""", tags=("power budget", "battery", "arithmetic", "stabilize"), safety_level="caution"),
        _article("measurement", "Foundations: keep measurements reproducible", "measurement and learning", """
A useful measurement record tells another person what was measured and how. Record the date, object, tool, unit, method, and any uncertainty. Keep estimates visibly separate from measurements.

PRACTICE WITH A RECTANGLE
Measure a tabletop's length and width in the same unit. For an example length of 1.2 meters and width of 0.6 meters, area is 1.2 x 0.6 = 0.72 square meters. Perimeter is 2 x (1.2 + 0.6) = 3.6 meters. Area and perimeter answer different questions.

CHECK THE RESULT
Measure again from the same reference points. Ask another person to repeat it. If the two results differ, check the tool, alignment, units, and rounding rather than averaging unexplained mistakes.

RECORD TEMPLATE
Object / purpose / tool / unit / readings / agreed result / uncertainty / operator.

TEACH-BACK
Have a learner explain why multiplying two lengths produces an area unit. Then change one dimension and recalculate. Keep the worksheet with the object drawing.

These are learning exercises, not structural calculations. Do not use approximate measurements alone to approve lifting equipment, load-bearing structures, or pressure systems.
""", tags=("measurement", "math", "teaching", "learn")),
        _article("maintenance", "Tools and vehicles: build a maintenance record", "tools and maintenance", """
Preserve the information needed to find the correct procedure before something fails. This worksheet does not authorize repairs or substitute parts.

EQUIPMENT CARD
Asset name / manufacturer / exact model / serial number / manual location / service contact.
Record its normal purpose, known defects, and whether it is available, awaiting inspection, or out of service.

SERVICE LOG
Date / running hours or mileage if applicable / observed symptom / work authorized / work performed / part identifier / person responsible / next inspection.

KEEP FACTS SEPARATE
'Would not start on this date' is an observation. 'Fuel pump failed' is a diagnosis that needs evidence. Preserve both, but do not substitute a guess for a confirmed diagnosis.

BEFORE USING THE RECORD
Match the manual and part information to the exact machine. Keep safety-critical inspection and service decisions with someone qualified for the equipment. Do not bypass guards or interlocks. A missing replacement part does not prove another part is compatible.

PRACTICE
Create a record for a harmless hand tool. Add a photograph or drawing to your own records, note its storage location, and record who knows how to inspect and use it. This starter does not include manufacturer repair manuals.
""", tags=("maintenance", "vehicles", "tools", "rebuild"), safety_level="caution"),
        _article("teaching", "Learning: turn a practical skill into a repeatable lesson", "measurement and learning", """
This is a proposed learning workflow, not a claim that reading replaces experience or professional qualification.

START WITH ONE OBSERVABLE RESULT
Example: 'The learner can count ten containers, record each capacity, and calculate total volume.' Avoid goals such as 'understand everything about water'.

WRITE THE PREREQUISITES
List the reading, arithmetic, tools, supervision, and safety knowledge needed first. Explain unfamiliar terms. Use the same units throughout the example.

DEMONSTRATE, PRACTICE, EXPLAIN
Show the task once. Let the learner repeat it using safe practice materials. Ask them to explain each step and check the result. Record mistakes without shaming the learner; revise the explanation where it was unclear.

PRESERVE THE LESSON
Keep a dated worksheet containing the goal, required materials, steps, checks, and limits. Record who can demonstrate the skill, who has practiced it, and what still needs qualified instruction. Retest after a break rather than assuming permanent proficiency.

REBUILDING CONNECTION
Map a larger project into prerequisite skills. For a garden record, those might include reading labels, measuring area, logging dates, and comparing observations. This map is a planning aid, not evidence that farming or other technical content is already complete in FieldForge.
""", tags=("teaching", "skills", "education", "learn", "rebuild")),
    )


STARTER_ARTICLE_COUNT = 12


def install_starter(library: KnowledgeLibrary) -> dict[str, int]:
    """Add missing starters atomically; never replace an article or personal note."""
    articles = starter_articles()
    added = unchanged = preserved = 0
    with library.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for article in articles:
            existing = db.execute(
                "SELECT * FROM knowledge_articles WHERE slug=?", (article.slug,)
            ).fetchone()
            if existing is not None:
                if library._article(existing) == article:
                    unchanged += 1
                else:
                    preserved += 1
                continue
            library._write(db, article)
            added += 1
    return {"added": added, "unchanged": unchanged, "preserved": preserved}


def export_starter(destination: str | Path) -> Path:
    """Build a compatible pack from only bundled text, never the user's database."""
    with tempfile.TemporaryDirectory(prefix="fieldforge-starter-") as directory:
        library = KnowledgeLibrary(Path(directory) / "starter.db")
        install_starter(library)
        return export_pack(library, destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(
        os.environ.get("FIELDFORGE_DB", "~/.fieldforge/fieldforge.db")
    ).expanduser())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install", help="Add missing starter articles without overwriting your work")
    export = sub.add_parser("export", help="Create a starter JSON pack for an older reader")
    export.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = {"path": str(export_starter(args.destination))}
        else:
            result = install_starter(KnowledgeLibrary(args.database))
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
