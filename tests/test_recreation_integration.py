"""Full-checkout verification; local standalone tests do not substitute for these."""

import gc

import pytest

from fieldforge.recreation.games import NAMES, NumberGrid, SlidingTiles, ThreeInRow
from fieldforge.recreation.store import GameStore


def test_complete_snapshot_restores_all_three_games_without_touching_other_records(tmp_path):
    from fieldforge.app import FieldForgeApp
    from fieldforge.core.models import HouseholdMember
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy
    app = FieldForgeApp(tmp_path / "app.db")
    app.add_member(HouseholdMember("Fictional backup example"))
    store = GameStore(app.db.path)
    saved = [store.save(game, expected_revision=0) for game in
             (NumberGrid.new(4), SlidingTiles.new(4), ThreeInRow().play(0))]
    backup = create_verified_backup(app.db.path, tmp_path / "complete.ffbackup")
    restored = restore_verified_copy(backup, tmp_path / "restored.db", active_database=app.db.path)
    target = GameStore(restored)
    assert [target.load(item.kind) for item in saved] == saved
    assert FieldForgeApp(restored).members()[0].name == "Fictional backup example"
    assert app.members()[0].name == "Fictional backup example"


def test_game_state_is_separate_from_knowledge_packs_and_search(tmp_path):
    from fieldforge.app import FieldForgeApp
    from fieldforge.knowledge.assistant import ReferenceAssistant
    from fieldforge.knowledge.packs import export_pack
    app = FieldForgeApp(tmp_path / "app.db")
    GameStore(app.db.path).save(ThreeInRow().play(0), expected_revision=0)
    pack = export_pack(app.knowledge, tmp_path / "knowledge.json", include_personal=True)
    assert "three_in_row" not in pack.read_text(encoding="utf-8")
    assert not ReferenceAssistant(app.db.path).ask("three_in_row").references
    assert app.knowledge.count() == 0 and not app.members()


def test_actual_desktop_has_playable_recreation_and_normal_close_retains_moves(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from tkinter import ttk
    from fieldforge.ui import desktop
    from fieldforge.ui.recreation import RecreationTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; graphical CI requires it")
    path = tmp_path / "desktop.db"
    monkeypatch.setenv("FIELDFORGE_DB", str(path))
    monkeypatch.setattr(tk, "Tk", lambda: root)
    errors, completed, workers = [], [], []
    root.report_callback_exception = lambda *args: errors.append(args)

    def children(widget):
        yield widget
        for child in widget.winfo_children():
            yield from children(child)

    def play():
        root.after_cancel(timer)
        try:
            panel = next(widget for widget in children(root) if isinstance(widget, RecreationTab))
            notebook = panel.master
            assert isinstance(notebook, ttk.Notebook)
            assert notebook.tab(panel, "text") == "Recreation"
            notebook.select(panel)
            panel.store.save(ThreeInRow(), expected_revision=0)
            panel.kind.set(NAMES["three_in_row"])
            panel.load()
            panel.cells[0].invoke()
            assert panel.current.game.cells.count("X") == panel.current.game.cells.count("O") == 1
            completed.append(True)
            workers.extend(w._worker for w in children(root) if hasattr(w, "_worker"))
            root.tk.call(root.protocol("WM_DELETE_WINDOW"))
        except Exception as exc:
            errors.append(exc)
            root.destroy()

    root.after(150, play)
    timer = root.after(7000, root.destroy)
    desktop.run()
    for worker in workers:
        worker.shutdown(wait=True, cancel_futures=True)
    assert completed and not errors
    assert GameStore(path).load("three_in_row").game == ThreeInRow().play(0)
    gc.collect()
