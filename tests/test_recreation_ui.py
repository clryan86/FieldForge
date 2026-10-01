import gc
import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from fieldforge.recreation.games import NAMES, NumberGrid, SlidingTiles, ThreeInRow, solutions
from fieldforge.recreation.store import GameStore


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.recreation import RecreationTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; use a graphical test job")
    root.geometry("1120x820")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.recreation.messagebox.askyesno", lambda *args, **kwargs: False)
    panel = RecreationTab(root, tmp_path / "games.db")
    panel.pack(fill="both", expand=True)
    root.update()
    try:
        yield root, panel
    finally:
        root.destroy()
        panel._worker.shutdown(wait=True, cancel_futures=True)
        gc.collect()
    assert not errors


def wait(root, panel):
    deadline = time.monotonic() + 5
    while panel.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert not panel.busy


def load(root, panel, game):
    current = panel.store.load(game.kind)
    panel.store.save(game, expected_revision=current.revision)
    panel.kind.set(NAMES[game.kind])
    panel.load()
    root.update()


def test_initial_panel_does_not_auto_start_a_game(screen):
    _, panel = screen
    assert panel.current.game is None and not panel.busy
    with panel.store.connect() as db:
        assert db.execute("SELECT count(*) FROM recreation_games").fetchone()[0] == 0
    assert "No saved board" in panel.status.get()
    assert str(panel.undo_button["state"]) == "disabled"


def test_new_grid_button_generates_a_real_unique_puzzle_and_saves_it(screen):
    root, panel = screen
    panel.new_button.invoke()
    wait(root, panel)
    assert isinstance(panel.current.game, NumberGrid)
    assert len(solutions(panel.current.game.givens)) == 1
    assert len(panel.cells) == 81
    assert panel.store.load("number_grid") == panel.current
    assert "New game saved" in panel.status.get()


def test_grid_mouse_digit_keyboard_hint_clear_and_undo(screen):
    root, panel = screen
    game = NumberGrid.new(1)
    load(root, panel, game)
    index = game.givens.index(0)
    panel.cells[index].invoke()
    digit = solutions(game.givens)[0][index]
    panel.key(SimpleNamespace(keysym=str(digit)))
    assert panel.current.game.cells[index] == digit
    assert panel.store.load(game.kind).game.cells[index] == digit
    panel.clear_button.invoke()
    assert panel.current.game.cells[index] == 0
    panel.hint_button.invoke()
    assert panel.current.game.hints == 1
    panel.undo_button.invoke()
    assert panel.current.game.cells[index] == 0 and panel.current.game.hints == 0
    panel.key(SimpleNamespace(keysym="Right"))
    assert panel.selected == index + 1


def test_fixed_grid_clue_is_not_mutated(screen):
    root, panel = screen
    game = NumberGrid.new(3)
    load(root, panel, game)
    index = next(i for i, n in enumerate(game.givens) if n)
    panel.click(index)
    panel.put(0)
    assert panel.current.game == game
    assert "fixed clue" in panel.status.get().lower()


def test_sliding_click_key_solve_and_undo(screen):
    root, panel = screen
    game = SlidingTiles((*range(1, 15), 0, 15))
    load(root, panel, game)
    assert len(panel.cells) == 16
    panel.key(SimpleNamespace(keysym="Right"))
    assert panel.current.game.won and "complete" in panel.summary.get()
    panel.undo_button.invoke()
    assert panel.current.game == game
    panel.cells[15].invoke()
    assert panel.current.game.won


def test_three_in_row_includes_computer_reply_and_whole_turn_undo(screen):
    root, panel = screen
    load(root, panel, ThreeInRow())
    panel.cells[0].invoke()
    assert panel.current.game.cells.count("X") == 1
    assert panel.current.game.cells.count("O") == 1
    assert panel.store.load("three_in_row").game == panel.current.game
    panel.undo_button.invoke()
    assert panel.current.game == ThreeInRow()
    panel.key(SimpleNamespace(keysym="5"))
    assert panel.current.game.cells[4] == "X"


def test_new_game_replacement_needs_confirmation(screen, monkeypatch):
    root, panel = screen
    game = SlidingTiles.new(2)
    load(root, panel, game)
    panel.new_game()
    assert not panel.busy and panel.current.game == game
    monkeypatch.setattr("fieldforge.ui.recreation.messagebox.askyesno", lambda *args, **kwargs: True)
    panel.new_game()
    wait(root, panel)
    assert panel.current.game.moves == 0 and panel.current.revision == 2


def test_switching_games_resumes_independent_board_and_clears_undo(screen):
    root, panel = screen
    load(root, panel, ThreeInRow())
    panel.click(0)
    saved = panel.current
    load(root, panel, SlidingTiles.new(9))
    panel.kind.set(NAMES["three_in_row"])
    panel.load()
    assert panel.current == saved and not panel.undo_states


def test_stale_window_does_not_clobber_a_newer_game(screen):
    root, panel = screen
    load(root, panel, ThreeInRow())
    old = panel.current
    newer = GameStore(panel.store.path).save(ThreeInRow().play(4), expected_revision=old.revision)
    panel.click(0)
    assert panel.current == old
    assert "another window" in panel.status.get()
    assert panel.store.load("three_in_row") == newer
    panel.reload_button.invoke()
    assert panel.current == newer


def test_save_failure_leaves_previous_board_and_undo_intact(screen, monkeypatch):
    root, panel = screen
    load(root, panel, ThreeInRow())
    before = panel.current
    def fail(*args, **kwargs):
        raise OSError("simulated storage failure")
    monkeypatch.setattr(panel.store, "save", fail)
    panel.click(0)
    assert panel.current == before and not panel.undo_states
    assert "simulated storage failure" in panel.status.get()


def test_corrupt_saved_board_is_not_reset_by_loading_or_declining_new_game(screen):
    root, panel = screen
    load(root, panel, ThreeInRow())
    with panel.store.connect() as db:
        db.execute("UPDATE recreation_games SET checksum='bad'")
    panel.load()
    assert panel.current.game is None and panel.current.error
    before = panel.store.path.read_bytes()
    panel.new_game()
    assert not panel.busy and panel.store.path.read_bytes() == before


def test_cancelled_generation_cannot_replace_saved_board(screen, monkeypatch):
    root, panel = screen
    load(root, panel, SlidingTiles.new(1))
    previous = panel.current
    started, release = threading.Event(), threading.Event()
    def slow(*args):
        started.set()
        release.wait(2)
        return SlidingTiles.new(8)
    monkeypatch.setattr("fieldforge.ui.recreation._new_game", slow)
    monkeypatch.setattr("fieldforge.ui.recreation.messagebox.askyesno", lambda *args, **kwargs: True)
    panel.new_game()
    assert started.wait(1)
    panel.cancel_button.invoke()
    release.set()
    panel._worker.shutdown(wait=True)
    root.update()
    assert panel.current == previous and panel.store.load(previous.kind) == previous
    assert not panel.busy


def test_stale_callback_generation_is_discarded(screen):
    _, panel = screen
    future = Future()
    future.set_result(ThreeInRow())
    panel._generation = 2
    panel._poll(future, 1)
    assert panel.current.game is None


def test_creation_failure_is_reported_without_empty_success(screen, monkeypatch):
    root, panel = screen
    def fail(*args):
        raise ValueError("puzzle creation failed")
    monkeypatch.setattr("fieldforge.ui.recreation._new_game", fail)
    panel.new_game()
    wait(root, panel)
    assert panel.current.game is None and "puzzle creation failed" in panel.status.get()


def test_destroy_signals_generation_cancellation(screen, monkeypatch):
    root, panel = screen
    started, finished = threading.Event(), threading.Event()
    def wait_cancel(_kind, _clues, cancel):
        started.set()
        cancel.wait(2)
        finished.set()
        raise InterruptedError()
    monkeypatch.setattr("fieldforge.ui.recreation._new_game", wait_cancel)
    panel.new_game()
    assert started.wait(1)
    panel.destroy()
    assert finished.wait(1)
    root.update()
    assert panel._disposed


def test_generator_runs_off_ui_thread_and_save_runs_on_ui_thread(screen, monkeypatch):
    root, panel = screen
    from fieldforge.ui import recreation
    main = threading.get_ident()
    generated, saved = [], []
    original_generate, original_save = recreation._new_game, panel.store.save
    def generate(*args):
        generated.append(threading.get_ident())
        return original_generate(*args)
    def save(*args, **kwargs):
        saved.append(threading.get_ident())
        return original_save(*args, **kwargs)
    monkeypatch.setattr(recreation, "_new_game", generate)
    monkeypatch.setattr(panel.store, "save", save)
    panel.new_game()
    wait(root, panel)
    assert generated and main not in generated and saved == [main]


def test_small_window_keeps_board_and_controls_visible(screen):
    root, panel = screen
    root.geometry("1000x700")
    load(root, panel, NumberGrid.new(1))
    root.update()
    for widget in (panel.cells[-1], panel.undo_button, panel.hint_button, panel.footer):
        assert widget.winfo_rooty() + widget.winfo_height() <= panel.winfo_rooty() + panel.winfo_height()
        assert widget.winfo_rootx() + widget.winfo_width() <= panel.winfo_rootx() + panel.winfo_width()
