"""Offline, dependency-aware learning plans and private, revision-checked progress.

This is a proposed learning map, not a validated curriculum, disaster severity
scale, or certification of competence. Reading links are introductory only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

from fieldforge.knowledge import KnowledgeLibrary

CATALOG_VERSION = "2026-10-01.1"
STAGES = (
    "Plan and assess",
    "Stabilize essentials",
    "Restore food and skills",
    "Community infrastructure",
    "Industry and production",
    "Advanced knowledge",
)
STATUSES = ("not_started", "exploring", "practiced", "needs_review")
STATUS_LABELS = {
    "not_started": "Not started", "exploring": "Exploring",
    "practiced": "Practice recorded", "needs_review": "Needs review",
}
NOTICE = (
    "Proposed learning order, not a disaster timeline or an instruction to attempt hazardous work. "
    "Practice records are self-reported, not proof of competence. "
    "Related reading is introductory; no topic is a complete, specialist-reviewed curriculum."
)
FILTERS = ("all", "reading_available", "reading_missing", "guide_needed", "next")


@dataclass(frozen=True)
class LearningGoal:
    slug: str
    title: str
    stage: int
    domain: str
    objective: str
    exercise: str
    requirements: str
    prerequisites: tuple[str, ...] = ()
    articles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.slug):
            raise ValueError("goal slug must use lowercase words separated by hyphens")
        if type(self.stage) is not int or not 1 <= self.stage <= len(STAGES):
            raise ValueError("invalid learning stage")
        for name in ("title", "domain", "objective", "exercise", "requirements"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 4000 or "\x00" in value:
                raise ValueError(f"invalid goal {name}")
        for name in ("prerequisites", "articles"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(values) > 64:
                raise ValueError(f"{name} must be a tuple of at most 64 identifiers")
            if any(not isinstance(value, str) or not value or len(value) > 200 for value in values):
                raise ValueError(f"invalid {name}")
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {name}")


class LearningCatalog:
    """Validated DAG. Plans include each prerequisite once, in a stable order."""

    def __init__(self, goals: tuple[LearningGoal, ...]) -> None:
        if not goals or len(goals) > 500 or any(not isinstance(g, LearningGoal) for g in goals):
            raise ValueError("catalog must contain 1 to 500 LearningGoals")
        by_id = {goal.slug: goal for goal in goals}
        if len(by_id) != len(goals):
            raise ValueError("duplicate goal identifiers")
        for goal in goals:
            if any(dependency not in by_id for dependency in goal.prerequisites):
                raise ValueError(f"unknown prerequisite for {goal.slug}")
        # Iterative topological sort also handles long chains without recursion.
        remaining, ordered = set(by_id), []
        while remaining:
            available = sorted(
                (slug for slug in remaining if not remaining.intersection(by_id[slug].prerequisites)),
                key=lambda slug: (by_id[slug].stage, by_id[slug].title.casefold(), slug),
            )
            if not available:
                raise ValueError("learning prerequisites contain a cycle")
            ordered.append(available[0])
            remaining.remove(available[0])
        self.goals = tuple(by_id[slug] for slug in ordered)
        self.by_id = MappingProxyType(by_id)
        self._plans: dict[str, tuple[LearningGoal, ...]] = {}
        for goal in self.goals:
            ancestors = {goal.slug}
            for dependency in goal.prerequisites:
                ancestors.update(item.slug for item in self._plans[dependency])
            self._plans[goal.slug] = tuple(item for item in self.goals if item.slug in ancestors)

    def get(self, slug: str) -> LearningGoal:
        if not isinstance(slug, str) or slug not in self.by_id:
            raise ValueError("unknown learning goal")
        return self.by_id[slug]

    def plan(self, slug: str) -> tuple[LearningGoal, ...]:
        self.get(slug)
        return self._plans[slug]


def _goal(slug, title, stage, domain, objective, exercise, requirements, deps=(), articles=()):
    return LearningGoal(slug, title, stage, domain, objective, exercise, requirements,
                        deps, tuple("starter-v1-" + article for article in articles))


def default_catalog() -> LearningCatalog:
    """Twenty-four proposed learning goals, NOT twenty-four installed lessons."""
    return LearningCatalog((
        _goal("orientation", "Use and preserve offline references", 1, "Knowledge stewardship",
              "Distinguish installed articles, source links, missing guides, and recorded review dates.",
              "Open one article. Identify its origin and limits. Write one unanswered question.",
              "An installed article; no network needed. Never equate a checksum with expert review.",
              articles=("start",)),
        _goal("contacts", "Plan contacts and meeting places", 1, "Emergency planning",
              "Create a household contact and meeting card that includes access and transport needs.",
              "Practice with fictional details; ask each participant to explain the fallback plan.",
              "Household discussion and local official planning guidance; protect real contact details.",
              deps=("orientation",), articles=("contacts",)),
        _goal("measurement", "Measure and record consistent units", 1, "Mathematics",
              "Keep estimates separate from measurements and show units in every calculation.",
              "Measure a tabletop twice. Record length, width, units, and uncertainty.",
              "A ruler or measuring tape and paper. This exercise is not structural design.",
              articles=("measurement",)),
        _goal("inventory", "Count supplies and estimate runway", 1, "Logistics",
              "Produce a repeatable inventory with usable quantities and explicit consumption assumptions.",
              "Use fictional stock counts to calculate normal-use and higher-use scenarios.",
              "Consistent units and an inventory record. Calculations do not establish supply safety.",
              deps=("measurement",), articles=("inventory",)),
        _goal("water", "Plan safe water storage", 2, "Water and sanitation",
              "Separate storage planning from the assessment and treatment of contaminated sources.",
              "Draft a container/date/capacity log and identify questions for the water authority.",
              "Current official water guidance. No chemical dosing or unknown-source approval is taught here.",
              deps=("inventory", "contacts"), articles=("water-storage", "water-limits")),
        _goal("power-budget", "Budget essential energy", 2, "Energy",
              "List documented loads, duration, uncertainty, and limitations of runtime estimates.",
              "Calculate a fictional lamp budget and locate the generator carbon-monoxide warnings.",
              "Equipment manuals and qualified help for installation; this is not a wiring course.",
              deps=("measurement", "inventory"), articles=("power-budget", "generator")),
        _goal("shelter", "Prepare shelter and outdoor equipment", 2, "Shelter",
              "Identify equipment systems and the information still needed for a specific trip or site.",
              "Create a packing record using the introductory checklist; flag unfamiliar equipment.",
              "Trip-specific guidance and instruction. This is not shelter construction or rescue training.",
              deps=("contacts",), articles=("packing",)),
        _goal("records", "Protect records and recovery copies", 2, "Knowledge stewardship",
              "Plan how essential records will be recovered without assuming one device will survive.",
              "List records, storage locations, privacy needs, and a proposed recovery-test procedure.",
              "A verified backup procedure. A dedicated preservation guide still needs to be added.",
              deps=("orientation", "inventory")),
        _goal("soil", "Learn soil and compost observations", 3, "Agriculture",
              "Build a dated observation log before moving on to broader food-production planning.",
              "Draft a compost ingredient and observation record using the introductory article.",
              "Local agriculture guidance; a backyard overview is not a complete soil or food-safety course.",
              deps=("water", "measurement"), articles=("compost",)),
        _goal("crops", "Plan seasonal food production", 3, "Agriculture",
              "Identify region, crop, soil, water, storage, and labor questions for a future growing plan.",
              "Make a list of locally specific information and training to obtain before selecting crops.",
              "Regional crop calendars, verified cultivation guides, and experienced instruction are missing.",
              deps=("soil", "inventory")),
        _goal("maintenance", "Preserve tools and equipment records", 3, "Tools and vehicles",
              "Match service information to an exact asset and keep observations separate from diagnoses.",
              "Create an equipment card for a harmless hand tool; record its manual and storage location.",
              "Correct manufacturer documents and qualified inspection for safety-critical equipment.",
              deps=("inventory",), articles=("maintenance",)),
        _goal("teaching", "Teach and document a practical skill", 3, "Education",
              "Turn a small observable task into a repeatable practice and teach-back exercise.",
              "Write a lesson for counting and measuring containers, then test the explanation with a learner.",
              "Safe practice materials. Self-reported practice is not a professional qualification.",
              deps=("measurement", "orientation"), articles=("teaching",)),
        _goal("sanitation", "Study community sanitation planning", 4, "Public health",
              "Map questions about water, waste, access, maintenance, and public-health oversight.",
              "Create an information-gap list, not a waste-treatment design or field procedure.",
              "Reviewed sanitation manuals and qualified public-health/site assessment are needed.",
              deps=("water", "records")),
        _goal("construction", "Study structures and building systems", 4, "Construction",
              "Organize the drawings, material specifications, site data, and professional review a project needs.",
              "Draft a documentation checklist for a hypothetical building; do not size structural members.",
              "Reviewed construction curricula, local standards, and qualified engineering oversight are needed.",
              deps=("measurement", "maintenance", "shelter")),
        _goal("energy-systems", "Study community energy systems", 4, "Energy",
              "Separate load documentation from the design, installation, and maintenance of a power system.",
              "List unknown loads, operating conditions, and questions for an electrical professional.",
              "Reviewed electrical references and qualified installation/testing are needed; no wiring guide included.",
              deps=("power-budget", "maintenance")),
        _goal("communications", "Study resilient communications", 4, "Communications",
              "Define communication needs and identify equipment, power, coverage, and training gaps.",
              "Write a fictional communications requirement sheet without assuming any network is available.",
              "Equipment-specific guides and applicable operating requirements still need verified coverage.",
              deps=("contacts", "power-budget", "records")),
        _goal("materials", "Study materials and material quality", 5, "Materials science",
              "Identify where traceability, specification, testing, and qualified process control are necessary.",
              "Draft a material identification and source record; mark every unknown property as unknown.",
              "Reviewed materials science instruction and laboratory/workshop safety are needed.",
              deps=("construction", "maintenance")),
        _goal("manufacturing", "Study manufacturing and quality control", 5, "Production",
              "Map the drawings, tools, tolerances, inspection records, and training required for a production task.",
              "Create a quality-record template for a paper model, not for a safety-critical component.",
              "Manufacturing courses, safe equipment training, and verified inspection methods are needed.",
              deps=("materials", "measurement")),
        _goal("transport", "Study vehicles and transport logistics", 5, "Transport",
              "Keep fleet logistics, maintenance documentation, and qualified repair decisions distinct.",
              "Draft a fictional fleet record and list missing exact-model manuals and inspections.",
              "Manufacturer repair information and qualified vehicle/heavy-equipment training are not bundled.",
              deps=("maintenance", "energy-systems", "records")),
        _goal("instrumentation", "Study measurement instruments and controls", 5, "Instrumentation",
              "Map instrument documentation, calibration, uncertainty, and testing prerequisites.",
              "Design a record template for readings and calibration evidence; do not build a control circuit.",
              "Reviewed instrumentation, electronics, and safe testing curricula are needed.",
              deps=("measurement", "energy-systems")),
        _goal("scientific-method", "Study reproducible scientific work", 6, "Science",
              "Plan how questions, methods, observations, uncertainty, and review will be documented.",
              "Outline a harmless measurement study and identify what another learner needs to repeat it.",
              "Reviewed science curricula and subject-specific supervision are still needed.",
              deps=("teaching", "measurement", "records")),
        _goal("health-systems", "Study health-system knowledge needs", 6, "Medicine and public health",
              "Inventory the professional references, facilities, supply systems, and expertise a care system needs.",
              "Write a library-acquisition checklist, not a diagnosis, treatment, or surgical procedure.",
              "Licensed clinicians, validated clinical references, and formal training are needed; no medical corpus included.",
              deps=("sanitation", "teaching", "records")),
        _goal("computing", "Study computing and digital preservation", 6, "Computing",
              "Map dependencies for maintaining hardware, software, documentation, and recoverable data.",
              "Draft an asset/dependency diagram and identify missing manuals, source code, and recovery tests.",
              "Reviewed computing and electronics curricula are needed; no local AI model is installed by this map.",
              deps=("instrumentation", "communications", "teaching")),
        _goal("space-earth", "Study Earth observation and space science", 6, "Earth and space",
              "Organize prerequisite science, computation, measurement, and reference collections.",
              "Create a reading-acquisition list and a harmless sky-observation journal template.",
              "Reviewed astronomy/Earth-science courses and instrument-specific safety instruction are needed.",
              deps=("scientific-method", "computing")),
    ))


@dataclass(frozen=True)
class LearningProgress:
    status: str = "not_started"
    note: str = ""
    revision: int = 0
    updated_at: str = ""


@dataclass(frozen=True)
class GoalView:
    goal: LearningGoal
    progress: LearningProgress
    installed_articles: tuple[tuple[str, str], ...]
    pending_prerequisites: tuple[str, ...]

    @property
    def reading_state(self) -> str:
        if self.installed_articles:
            return "Intro available"
        return "Intro not installed" if self.goal.articles else "Guide needed"

    @property
    def next_to_explore(self) -> bool:
        return bool(self.installed_articles) and not self.pending_prerequisites and (
            self.progress.status in {"not_started", "exploring", "needs_review"}
        )


class ProgressConflict(ValueError):
    """A newer record exists; the caller must not overwrite it silently."""


class PathwayStore:
    """Uses the existing library database. Never inserts articles or imports a model."""

    def __init__(self, library: KnowledgeLibrary, catalog: LearningCatalog | None = None) -> None:
        self.library = library
        self.catalog = default_catalog() if catalog is None else catalog
        with library.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute(
                "SELECT value FROM knowledge_state WHERE key='pathways_schema'"
            ).fetchone()
            if version is not None and version[0] != "1":
                raise ValueError("unsupported pathway progress schema; use a compatible FieldForge version")
            db.execute("""CREATE TABLE IF NOT EXISTS pathway_progress (
                slug TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN
                    ('not_started','exploring','practiced','needs_review')),
                note TEXT NOT NULL DEFAULT '' CHECK(length(note) <= 20000),
                revision INTEGER NOT NULL CHECK(revision > 0),
                updated_at TEXT NOT NULL
            )""")
            db.execute("INSERT OR IGNORE INTO knowledge_state VALUES('pathways_schema','1')")

    @staticmethod
    def _progress(row) -> LearningProgress:
        return LearningProgress() if row is None else LearningProgress(
            row["status"], row["note"], row["revision"], row["updated_at"]
        )

    def progress(self, slug: str) -> LearningProgress:
        self.catalog.get(slug)
        with self.library.connect() as db:
            row = db.execute("SELECT * FROM pathway_progress WHERE slug=?", (slug,)).fetchone()
        return self._progress(row)

    def save(self, slug: str, *, status: str, note: str, expected_revision: int) -> LearningProgress:
        self.catalog.get(slug)
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError("invalid learning status")
        if not isinstance(note, str) or len(note) > 20000 or "\x00" in note:
            raise ValueError("private note must be at most 20000 characters, without NUL characters")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        with self.library.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._progress(db.execute(
                "SELECT * FROM pathway_progress WHERE slug=?", (slug,)
            ).fetchone())
            if old.revision != expected_revision:
                raise ProgressConflict(
                    "This progress was changed in another window. Your edits are still visible. "
                    "Copy them before using Reload saved progress, then reconcile and save."
                )
            if (old.status, old.note) == (status, note):
                return old
            updated = LearningProgress(status, note, old.revision + 1,
                                       datetime.now(timezone.utc).isoformat(timespec="seconds"))
            db.execute(
                "INSERT INTO pathway_progress VALUES(?,?,?,?,?) ON CONFLICT(slug) DO UPDATE SET "
                "status=excluded.status,note=excluded.note,revision=excluded.revision,"
                "updated_at=excluded.updated_at",
                (slug, updated.status, updated.note, updated.revision, updated.updated_at),
            )
            return updated

    def views(self, *, query: str = "", stage: int | None = None,
              content: str = "all") -> tuple[GoalView, ...]:
        if not isinstance(query, str) or len(query) > 200:
            raise ValueError("search must be at most 200 characters")
        if stage is not None and (type(stage) is not int or not 1 <= stage <= len(STAGES)):
            raise ValueError("invalid learning stage")
        if content not in FILTERS:
            raise ValueError("invalid content filter")
        with self.library.connect() as db:
            db.execute("BEGIN")
            progress = {row["slug"]: self._progress(row) for row in db.execute(
                "SELECT * FROM pathway_progress"
            )}
            references = sorted({article for goal in self.catalog.goals for article in goal.articles})
            titles = {}
            # Batched exact matches; don't load or scan an entire large article corpus.
            for start in range(0, len(references), 400):
                batch = references[start:start + 400]
                titles.update(dict(db.execute(
                    f"SELECT slug,title FROM knowledge_articles WHERE slug IN ({','.join('?' for _ in batch)})",
                    batch,
                )))
        result = []
        for goal in self.catalog.goals:
            if stage is not None and goal.stage != stage:
                continue
            haystack = " ".join((goal.title, goal.domain, goal.objective)).casefold()
            if not all(word in haystack for word in query.casefold().split()):
                continue
            current = progress.get(goal.slug, LearningProgress())
            pending = tuple(item.slug for item in self.catalog.plan(goal.slug) if item.slug != goal.slug
                            and progress.get(item.slug, LearningProgress()).status != "practiced")
            view = GoalView(goal, current, tuple((slug, titles[slug]) for slug in goal.articles
                                                if slug in titles), pending)
            if content == "reading_available" and not view.installed_articles:
                continue
            if content == "reading_missing" and (not goal.articles or view.installed_articles):
                continue
            if content == "guide_needed" and goal.articles:
                continue
            if content == "next" and not view.next_to_explore:
                continue
            result.append(view)
        return tuple(result)
