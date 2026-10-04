"""Bundled study lessons, exact numeric feedback and private SQLite work records.

Practice records describe this app's checks and the learner's own reflection;
they are not evidence of mastery. Nothing in this module calls a model/network.
"""

from __future__ import annotations

import hashlib
import html
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from fieldforge.knowledge._learning_model import parse_number

NOTICE = ("Original AI-assisted teaching drafts; not independently educator-reviewed. "
          "Number and choice checks compare stated answers. Written explanations are self-reviewed. "
          "Saved practice is not a qualification or a measurement of mastery.")


@dataclass(frozen=True)
class Question:
    id: str
    prompt: str
    answer: str
    explanation: str
    unit: str = ""
    hints: tuple[str, ...] = ()
    mistakes: tuple[tuple[str, str], ...] = ()
    kind: str = "reflection"
    choices: tuple[tuple[str, str], ...] = ()
    passage: str = ""

    @property
    def fingerprint(self) -> str:
        fields = asdict(self)
        # Preserve fingerprints (and saved work) for every pre-literacy question.
        for name in ("choices", "passage"):
            if not fields[name]:
                del fields[name]
        raw = json.dumps(fields, ensure_ascii=True, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class StudyLesson:
    id: str
    title: str
    track: str
    goal: str
    materials: str
    paragraphs: tuple[str, ...]
    prerequisites: tuple[str, ...]
    questions: tuple[Question, ...]
    references: tuple[str, ...]
    diagram: dict | None = None
    guided: bool = False


@lru_cache(maxsize=1)
def lessons() -> tuple[StudyLesson, ...]:
    root = files("fieldforge.content").joinpath("education")
    source = json.loads(root.joinpath("lessons.json").read_text(encoding="utf-8"))
    result = []
    for filename in ("guided.json", "guided-literacy.json"):
        guided = json.loads(root.joinpath(filename).read_text(encoding="utf-8"))
        for item in guided["lessons"]:
            questions = tuple(Question(**{**q, "hints": tuple(q["hints"]),
                                          "mistakes": tuple(tuple(m) for m in q["mistakes"]),
                                          "choices": tuple(tuple(c) for c in q.get("choices", ()))})
                              for q in item["questions"])
            result.append(StudyLesson(**{**item, "questions": questions, "guided": True,
                                        "paragraphs": tuple(item["paragraphs"]),
                                        "prerequisites": tuple(item["prerequisites"]),
                                        "references": tuple(guided["references"])}))
    for item in source["lessons"]:
        result.append(StudyLesson(
            "library-" + item["id"], item["title"], item["track"].replace("-", " ").title(),
            item["goal"], item["materials"],
            tuple(item["lesson"]) + ("Adapt the activity\n" + item["adaptation"],),
            tuple("library-" + key for key in item["prerequisites"]),
            tuple(Question(f"q{index + 1}", prompt, answer, answer)
                  for index, (prompt, answer) in enumerate(zip(item["practice"], item["answers"]))),
            tuple(source["references"][key]["title"] + "\n" + source["references"][key]["url"]
                  for key in item["references"]),
        ))
    ids = {lesson.id for lesson in result}
    if len(ids) != len(result):
        raise ValueError("Duplicate study lesson IDs")
    for lesson in result:
        if not lesson.questions or any(key not in ids for key in lesson.prerequisites):
            raise ValueError("Missing study questions or prerequisites")
        if len({q.id for q in lesson.questions}) != len(lesson.questions):
            raise ValueError("Duplicate study question IDs")
        for q in lesson.questions:
            if q.kind not in {"number", "reflection", "choice"} or not q.prompt or not q.explanation:
                raise ValueError("Invalid study question")
            if q.kind == "number":
                parse_number(q.answer)
                for wrong, _feedback in q.mistakes:
                    if parse_number(wrong) == parse_number(q.answer):
                        raise ValueError("Correct answer listed as a misconception")
            if q.kind == "choice":
                keys = [key for key, _label in q.choices]
                if (not 2 <= len(keys) <= 5 or keys != list("ABCDE"[:len(keys)])
                        or q.answer not in keys or any(not label.strip() for _, label in q.choices)
                        or {key for key, _ in q.mistakes} != set(keys) - {q.answer}
                        or len(q.mistakes) != len(keys) - 1 or not q.passage.strip()):
                    raise ValueError("Choice questions need ordered options, source text and feedback for each distractor")
    return tuple(result)


@dataclass(frozen=True)
class Work:
    response: str = ""
    reasoning: str = ""
    hints: int = 0
    revealed: bool = False
    attempts: int = 0
    result: str = "draft"
    reflection: str = ""
    revision: int = 0
    updated: str = ""


def revise(work: Work, response: str, reasoning: str) -> Work:
    """Editing a previously checked answer clears its current result."""
    changed = (response, reasoning) != (work.response, work.reasoning)
    return replace(work, response=response, reasoning=reasoning,
                   result="draft" if changed else work.result,
                   reflection="" if changed else work.reflection)


def answer_matches(question: Question, response: str) -> bool:
    if question.kind == "number":
        return parse_number(response) == parse_number(question.answer)
    if question.kind == "choice":
        if response.strip().upper() not in dict(question.choices):
            raise ValueError("Choose one of the listed options before checking.")
        return response.strip().upper() == question.answer
    raise ValueError("Written explanations require self-review")


def check(question: Question, work: Work) -> tuple[Work, str]:
    if question.kind == "reflection":
        return work, "Compare your explanation with the worked answer, then record your reflection."
    try:
        correct = answer_matches(question, work.response)
    except ValueError as exc:
        return work, str(exc)
    updated = replace(work, attempts=work.attempts + 1,
                      result="correct" if correct else "retry", reflection="",
                      response=work.response.strip().upper() if question.kind == "choice" else work.response)
    if correct:
        support = "after a hint or answer was shown" if work.hints or work.revealed else "before hints or answer reveal"
        label = "Numeric answer" if question.kind == "number" else "Selected answer"
        return updated, f"{label} matches ({support}).\n\n{question.explanation}\n\nExplain your reasoning in your own words."
    for wrong, feedback in question.mistakes:
        matches = (parse_number(work.response) == parse_number(wrong) if question.kind == "number"
                   else work.response.strip().upper() == wrong)
        if matches:
            return updated, feedback + "\n\nRevise your answer, or ask for one hint."
    return updated, "This number does not match. Check what the question asks and its units. Try a sketch or one hint."


class StudyStore:
    """One work record per versioned question. Full database backups include it.

    Compare-and-swap prevents two open desktops from silently losing work.
    Changed question content gets its own record; old work remains in SQLite.
    """

    def __init__(self, database: str | Path):
        self.path = Path(database)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS education_work_v1 (
                lesson TEXT NOT NULL, question TEXT NOT NULL, fingerprint TEXT NOT NULL,
                payload TEXT NOT NULL, revision INTEGER NOT NULL,
                PRIMARY KEY (lesson, question, fingerprint))""")

    def read(self, lesson: str, question: Question) -> Work:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT payload, revision FROM education_work_v1 "
                             "WHERE lesson=? AND question=? AND fingerprint=?",
                             (lesson, question.id, question.fingerprint)).fetchone()
        if not row:
            return Work()
        try:
            work = Work(**json.loads(row[0]))
            self._validate(question, work)
            if work.revision != row[1]:
                raise ValueError("revision mismatch")
            return work
        except (TypeError, ValueError) as exc:
            raise ValueError("Saved education work is unreadable; restore a verified backup.") from exc

    @staticmethod
    def _validate(question: Question, work: Work) -> None:
        if any(not isinstance(value, str) or len(value) > 20000 or "\x00" in value
               for value in (work.response, work.reasoning, work.updated)):
            raise ValueError("Keep each response and explanation under 20,000 characters.")
        if (type(work.hints) is not int or not 0 <= work.hints <= len(question.hints)
                or type(work.revealed) is not bool
                or type(work.attempts) is not int or work.attempts < 0
                or type(work.revision) is not int or work.revision < 0
                or work.result not in {"draft", "correct", "retry"}
                or work.reflection not in {"", "needs practice", "explained it"}):
            raise ValueError("Invalid education work record")
        if work.result == "correct" and (
                question.kind == "reflection" or not answer_matches(question, work.response)):
            raise ValueError("A correct record needs a matching numeric or choice answer")
        if work.reflection and not work.revealed:
            raise ValueError("Read the worked answer before recording a self-review")

    def save(self, lesson: str, question: Question, work: Work) -> Work:
        self._validate(question, work)
        saved = replace(work, revision=work.revision + 1,
                        updated=datetime.now(timezone.utc).isoformat(timespec="microseconds"))
        key = (lesson, question.id, question.fingerprint)
        payload = json.dumps(asdict(saved), ensure_ascii=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            if work.revision == 0:
                try:
                    db.execute("INSERT INTO education_work_v1 VALUES (?,?,?,?,?)",
                               (*key, payload, saved.revision))
                except sqlite3.IntegrityError as exc:
                    raise ValueError("This exercise changed in another window. Export your work before reopening it.") from exc
            else:
                updated = db.execute("UPDATE education_work_v1 SET payload=?, revision=? "
                                     "WHERE lesson=? AND question=? AND fingerprint=? AND revision=?",
                                     (payload, saved.revision, *key, work.revision))
                if updated.rowcount != 1:
                    raise ValueError("This exercise changed in another window. Export your work before reopening it.")
        return saved

    def recent(self) -> tuple[str, int] | None:
        known = {(lesson.id, q.id, q.fingerprint): (lesson.id, index, q)
                 for lesson in lessons() for index, q in enumerate(lesson.questions)}
        matches = []
        with closing(sqlite3.connect(self.path)) as db:
            for lesson, question, fingerprint, payload in db.execute(
                    "SELECT lesson, question, fingerprint, payload FROM education_work_v1"):
                key = (lesson, question, fingerprint)
                if key in known:
                    item = known[key]
                    try:
                        work = Work(**json.loads(payload))
                        self._validate(item[2], work)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("Saved education work is unreadable; restore a verified backup.") from exc
                    matches.append((work.updated, item[0], item[1]))
        if not matches:
            return None
        _when, lesson, index = max(matches)
        return lesson, index

    def summary(self, lesson: StudyLesson) -> str:
        records = [self.read(lesson.id, q) for q in lesson.questions]
        checked = sum(w.result == "correct" for w in records)
        reviewed = sum(bool(w.reflection) for w in records)
        saved = sum(w.revision > 0 for w in records)
        if not saved:
            return "Not started"
        if any(w.result == "retry" or w.reflection == "needs practice" for w in records):
            return "Review needed"
        return f"{checked} checked · {reviewed} self-reviewed · {saved}/{len(records)} saved"


def worksheet(lesson: StudyLesson, records: tuple[Work, ...]) -> str:
    """Portable printable HTML; escaped user text, no scripts or remote assets."""
    escape = html.escape
    passages = {q.passage: index for index, q in enumerate(lesson.questions, 1) if q.passage}
    sections = [f"<h1>{escape(lesson.title)}</h1><p>{escape(NOTICE)}</p>",
                f"<h2>Goal</h2><p>{escape(lesson.goal)}</p>",
                f"<h2>Materials</h2><p>{escape(lesson.materials)}</p>"]
    sections.extend(f"<p class='block'>{escape(p)}</p>" for p in lesson.paragraphs
                    if p.partition("\n")[2] not in passages)
    if lesson.diagram:
        sections.append(f"<p>{escape(lesson.diagram['description'])}</p>")
    sections.append("<h2>Practice and saved work</h2>")
    for passage, index in passages.items():
        sections.append(f"<h3 id='passage-{index}'>Practice source text</h3><pre>{escape(passage)}</pre>")
    for i, (q, work) in enumerate(zip(lesson.questions, records), 1):
        support = f"Hints shown: {work.hints}; answer shown: {'yes' if work.revealed else 'no'}"
        options = "".join(f"<p>{escape(key)}. {escape(label)}</p>" for key, label in q.choices)
        source = f"<p><a href='#passage-{passages[q.passage]}'>Read the practice source text</a></p>" if q.passage else ""
        label = "Choose an option" if q.kind == "choice" else f"Answer units: {q.unit or 'written response'}"
        sections.append(f"<h3>{i}. {escape(q.prompt)}</h3>{source}{options}<p>{escape(label)}</p>"
                        f"<pre>{escape(work.response or '(not answered)')}</pre><pre>{escape(work.reasoning)}</pre>"
                        f"<p>{escape(work.result)}; self-review: {escape(work.reflection or 'not recorded')}. "
                        f"{support}. Answer checks: {work.attempts}.</p>")
    sections.append("<details><summary>Worked answers and comparison criteria (open to print)</summary>")
    sections.extend(f"<h3>{i}. {escape(q.answer)} {escape(q.unit)}</h3><p class='block'>{escape(q.explanation)}</p>"
                    for i, q in enumerate(lesson.questions, 1))
    sections.append("</details><h2>Background references</h2>")
    sections.extend(f"<p class='block'>{escape(ref)}</p>" for ref in lesson.references)
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>{escape(lesson.title)} — FieldForge worksheet</title>"
            "<style>body{font:18px/1.55 system-ui;max-width:850px;margin:2em auto;padding:0 1em;color:#152c3b}"
            "h1,h2{line-height:1.2}pre,.block{white-space:pre-wrap;overflow-wrap:anywhere}pre{font:inherit;background:#eef4f6;padding:1em}"
            "summary{cursor:pointer;font-weight:bold}h3{break-after:avoid}@media print{body{font-size:11pt;margin:0}}</style>"
            "<body>" + "\n".join(sections) + "<p>Original FieldForge study materials · CC BY-SA 4.0.</p></body></html>")
