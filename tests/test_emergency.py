import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from fieldforge.core import emergency
from fieldforge.core.emergency import EmergencyConflict, EmergencyStore, render_checklist, template
from fieldforge.core.models import EmergencyAction, Priority
from fieldforge.scenarios.engine import available_scenarios


def existing_database(path):
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE unrelated_private(value TEXT)")
        db.execute("INSERT INTO unrelated_private VALUES('PREEXISTING_PRIVATE_RECORD')")
        db.commit()
    return EmergencyStore(path)


@pytest.fixture
def store(tmp_path):
    return existing_database(tmp_path / "emergency #1.db")


def incident(store, title="Fictional outage exercise"):
    return store.create(title, "power_outage")


def test_opening_does_not_start_an_incident_or_alter_old_records(store):
    assert not store.browse()
    EmergencyStore(store.path)
    with store.connect() as db:
        assert db.execute("SELECT value FROM unrelated_private").fetchone()[0] == "PREEXISTING_PRIVATE_RECORD"
        assert db.execute("SELECT COUNT(*) FROM emergency_tasks").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM emergency_log").fetchone()[0] == 0


@pytest.mark.parametrize("scenario", available_scenarios())
def test_all_existing_templates_create_separate_pending_checklists(store, scenario):
    record = store.create("Fictional drill", scenario)
    detail = store.detail(record.id)
    assert record.mode == "exercise" and record.state == "active"
    assert len(record.template_sha256) == 64
    assert record.created_at.endswith("+00:00")
    assert detail.done == 0 and all(task.status == "pending" for task in detail.tasks)
    assert [task.title for task in detail.tasks] == [row["title"] for row in template(scenario)]
    assert detail.tasks[0].priority == "critical"
    second = store.create("Another drill", scenario, mode="incident")
    assert second.id != record.id and second.mode == "incident"


def test_template_preview_has_no_database_side_effects(store):
    before = store.path.read_bytes()
    assert template("power_outage")
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("title,scenario,mode", [
    ("", "power_outage", "exercise"), ("x"*201, "power_outage", "exercise"),
    ("x\x00", "power_outage", "exercise"), (None, "power_outage", "exercise"),
    ("Example", "unknown", "exercise"), ("Example", "power_outage", "automatic"),
])
def test_invalid_creation_does_not_partially_write(store, title, scenario, mode):
    with pytest.raises(ValueError):
        store.create(title, scenario, mode=mode)
    assert not store.browse()


def test_saved_template_survives_later_source_changes(store, monkeypatch):
    first = incident(store)
    original = store.detail(first.id)
    monkeypatch.setattr(emergency, "scenario_actions", lambda _: [EmergencyAction("New prompt", Priority.HIGH, "Different reason")])
    second = incident(store)
    assert store.detail(first.id) == original
    assert store.detail(second.id).tasks[0].title == "New prompt"
    assert first.template_sha256 != second.template_sha256


def test_progress_exact_note_and_log_survive_reopen(store):
    record = incident(store)
    task = store.detail(record.id).tasks[0]
    saved = store.update_task(task.id, expected_revision=task.revision, status="done", note="  Café — 记录\r\n\n")
    reopened = EmergencyStore(store.path).detail(record.id)
    assert reopened.done == 1 and reopened.tasks[0] == saved
    assert reopened.incident.revision == 2
    assert reopened.log_count == 2 and "Café" not in reopened.log[0].message
    assert "Task note changed" in reopened.log[0].message


def test_noop_updates_do_not_add_log_or_revisions(store):
    record = incident(store)
    before = store.detail(record.id)
    task = before.tasks[0]
    assert store.update_task(task.id, expected_revision=1, status="pending", note="") == task
    assert store.set_archived(record.id, expected_revision=1, archived=False) == record
    assert store.detail(record.id) == before


@pytest.mark.parametrize("status,note,revision", [
    ("unknown", "", 1), ("done", "x\x00", 1), ("pending", "x"*4001, 1),
    ("blocked", "  ", 1), ("done", "ok", True), ("done", "ok", 0),
])
def test_invalid_action_edits_do_not_write(store, status, note, revision):
    record = incident(store)
    before = store.detail(record.id)
    with pytest.raises(ValueError):
        store.update_task(before.tasks[0].id, expected_revision=revision, status=status, note=note)
    assert store.detail(record.id) == before


def test_stale_editor_preserves_newer_notes(store):
    record = incident(store)
    old = store.detail(record.id).tasks[0]
    new = store.update_task(old.id, expected_revision=old.revision, status="blocked", note="Waiting for appropriate help")
    with pytest.raises(EmergencyConflict):
        store.update_task(old.id, expected_revision=old.revision, status="done", note="Stale note")
    assert store.detail(record.id).tasks[0] == new


def test_simultaneous_task_updates_have_one_winner(store):
    task = store.detail(incident(store).id).tasks[0]
    def edit(note):
        try:
            store.update_task(task.id, expected_revision=1, status="in_progress", note=note)
            return "saved"
        except EmergencyConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as worker:
        assert sorted(worker.map(edit, ("A", "B"))) == ["conflict", "saved"]


def test_independent_sessions_never_share_progress_or_notes(store):
    first, second = incident(store), incident(store)
    task = store.detail(first.id).tasks[0]
    store.update_task(task.id, expected_revision=1, status="done", note="First only")
    store.add_note(first.id, "PRIVATE_FIRST_SESSION")
    assert store.detail(second.id).done == 0
    assert store.detail(second.id).log_count == 1
    assert "PRIVATE_FIRST_SESSION" not in str(store.detail(second.id))


def test_archive_blocks_writes_and_reopen_preserves_progress(store):
    record = incident(store)
    task = store.detail(record.id).tasks[0]
    store.update_task(task.id, expected_revision=1, status="done", note="Done for exercise")
    with pytest.raises(EmergencyConflict):
        store.set_archived(record.id, expected_revision=record.revision, archived=True)
    latest = store.detail(record.id)
    archived = store.set_archived(record.id, expected_revision=latest.incident.revision, archived=True)
    assert not store.browse() and store.browse(archived=True)[0].state == "archived"
    with pytest.raises(EmergencyConflict, match="archived"):
        store.add_note(record.id, "Not allowed while archived")
    with pytest.raises(EmergencyConflict, match="archived"):
        store.update_task(task.id, expected_revision=2, status="pending", note="Old editor")
    reopened = store.set_archived(record.id, expected_revision=archived.revision, archived=False)
    assert reopened.state == "active" and store.detail(record.id).done == 1
    assert store.detail(record.id).tasks[0].note == "Done for exercise"


def test_append_notes_preserve_exact_text_and_display_bounded_latest_records(store):
    record = incident(store)
    for i in range(12):
        store.add_note(record.id, f" Log note {i} — 文本\n\n")
    detail = store.detail(record.id, log_limit=5)
    assert detail.log_count == 13 and len(detail.log) == 5
    assert detail.log[0].message == " Log note 11 — 文本\n\n"
    assert detail.incident.revision == 13


@pytest.mark.parametrize("message", ["", " ", "x"*4001, "x\x00", None])
def test_invalid_log_notes_do_not_write(store, message):
    record = incident(store)
    with pytest.raises(ValueError):
        store.add_note(record.id, message)
    assert store.detail(record.id).log_count == 1


@pytest.mark.parametrize("operation", ["create", "task", "note", "archive"])
def test_log_failure_rolls_back_corresponding_mutation(store, operation):
    record = incident(store)
    before = store.detail(record.id)
    with store.connect() as db:
        db.execute("CREATE TRIGGER reject_log BEFORE INSERT ON emergency_log BEGIN SELECT RAISE(ABORT,'Simulated failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="Simulated"):
        if operation == "create":
            incident(store)
        elif operation == "task":
            store.update_task(before.tasks[0].id, expected_revision=1, status="done", note="Keep atomic")
        elif operation == "note":
            store.add_note(record.id, "Keep atomic")
        else:
            store.set_archived(record.id, expected_revision=1, archived=True)
    assert store.detail(record.id) == before
    assert len(store.browse()) == 1


def test_unknown_future_version_rejected_without_rewriting_schema(store):
    incident(store)
    with store.connect() as db:
        db.execute("UPDATE emergency_state SET value='99' WHERE key='schema_version'")
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="unsupported"):
        EmergencyStore(store.path)
    assert store.path.read_bytes() == before


def test_partial_unversioned_schema_rejected_without_claiming_migration(tmp_path):
    path = tmp_path / "partial.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE emergency_tasks(x)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="unversioned"):
        EmergencyStore(path)
    assert path.read_bytes() == before


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        EmergencyStore(path)
    assert not path.exists()


def test_copy_summary_excludes_private_notes_and_log(store):
    record = incident(store)
    task = store.detail(record.id).tasks[0]
    store.update_task(task.id, expected_revision=1, status="done", note="PRIVATE_TASK")
    store.add_note(record.id, "PRIVATE_LOG")
    output = render_checklist(store.detail(record.id))
    assert "PRIVATE_TASK" not in output and "PRIVATE_LOG" not in output
    assert record.title in output and task.title in output
    assert "not a recovery backup" in output and "self-reported" in output.lower()


def test_pages_are_stable_and_do_not_reset_progress(store):
    for i in range(6):
        incident(store, str(i))
    assert [r.title for r in store.browse(limit=3)] == ["5", "4", "3"]
    assert [r.title for r in store.browse(offset=3, limit=3)] == ["2", "1", "0"]


@pytest.mark.parametrize("arguments", [{"limit": True}, {"offset": -1}, {"archived": 1}, {"limit": 101}])
def test_bad_pagination_rejected(store, arguments):
    with pytest.raises(ValueError):
        store.browse(**arguments)


def test_literal_text_and_no_network(store, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unexpected network operation")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, blocked)
    record = incident(store, "' OR 1=1 --")
    store.add_note(record.id, "<script>Not executable</script>")
    assert store.detail(record.id).log[0].message.startswith("<script>")
    assert json.loads(json.dumps(store.detail(record.id).incident.title)) == record.title
