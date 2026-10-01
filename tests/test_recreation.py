import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from fieldforge.recreation.games import (
    NumberGrid,
    SlidingTiles,
    ThreeInRow,
    conflicts,
    decode_game,
    encode_game,
    solutions,
)
from fieldforge.recreation.store import GameConflict, GameStore, SavedGame


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("clues", [32, 38])
def test_generated_grids_have_one_solution_and_no_fixed_clue_conflicts(seed, clues):
    game = NumberGrid.new(seed, clues=clues)
    assert not conflicts(game.givens)
    assert clues <= sum(v != 0 for v in game.givens) <= 45
    assert len(solutions(game.givens)) == 1
    assert game.cells == game.givens and not game.won
    assert NumberGrid.new(seed, clues=clues) == game


def test_grid_edit_clear_and_hint_preserve_original_and_counts():
    original = NumberGrid.new(5)
    index = original.givens.index(0)
    solution = solutions(original.givens)[0]
    changed = original.put(index, solution[index])
    assert original.cells[index] == 0
    assert changed.cells[index] == solution[index] and changed.moves == 1
    assert changed.put(index, solution[index]) == changed
    cleared = changed.put(index, 0)
    assert cleared.cells[index] == 0 and cleared.moves == 2
    hinted = cleared.hint(index)
    assert hinted.cells[index] == solution[index] and hinted.hints == 1 and hinted.moves == 3
    with pytest.raises(ValueError):
        original.put(next(i for i, v in enumerate(original.givens) if v), 0)


def test_grid_conflicts_do_not_destroy_user_guesses_or_falsely_mark_won():
    game = NumberGrid.new(9)
    index = game.givens.index(0)
    row = index // 9 * 9
    digit = next(n for n in game.cells[row:row + 9] if n)
    changed = game.put(index, digit)
    assert index in conflicts(changed.cells) and not changed.won
    restored = decode_game(json.loads(json.dumps(encode_game(changed))))
    assert restored == changed
    solved = replace(game, cells=solutions(game.givens)[0])
    assert solved.won
    with pytest.raises(ValueError, match="solved"):
        solved.put(index, 0)


def test_ambiguous_invalid_and_changed_grid_clues_rejected():
    with pytest.raises(ValueError, match="exactly one"):
        NumberGrid((0,) * 81, (0,) * 81)
    game = NumberGrid.new(2)
    wrong = list(game.cells)
    wrong[next(i for i, n in enumerate(game.givens) if n)] = 0
    with pytest.raises(ValueError, match="fixed"):
        replace(game, cells=tuple(wrong))
    with pytest.raises(ValueError):
        replace(game, moves=True)
    with pytest.raises(ValueError):
        replace(game, hints=1)
    with pytest.raises(ValueError):
        game.put(True, 9)
    with pytest.raises(ValueError):
        game.put(81, 9)


def test_grid_generation_can_be_cancelled_before_saved_state_is_created():
    cancelled = Event()
    cancelled.set()
    with pytest.raises(InterruptedError):
        NumberGrid.new(1, cancel=cancelled)


@pytest.mark.parametrize("seed", range(12))
def test_shuffled_tiles_are_valid_solvable_and_not_already_won(seed):
    game = SlidingTiles.new(seed)
    assert not game.won and game.moves == 0
    assert game == SlidingTiles.new(seed)
    assert set(game.cells) == set(range(16))
    for i in game.legal_moves():
        moved = game.move(i)
        assert moved.moves == 1 and moved.move(game.cells.index(0)).cells == game.cells


def test_sliding_moves_reject_wraparound_and_detect_win():
    game = SlidingTiles((*range(1, 15), 0, 15))
    assert game.legal_moves() == (10, 13, 15)
    assert game.move(15).won
    with pytest.raises(ValueError):
        game.move(0)
    with pytest.raises(ValueError):
        game.move(True)
    with pytest.raises(ValueError, match="solvable"):
        SlidingTiles((2, 1, *range(3, 16), 0))
    with pytest.raises(ValueError):
        SlidingTiles((0,) * 16)


def test_computer_never_loses_across_all_player_choices():
    seen, outcomes = set(), set()
    def explore(game):
        if game.cells in seen:
            return
        seen.add(game.cells)
        if game.outcome:
            outcomes.add(game.outcome)
            assert game.outcome != "X"
            return
        for index, value in enumerate(game.cells):
            if value == ".":
                explore(game.play(index))
    explore(ThreeInRow())
    assert len(seen) > 100 and outcomes == {"O", "draw"}


def test_computer_reply_is_one_turn_and_undo_can_restore_original_board():
    game = ThreeInRow()
    result = game.play(0)
    assert game.cells == "." * 9
    assert result.cells.count("X") == result.cells.count("O") == 1
    assert result == game.play(0) and result.moves == 1
    with pytest.raises(ValueError, match="empty"):
        result.play(0)
    with pytest.raises(ValueError):
        game.play(False)
    terminal = ThreeInRow("XXXOO....")
    assert terminal.outcome == "X"
    with pytest.raises(ValueError, match="finished"):
        terminal.play(8)


@pytest.mark.parametrize("cells", ["bad", "." * 8, "XXXOOO...", "OO.......", "X........", "XXXXXXXXX", "O"*9])
def test_unreachable_or_mid_turn_three_in_row_saves_rejected(cells):
    with pytest.raises(ValueError):
        ThreeInRow(cells)


@pytest.fixture
def store(tmp_path):
    return GameStore(tmp_path / "test #games.db")


def games():
    return (NumberGrid.new(3), SlidingTiles.new(3), ThreeInRow().play(0))


def test_three_games_have_independent_slots_and_survive_reopen(store):
    for game in games():
        assert store.load(game.kind) == SavedGame(game.kind)
        saved = store.save(game, expected_revision=0)
        assert saved.revision == 1
        assert GameStore(store.path).load(game.kind) == saved
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM recreation_games").fetchone()[0] == 3


def test_stale_save_and_concurrent_first_saves_do_not_overwrite(store):
    game = ThreeInRow()
    def save(index):
        try:
            store.save(game.play(index), expected_revision=0)
            return "saved"
        except GameConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(save, (0, 2))) == ["conflict", "saved"]
    first = store.load(game.kind)
    assert first.revision == 1
    with pytest.raises(GameConflict):
        store.save(game, expected_revision=0)
    assert store.load(game.kind) == first


def test_identical_saves_do_not_bump_revision_or_change_bytes(store):
    game = SlidingTiles.new(0)
    first = store.save(game, expected_revision=0)
    before = store.path.read_bytes()
    assert store.save(game, expected_revision=first.revision) == first
    assert store.path.read_bytes() == before


def test_corrupt_or_future_game_is_reported_not_silently_reset(store):
    game = ThreeInRow()
    store.save(game, expected_revision=0)
    with store.connect() as db:
        db.execute("UPDATE recreation_games SET payload='malformed'")
    before = store.path.read_bytes()
    bad = store.load(game.kind)
    assert bad.game is None and bad.revision == 1 and "checksum" in bad.error
    assert store.path.read_bytes() == before
    replaced = store.save(game, expected_revision=bad.revision)
    assert replaced.game == game and replaced.revision == 2


@pytest.mark.parametrize("payload", [
    {}, {"kind": "sliding", "version": True, "state": {}},
    {"kind": "sliding", "version": 99, "state": {}},
    {"kind": "unknown", "version": 1, "state": {}},
    {"kind": "sliding", "version": 1, "state": {"cells": list(range(16)), "moves": float("nan")}},
    {"kind": "three_in_row", "version": 1, "state": {"cells": ".........", "extra": 1}},
])
def test_invalid_game_envelopes_do_not_instantiate(payload):
    with pytest.raises(ValueError):
        decode_game(payload)


def test_large_or_duplicate_json_is_rejected_without_execution(store):
    import hashlib
    for text in ('{"kind":"three_in_row","kind":"sliding","version":1,"state":{}}', "x" * 9000):
        with store.connect() as db:
            db.execute("INSERT OR REPLACE INTO recreation_games VALUES(?,?,?,?,?)",
                       ("three_in_row", text, hashlib.sha256(text.encode()).hexdigest(), 1, "now"))
        result = store.load("three_in_row")
        assert result.error and result.game is None


def test_failed_write_rolls_back_previous_board_and_revision(store):
    first = store.save(ThreeInRow(), expected_revision=0)
    with store.connect() as db:
        db.execute("CREATE TRIGGER deny_game BEFORE UPDATE ON recreation_games "
                   "BEGIN SELECT RAISE(ABORT,'simulated write error'); END")
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        store.save(first.game.play(0), expected_revision=1)
    assert store.load(first.kind) == first


def test_unknown_schema_is_not_migrated_or_reset(store):
    with store.connect() as db:
        db.execute("UPDATE recreation_meta SET value='99'")
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="unsupported"):
        GameStore(store.path)
    assert store.path.read_bytes() == before


def test_unrelated_private_tables_never_read_or_changed(store):
    with store.connect() as db:
        db.execute("CREATE TABLE household_members(note TEXT)")
        db.execute("INSERT INTO household_members VALUES('PRIVATE_MARKER')")
    store.save(ThreeInRow(), expected_revision=0)
    store.load("three_in_row")
    with store.connect() as db:
        assert db.execute("SELECT note FROM household_members").fetchone()[0] == "PRIVATE_MARKER"
        assert "PRIVATE_MARKER" not in db.execute("SELECT payload FROM recreation_games").fetchone()[0]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='app_events'").fetchone() is None


def test_no_network_or_other_accounts_are_required(store, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network attempted")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, blocked)
    for game in games():
        saved = store.save(game, expected_revision=0)
        assert store.load(game.kind) == saved


def test_store_option_validation(store):
    for kind in ("unknown", [], None):
        with pytest.raises(ValueError):
            store.load(kind)
    with pytest.raises(ValueError):
        store.save(ThreeInRow(), expected_revision=True)


def test_valid_payload_in_wrong_slot_is_not_returned_as_a_playable_board(store):
    import hashlib
    payload = json.dumps(encode_game(ThreeInRow()))
    with store.connect() as db:
        db.execute("INSERT INTO recreation_games VALUES(?,?,?,?,?)",
                   ("sliding", payload, hashlib.sha256(payload.encode()).hexdigest(), 1, "now"))
    saved = store.load("sliding")
    assert saved.game is None and "does not match" in saved.error
