"""Exercise real incident schema and templates, with fictional local records only."""

import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from fieldforge.core import emergency_actions as module
from fieldforge.core.emergency import EmergencyConflict, EmergencyStore, template
from fieldforge.core.emergency_actions import ActionStore, render_action_checklist
from fieldforge.scenarios.engine import available_scenarios


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "existing #test.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE unrelated_records(value TEXT)")
    return ActionStore(path)


def incident(store):
    return store.create("Fictional exercise", "power_outage")


def add(store, session, **changes):
    values = {"title": "Count labelled containers", "reason": "Record the count in the exercise sheet.",
              "responsible": "Team Cedar", **changes}
    return store.add_custom(session.id, expected_revision=session.revision, **values)


def update(store, task, **changes):
    return store.update_task(task.id, expected_revision=task.revision,
                             **{"status": task.status, "note": task.note, **changes})


@pytest.mark.parametrize("scenario", available_scenarios())
def test_original_templates_remain_exact_and_unassigned(store, scenario):
    session = store.create("Test", scenario)
    detail = store.detail(session.id)
    assert [(t.title, t.reason, t.priority) for t in detail.tasks] == [
        (row["title"], row["reason"], row["priority"]) for row in template(scenario)
    ]
    assert all(t.origin == "template" and not t.responsible for t in detail.tasks)
    assert not detail.done


def test_existing_v1_incidents_progress_notes_and_ids_survive_additive_upgrade(tmp_path):
    path = tmp_path / "older.db"
    with closing(sqlite3.connect(path)):
        pass
    old = EmergencyStore(path)
    session = old.create("Existing exercise", "evacuation")
    task = old.detail(session.id).tasks[0]
    old.update_task(task.id, expected_revision=task.revision, status="blocked", note="Keep exact note\n\n")
    before = old.detail(session.id)
    new = ActionStore(path)
    after = new.detail(session.id)
    assert before.incident == after.incident and before.log == after.log
    assert before.tasks[0].id == after.tasks[0].id
    assert after.tasks[0].note == "Keep exact note\n\n"
    with new.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM emergency_action_metadata").fetchone()[0] == 0
    assert new.detail(session.id) == ActionStore(path).detail(session.id)


def test_custom_task_is_pending_scoped_and_does_not_change_template_hash(store):
    first, other = incident(store), incident(store)
    original = store.detail(first.id)
    task = add(store, first)
    detail = store.detail(first.id)
    assert task.origin == "custom" and task.status == "pending" and task.note == ""
    assert task.position == len(original.tasks) + 1
    assert detail.incident.template_sha256 == original.incident.template_sha256
    assert detail.incident.revision == first.revision + 1
    assert len(store.detail(other.id).tasks) == len(original.tasks)
    assert [t.id for t in detail.tasks[:-1]] == [t.id for t in original.tasks]
    assert task == ActionStore(store.path).get_task(task.id)


def test_responsibility_and_custom_edits_persist_exact_notes(store):
    session = incident(store)
    task = add(store, session, responsible="  Équipe 森  ")
    assert task.responsible == "Équipe 森"
    changed = update(store, task, title="Corrected title", reason="  Exact context\r\n\n", priority="high",
                     responsible="Team Elm", status="blocked", note="Awaiting count\n\n")
    assert changed.revision == task.revision + 1 and changed.origin == "custom"
    assert changed.note == "Awaiting count\n\n" and changed.reason == "  Exact context\r\n\n"
    assert ActionStore(store.path).get_task(task.id) == changed
    assert update(store, changed, responsible="").responsible == ""


@pytest.mark.parametrize("changes", [{"title": ""}, {"title": "x"*201}, {"reason": " "},
    {"reason": "x"*4001}, {"priority": "urgent"}, {"priority": []}, {"responsible": "x"*121},
    {"responsible": "Name\nOther"}, {"responsible": "\x7f"}, {"responsible": None}, {"title": "\x00"}])
def test_invalid_custom_inputs_do_not_write(store, changes):
    session = incident(store)
    before = store.detail(session.id)
    with pytest.raises(ValueError):
        add(store, session, **changes)
    assert store.detail(session.id) == before


@pytest.mark.parametrize("changes", [{"title": "Changed"}, {"reason": "Changed"}, {"priority": "low"}])
def test_template_wording_and_priority_cannot_be_changed(store, changes):
    session = incident(store)
    task = store.detail(session.id).tasks[0]
    with pytest.raises(ValueError, match="frozen"):
        update(store, task, **changes)
    assert store.get_task(task.id) == task


def test_template_progress_and_assignment_can_change_without_altering_prompt(store):
    session = incident(store)
    task = store.detail(session.id).tasks[0]
    changed = update(store, task, responsible="Duty alias", status="in_progress", note="Private note")
    assert (changed.title, changed.reason, changed.priority) == (task.title, task.reason, task.priority)
    assert changed.origin == "template" and changed.responsible == "Duty alias"
    assert store.detail(session.id).incident.template_sha256 == session.template_sha256


def test_unchanged_save_is_noop_and_omitted_responsibility_is_preserved(store):
    task = add(store, incident(store))
    before = store.detail(task.session_id)
    assert update(store, task) == task
    assert store.detail(task.session_id) == before
    changed = update(store, task, status="done")
    assert changed.responsible == task.responsible


def test_older_api_status_update_keeps_new_metadata_and_stale_editor_is_rejected(store):
    task = add(store, incident(store))
    legacy = EmergencyStore(store.path)
    legacy.update_task(task.id, expected_revision=task.revision, status="in_progress", note="Legacy note")
    read = store.get_task(task.id)
    assert read.origin == "custom" and read.responsible == task.responsible
    with pytest.raises(EmergencyConflict):
        update(store, task, responsible="Stale alias")
    assert store.get_task(task.id) == read


def test_archived_incident_is_readonly_for_creation_and_responsibility(store):
    session = incident(store)
    task = add(store, session)
    latest = store.detail(session.id).incident
    archived = store.set_archived(session.id, expected_revision=latest.revision, archived=True)
    with pytest.raises(EmergencyConflict, match="archived"):
        add(store, archived)
    with pytest.raises(EmergencyConflict, match="archived"):
        update(store, task, responsible="Other alias")
    reopened = store.set_archived(session.id, expected_revision=archived.revision, archived=False)
    assert store.get_task(task.id) == task
    assert reopened.state == "active"


def test_stale_incident_cannot_add_or_archive_after_assignment_change(store):
    session = incident(store)
    task = store.detail(session.id).tasks[0]
    update(store, task, responsible="New shift")
    with pytest.raises(EmergencyConflict, match="incident changed"):
        add(store, session)
    with pytest.raises(EmergencyConflict):
        store.set_archived(session.id, expected_revision=session.revision, archived=True)


def test_concurrent_adds_have_one_winner_and_unique_positions(store):
    session = incident(store)
    def save(_):
        try:
            add(store, session)
            return "saved"
        except EmergencyConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(save, range(2))) == ["conflict", "saved"]
    positions = [t.position for t in store.detail(session.id).tasks]
    assert len(positions) == len(set(positions)) == 6


def test_concurrent_assignment_edits_do_not_clobber_each_other(store):
    task = add(store, incident(store))
    def save(alias):
        try:
            update(store, task, responsible=alias)
            return "saved"
        except EmergencyConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(save, ("Alpha", "Bravo"))) == ["conflict", "saved"]
    assert store.get_task(task.id).revision == task.revision + 1


@pytest.mark.parametrize("operation", ["add", "assignment", "details"])
def test_log_failure_rolls_back_task_metadata_and_revision(store, operation):
    session = incident(store)
    task = add(store, session)
    before = store.detail(session.id)
    with store.connect() as db:
        db.execute("CREATE TRIGGER deny_log BEFORE INSERT ON emergency_log "
                   "BEGIN SELECT RAISE(ABORT,'simulated error'); END")
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        if operation == "add":
            add(store, before.incident)
        else:
            update(store, task, **({"responsible": "Changed"} if operation == "assignment" else {"title": "Changed"}))
    assert store.detail(session.id) == before


def test_new_metadata_failure_rolls_back_task_insert(store):
    session = incident(store)
    before = store.detail(session.id)
    with store.connect() as db:
        db.execute("CREATE TRIGGER deny_meta BEFORE INSERT ON emergency_action_metadata "
                   "BEGIN SELECT RAISE(ABORT,'simulated error'); END")
    with pytest.raises(sqlite3.IntegrityError):
        add(store, session)
    assert store.detail(session.id) == before


def test_action_cap_rejected_without_truncation(store, monkeypatch):
    monkeypatch.setattr(module, "MAX_ACTIONS", 6)
    session = incident(store)
    add(store, session)
    with pytest.raises(ValueError, match="limit"):
        add(store, store.detail(session.id).incident)
    assert len(store.detail(session.id).tasks) == 6


def test_copy_marks_user_tasks_but_excludes_responsibility_notes_and_log(store):
    session = incident(store)
    task = add(store, session, responsible="PRIVATE_ASSIGNEE_SENTINEL")
    update(store, task, note="PRIVATE_TASK_NOTE_SENTINEL", status="blocked")
    store.add_note(session.id, "PRIVATE_JOURNAL_SENTINEL")
    report = render_action_checklist(store.detail(session.id))
    assert "[User-added] Count labelled containers" in report
    assert "[Scenario prompt]" in report and "does not cover user-added tasks" in report
    assert "PRIVATE_" not in report
    automatic = [row.message for row in store.detail(session.id).log if row.kind == "activity"]
    assert not any("PRIVATE_" in message for message in automatic)


@pytest.mark.parametrize("case", ["future", "unversioned", "missing", "columns"])
def test_invalid_metadata_schema_is_not_silently_rebuilt(store, case):
    with store.connect() as db:
        if case == "future":
            db.execute("UPDATE emergency_state SET value='99' WHERE key='action_metadata_schema'")
        elif case == "unversioned":
            db.execute("DELETE FROM emergency_state WHERE key='action_metadata_schema'")
        elif case == "missing":
            db.execute("DROP TABLE emergency_action_metadata")
        else:
            db.execute("ALTER TABLE emergency_action_metadata ADD COLUMN unknown TEXT")
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        ActionStore(store.path)
    assert store.path.read_bytes() == before


def test_no_automatic_incidents_or_personal_records_on_start(store):
    assert not store.browse()
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM emergency_action_metadata").fetchone()[0] == 0


def test_invalid_revisions_and_blocked_note_are_rejected(store):
    session = incident(store)
    task = store.detail(session.id).tasks[0]
    with pytest.raises(ValueError):
        store.add_custom(session.id, expected_revision=True, title="Test", reason="Test")
    with pytest.raises(ValueError, match="blocked"):
        update(store, task, status="blocked", note=" ")
    with pytest.raises(ValueError):
        store.get_task(True)
    with pytest.raises(ValueError):
        store.detail(session.id, log_limit=0)


def test_network_not_required_and_source_instructions_stay_text(store, monkeypatch, tmp_path):
    def blocked(*args, **kwargs):
        raise AssertionError("network request attempted")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, blocked)
    marker = tmp_path / "do-not-create"
    text = f"<script>open('{marker}','w')</script>"
    task = add(store, incident(store), reason=text)
    assert store.get_task(task.id).reason == text and not marker.exists()


def test_missing_database_path_does_not_create_file(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        ActionStore(path)
    assert not path.exists()


def test_changed_custom_task_cannot_silently_keep_done_status(store):
    task = add(store, incident(store))
    completed = update(store, task, status="done")
    with pytest.raises(ValueError, match="Task details changed"):
        update(store, completed, title="A different action")
    assert store.get_task(task.id) == completed
    changed = update(store, completed, title="A different action", status="pending")
    assert changed.status == "pending"
