"""Legacy preservation, independent learners, failure-safe switching and recovery."""

import hashlib
import json
import os
import sqlite3
from dataclasses import asdict, replace

import pytest

from fieldforge.app import FieldForgeApp
from fieldforge.core.recovery import create_verified_backup, restore_verified_copy
from fieldforge.knowledge.education import StudyStore, Work, check, lessons, worksheet


def question():
    lesson = next(item for item in lessons() if item.id == "number-count")
    return lesson, lesson.questions[0]


def test_all_650_existing_question_identities_are_unchanged():
    records = [(lesson.id, q.id, q.fingerprint) for lesson in lessons() for q in lesson.questions]
    assert len(records) == 650
    assert hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest() == (
        "b90a2414e70540662c4252bed664bed482b970b7b6f5f86d3ef6ab0cf5d107d8")


def test_upgrade_keeps_original_payload_bytes_and_new_saves_readable_by_earlier_apps(tmp_path):
    lesson, q = question()
    path = tmp_path / "old.db"
    fields = asdict(Work(response="8", reasoning="Five plus three", attempts=1, result="correct", revision=7))
    del fields["learner_id"]
    payload = json.dumps(fields, indent=3)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE education_work_v1 (lesson TEXT, question TEXT, fingerprint TEXT, "
                   "payload TEXT, revision INTEGER, PRIMARY KEY(lesson,question,fingerprint))")
        db.execute("INSERT INTO education_work_v1 VALUES (?,?,?,?,?)", (lesson.id, q.id, q.fingerprint, payload, 7))
    store = StudyStore(path)
    store.create_learner("New learner")
    assert store.read(lesson.id, q) == Work(**fields)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT payload FROM education_work_v1").fetchone()[0] == payload
    store.save(lesson.id, q, replace(store.read(lesson.id, q), reasoning="Three after five gives eight."))
    with sqlite3.connect(path) as db:
        assert "learner_id" not in json.loads(db.execute("SELECT payload FROM education_work_v1").fetchone()[0])


def test_answers_support_reviews_resume_and_conflicts_are_scoped_to_one_learner(tmp_path):
    lesson, q = question()
    original = StudyStore(tmp_path / "study.db")
    ada = original.create_learner("Ada")
    bo = original.create_learner("Bo")
    a, b = StudyStore(original.path, ada.id), StudyStore(original.path, bo.id)
    checked, _ = check(q, replace(a.read(lesson.id, q), response="8", hints=1, revealed=True))
    saved_a = a.save(lesson.id, q, replace(checked, reflection="explained it"))
    saved_b = b.save(lesson.id, q, replace(b.read(lesson.id, q), response="5", reasoning="Counted one row."))
    assert original.read(lesson.id, q) == Work()
    assert a.read(lesson.id, q) == saved_a and b.read(lesson.id, q) == saved_b
    assert saved_b.hints == 0 and not saved_b.revealed and saved_b.reflection == ""
    assert original.recent() is None and a.recent() == b.recent() == (lesson.id, 0)
    assert original.summary(lesson) == "Not started" and "1 checked" in a.summary(lesson)
    assert "0 checked" in b.summary(lesson)
    with pytest.raises(ValueError, match="different learner"):
        b.save(lesson.id, q, saved_a)
    stale = StudyStore(original.path, ada.id).read(lesson.id, q)
    a.save(lesson.id, q, replace(saved_a, reasoning="A changed explanation"))
    with pytest.raises(ValueError, match="another window"):
        a.save(lesson.id, q, stale)
    assert b.read(lesson.id, q) == saved_b
    assert a.read(lesson.id, replace(q, prompt="A revised question")).revision == 0


def test_remembered_selection_does_not_redirect_an_existing_store(tmp_path):
    original = StudyStore(tmp_path / "study.db")
    profile = original.create_learner("Second learner")
    other = StudyStore(original.path, profile.id)
    other.remember_learner()
    assert original.preferred_learner() == profile.id
    assert original.learner_id == "default" and StudyStore(original.path).learner_id == "default"
    with pytest.raises(AttributeError):
        original.learner_id = profile.id
    with pytest.raises(ValueError, match="no longer exists"):
        StudyStore(original.path, "f" * 32)


@pytest.mark.parametrize("name", ["", "   ", "x" * 41, "two\nlines", "hidden\x00name", 5])
def test_invalid_names_do_not_create_profiles(tmp_path, name):
    store = StudyStore(tmp_path / "study.db")
    with pytest.raises(ValueError, match="name"):
        store.create_learner(name)
    assert len(store.learners()) == 1


def test_names_are_distinct_normalized_and_rename_is_version_checked(tmp_path):
    store = StudyStore(tmp_path / "study.db")
    profile = store.create_learner("  Ada  ")
    assert profile.name == "Ada"
    for duplicate in ("ADA", "Ａｄａ"):
        with pytest.raises(ValueError, match="already used"):
            store.create_learner(duplicate)
    renamed = store.rename_learner(profile, "Ada practice")
    assert renamed.id == profile.id and renamed.revision == 2
    with pytest.raises(ValueError, match="another window"):
        store.rename_learner(profile, "Stale rename")
    original = store.learners()[0]
    store.rename_learner(original, "Earlier shared practice")
    reopened = StudyStore(store.path)
    assert len(reopened.learners()) == 2 and reopened.learners()[0].name == "Earlier shared practice"
    with pytest.raises(ValueError, match="already used"):
        store.rename_learner(renamed, "earlier shared practice")


def test_all_learners_survive_real_backup_and_preview_does_not_expose_names(tmp_path):
    app = FieldForgeApp(tmp_path / "app.db")
    original = StudyStore(app.db.path)
    lesson, q = question()
    saved_original = original.save(lesson.id, q, Work(response="Original private response"))
    profile = original.create_learner("Private learner name")
    other = StudyStore(original.path, profile.id)
    saved_other = other.save(lesson.id, q, replace(other.read(lesson.id, q), response="Second private response", hints=1))
    other.remember_learner()
    preview = create_verified_backup(app.db.path, tmp_path / "all.ffbackup")
    assert dict(preview.counts)["Education learners"] == 2
    assert dict(preview.counts)["Education practice records"] == 1
    assert dict(preview.counts)["Additional learner practice records"] == 1
    assert profile.name not in str(preview) and saved_other.response not in str(preview)
    restored = restore_verified_copy(preview, tmp_path / "restored.db", active_database=app.db.path)
    assert StudyStore(restored).read(lesson.id, q) == saved_original
    assert StudyStore(restored, profile.id).read(lesson.id, q) == saved_other
    assert StudyStore(restored).preferred_learner() == profile.id
    assert StudyStore(restored).learners() == original.learners()


@pytest.mark.parametrize("missing", ["education_work_v1", "education_learners_v1", "education_learner_work_v1", "education_preferences_v1"])
def test_partial_profile_schema_does_not_pass_backup_preview(tmp_path, missing):
    app = FieldForgeApp(tmp_path / "app.db")
    StudyStore(app.db.path)
    with sqlite3.connect(app.db.path) as db:
        db.execute(f"DROP TABLE {missing}")
    with pytest.raises(ValueError, match="incomplete education learner schema"):
        create_verified_backup(app.db.path, tmp_path / "partial.ffbackup")
    assert not (tmp_path / "partial.ffbackup").exists()


def test_wrong_owner_corruption_is_not_loaded_or_marked_as_recent(tmp_path):
    original = StudyStore(tmp_path / "study.db")
    profile = original.create_learner("A")
    store = StudyStore(original.path, profile.id)
    lesson, q = question()
    store.save(lesson.id, q, replace(store.read(lesson.id, q), response="A draft"))
    with sqlite3.connect(store.path) as db:
        raw = json.loads(db.execute("SELECT payload FROM education_learner_work_v1").fetchone()[0])
        raw["learner_id"] = "default"
        db.execute("UPDATE education_learner_work_v1 SET payload=?", (json.dumps(raw),))
    with pytest.raises(ValueError, match="unreadable"):
        store.read(lesson.id, q)
    with pytest.raises(ValueError, match="unreadable"):
        store.recent()
    assert original.recent() is None


def test_worksheet_labels_and_escapes_the_selected_learner_only():
    lesson, _q = question()
    page = worksheet(lesson, tuple(Work(response="Only this learner's answers") for _ in lesson.questions),
                     learner="<Alex> & family")
    assert "<strong>Learner:</strong> &lt;Alex&gt; &amp; family" in page
    assert "<Alex>" not in page


@pytest.fixture
def root():
    import tkinter as tk
    try:
        window = tk.Tk()
    except tk.TclError:
        if os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1":
            raise
        pytest.skip("Graphical CI requires a functioning display")
    errors = []
    window.report_callback_exception = lambda *args: errors.append(args)
    window.geometry("1000x700")
    yield window
    window.destroy()
    assert not errors


def test_gui_create_switch_rename_export_resume_and_reopen(root, tmp_path, monkeypatch):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.pack(fill="both", expand=True)
    tab.pages.select(tab.practice_page)
    tab.response.insert("1.0", "8")
    tab.reasoning.insert("1.0", "Original-only private method")
    tab.check_button.invoke()
    tab.hint_button.invoke()
    original = tab.work
    monkeypatch.setattr("fieldforge.ui.education.simpledialog.askstring", lambda *_a, **_kw: "Ada")
    tab.add_learner_button.invoke()
    profile = tab.current_learner
    assert profile.name == "Ada" and tab.work.revision == 0 and tab.work.hints == 0
    assert tab.response.get("1.0", "end-1c") == ""
    tab.response.insert("1.0", "Ada's first draft")
    tab.next.invoke()
    tab.response.insert("1.0", "0")
    tab.check_button.invoke()
    second = tab.work
    tab.learner_picker.current(0)
    tab.learner_picker.event_generate("<<ComboboxSelected>>")
    root.update()
    assert tab.store.learner_id == "default" and tab.work.revision == 0
    tab.resume()
    assert tab.question_index == 0 and tab.work == original
    assert tab.switch_learner(profile.id)
    tab.resume()
    assert tab.question_index == 1 and tab.work == second
    monkeypatch.setattr("fieldforge.ui.education.simpledialog.askstring", lambda *_a, **_kw: "<Ada> & learner")
    tab.rename_learner_button.invoke()
    assert tab.current_learner.id == profile.id and tab.work == second
    assert "<Ada> & learner" in tab.progress.get()
    output = tmp_path / "learner.html"
    monkeypatch.setattr("fieldforge.ui.education.filedialog.asksaveasfilename", lambda **_kw: str(output))
    tab.export()
    text = output.read_text(encoding="utf-8")
    assert "&lt;Ada&gt; &amp; learner" in text and "Ada&#x27;s first draft" in text
    assert "Original-only private method" not in text
    root.update()
    for widget in (tab.learner_picker, tab.add_learner_button, tab.rename_learner_button,
                   tab.check_button, tab.explained_button, tab.status_label):
        assert widget.winfo_ismapped()
        assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
        assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
    assert tab.can_close()
    tab.destroy()
    reopened = EducationTab(root, tmp_path / "study.db")
    assert reopened.current_learner.id == profile.id
    reopened.resume()
    assert reopened.work == second


def test_gui_failed_save_or_load_or_preference_write_keeps_learner_and_draft(root, tmp_path, monkeypatch):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.pack(fill="both", expand=True)
    profile = tab.store.create_learner("Other")
    tab.reload_learners()
    tab.response.insert("1.0", "Unsaved original work")
    save = tab.store.save
    def fail(*_a):
        raise sqlite3.OperationalError("simulated write failure")
    monkeypatch.setattr(tab.store, "save", fail)
    tab.learner_picker.current(1)
    tab.learner_picker.event_generate("<<ComboboxSelected>>")
    assert tab.store.learner_id == "default" and tab.learner_choice.get() == "Original learner"
    assert tab.response.get("1.0", "end-1c") == "Unsaved original work"
    assert "NOT SAVED" in tab.status.get()
    assert StudyStore(tab.store.path, profile.id).recent() is None
    monkeypatch.setattr(tab.store, "save", save)
    with monkeypatch.context() as patch:
        patch.setattr(StudyStore, "remember_learner", fail)
        assert not tab.switch_learner(profile.id)
    assert tab.store.learner_id == "default" and tab.store.preferred_learner() == "default"
    other = StudyStore(tab.store.path, profile.id)
    other.save(tab.lesson.id, tab.question, replace(other.read(tab.lesson.id, tab.question), response="Other's work"))
    with sqlite3.connect(tab.store.path) as db:
        db.execute("UPDATE education_learner_work_v1 SET payload='{}'")
    assert not tab.switch_learner(profile.id)
    assert tab.store.learner_id == "default" and "Unsaved original work" in tab.response.get("1.0", "end")


def test_gui_two_windows_stay_bound_and_conflicts_do_not_cross_profiles(root, tmp_path):
    from fieldforge.ui.education import EducationTab
    first = EducationTab(root, tmp_path / "study.db")
    profile = first.store.create_learner("Second")
    second = EducationTab(root, tmp_path / "study.db")
    first.response.insert("1.0", "First window original")
    assert first.save_current()
    second.response.insert("1.0", "Second window stale original")
    assert not second.switch_learner(profile.id)
    assert "another window" in second.status.get()
    assert first.switch_learner(profile.id)
    first.response.insert("1.0", "Second learner's answer")
    assert first.save_current()
    assert second.store.learner_id == "default"
    assert "Second window stale original" in second.response.get("1.0", "end")
    assert not second.save_current()
    assert StudyStore(first.store.path, profile.id).read(first.lesson.id, first.question).response == "Second learner's answer"
