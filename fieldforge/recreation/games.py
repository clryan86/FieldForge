"""Immutable puzzle engines. No UI, files, network, downloaded assets, or model.

Number Grid is a Sudoku-style puzzle with one checked solution; Sliding Tiles
starts from legal moves; Three in a Row uses a deterministic minimax opponent.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from threading import Event
from typing import ClassVar

KINDS = ("number_grid", "sliding", "three_in_row")
NAMES = dict(zip(KINDS, ("Number Grid", "Sliding Tiles", "Three in a Row")))
MAX_MOVES = 1_000_000


def _integer(value: int, low: int, high: int, name: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")


def _cells(cells: tuple[int, ...], size: int, highest: int) -> None:
    if not isinstance(cells, tuple) or len(cells) != size:
        raise ValueError("invalid board dimensions")
    for value in cells:
        _integer(value, 0, highest, "cell")


UNITS = tuple(
    [tuple(r * 9 + c for c in range(9)) for r in range(9)]
    + [tuple(r * 9 + c for r in range(9)) for c in range(9)]
    + [tuple((br + r) * 9 + bc + c for r in range(3) for c in range(3))
       for br in (0, 3, 6) for bc in (0, 3, 6)]
)
PEERS = tuple(frozenset(j for unit in UNITS if i in unit for j in unit if j != i)
              for i in range(81))


def conflicts(cells: tuple[int, ...]) -> frozenset[int]:
    return frozenset(i for i, value in enumerate(cells)
                     if value and any(cells[j] == value for j in PEERS[i]))


@lru_cache(maxsize=128)
def solutions(givens: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    """Find up to two solutions with MRV branching and a deterministic work cap."""
    _cells(givens, 81, 9)
    if conflicts(givens):
        return ()
    board, result, visited = list(givens), [], 0

    def search() -> None:
        nonlocal visited
        visited += 1
        if visited > 50_000:
            raise ValueError("puzzle validation exceeded its work limit")
        choice, choices = -1, ()
        for i, value in enumerate(board):
            if value:
                continue
            possible = tuple(v for v in range(1, 10) if all(board[j] != v for j in PEERS[i]))
            if not possible:
                return
            if choice == -1 or len(possible) < len(choices):
                choice, choices = i, possible
                if len(choices) == 1:
                    break
        if choice == -1:
            result.append(tuple(board))
            return
        for value in choices:
            board[choice] = value
            search()
            if len(result) >= 2:
                break
        board[choice] = 0

    search()
    return tuple(result)


@dataclass(frozen=True)
class NumberGrid:
    givens: tuple[int, ...]
    cells: tuple[int, ...]
    moves: int = 0
    hints: int = 0
    kind: ClassVar[str] = "number_grid"

    def __post_init__(self) -> None:
        _cells(self.givens, 81, 9)
        _cells(self.cells, 81, 9)
        _integer(self.moves, 0, MAX_MOVES, "moves")
        _integer(self.hints, 0, self.moves, "hints")
        if any(value and self.cells[i] != value for i, value in enumerate(self.givens)):
            raise ValueError("fixed clues cannot be changed")
        if len(solutions(self.givens)) != 1:
            raise ValueError("Number Grid must have exactly one solution")

    @property
    def won(self) -> bool:
        return 0 not in self.cells and not conflicts(self.cells)

    def put(self, index: int, value: int) -> NumberGrid:
        _integer(index, 0, 80, "square")
        _integer(value, 0, 9, "digit")
        if self.givens[index]:
            raise ValueError("This is a fixed clue. Choose an empty or editable square.")
        if self.won:
            raise ValueError("This puzzle is solved. Start a new game or undo.")
        if self.cells[index] == value:
            return self
        cells = list(self.cells)
        cells[index] = value
        return replace(self, cells=tuple(cells), moves=self.moves + 1)

    def hint(self, index: int) -> NumberGrid:
        _integer(index, 0, 80, "square")
        value = solutions(self.givens)[0][index]
        if self.givens[index] or self.cells[index] == value:
            raise ValueError("Choose an editable square that still needs its answer.")
        return replace(self.put(index, value), hints=self.hints + 1)

    @classmethod
    def new(cls, seed: int | None = None, *, clues: int = 38,
            cancel: Event | None = None) -> NumberGrid:
        _integer(clues, 32, 45, "minimum clues")
        rng = random.Random(seed)
        groups = [0, 1, 2]
        rows = [g * 3 + r for g in rng.sample(groups, 3) for r in rng.sample(groups, 3)]
        cols = [g * 3 + c for g in rng.sample(groups, 3) for c in rng.sample(groups, 3)]
        digits = rng.sample(list(range(1, 10)), 9)
        board = [digits[(r * 3 + r // 3 + c) % 9] for r in rows for c in cols]
        order = rng.sample(list(range(81)), 81)
        remaining = 81
        for index in order:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("new game cancelled")
            if remaining <= clues:
                break
            old = board[index]
            board[index] = 0
            try:
                unique = len(solutions(tuple(board))) == 1
            except ValueError:
                unique = False  # Keep a clue rather than accept an unverified puzzle.
            if unique:
                remaining -= 1
            else:
                board[index] = old
        puzzle = tuple(board)
        return cls(puzzle, puzzle)


@dataclass(frozen=True)
class SlidingTiles:
    cells: tuple[int, ...] = (*range(1, 16), 0)
    moves: int = 0
    kind: ClassVar[str] = "sliding"

    def __post_init__(self) -> None:
        _cells(self.cells, 16, 15)
        _integer(self.moves, 0, MAX_MOVES, "moves")
        if set(self.cells) != set(range(16)):
            raise ValueError("tiles must contain 0 through 15 exactly once")
        values = [v for v in self.cells if v]
        inversions = sum(a > b for i, a in enumerate(values) for b in values[i + 1:])
        blank_row_from_bottom = 4 - self.cells.index(0) // 4
        if (inversions + blank_row_from_bottom) % 2 != 1:
            raise ValueError("this tile arrangement is not solvable")

    @property
    def won(self) -> bool:
        return self.cells == (*range(1, 16), 0)

    def legal_moves(self) -> tuple[int, ...]:
        r, c = divmod(self.cells.index(0), 4)
        return tuple(i for i in range(16) if abs(i // 4 - r) + abs(i % 4 - c) == 1)

    def move(self, index: int) -> SlidingTiles:
        _integer(index, 0, 15, "tile")
        if index not in self.legal_moves():
            raise ValueError("Choose a tile directly beside the empty space.")
        cells = list(self.cells)
        blank = cells.index(0)
        cells[blank], cells[index] = cells[index], cells[blank]
        return SlidingTiles(tuple(cells), self.moves + 1)

    @classmethod
    def new(cls, seed: int | None = None) -> SlidingTiles:
        rng = random.Random(seed)
        game, previous_blank = cls(), -1
        # Every shuffle step is legal; no randomly permuted unsolvable boards.
        for _ in range(160):
            index = rng.choice(tuple(i for i in game.legal_moves() if i != previous_blank))
            previous_blank = game.cells.index(0)
            game = game.move(index)
        if game.won:
            game = game.move(game.legal_moves()[0])
        return replace(game, moves=0)


LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))
_MOVE_ORDER = (4, 0, 2, 6, 8, 1, 3, 5, 7)


def winner(cells: str) -> str:
    for a, b, c in LINES:
        if cells[a] != "." and cells[a] == cells[b] == cells[c]:
            return cells[a]
    return "draw" if "." not in cells else ""


@lru_cache(maxsize=1)
def _reachable() -> frozenset[str]:
    seen = set()

    def walk(cells: str, turn: str) -> None:
        if cells in seen:
            return
        seen.add(cells)
        if winner(cells):
            return
        for i in range(9):
            if cells[i] == ".":
                walk(cells[:i] + turn + cells[i + 1:], "O" if turn == "X" else "X")

    walk("." * 9, "X")
    return frozenset(seen)


@lru_cache(maxsize=6000)
def _score(cells: str, turn: str) -> int:
    outcome = winner(cells)
    if outcome:
        return {"X": -1, "O": 1, "draw": 0}[outcome]
    values = [_score(cells[:i] + turn + cells[i + 1:], "X" if turn == "O" else "O")
              for i in _MOVE_ORDER if cells[i] == "."]
    return max(values) if turn == "O" else min(values)


@dataclass(frozen=True)
class ThreeInRow:
    cells: str = "." * 9
    kind: ClassVar[str] = "three_in_row"

    def __post_init__(self) -> None:
        if not isinstance(self.cells, str) or len(self.cells) != 9 or self.cells not in _reachable():
            raise ValueError("invalid Three in a Row board")
        if not self.outcome and self.cells.count("X") != self.cells.count("O"):
            raise ValueError("saved board must be at the player's turn")

    @property
    def outcome(self) -> str:
        return winner(self.cells)

    @property
    def moves(self) -> int:
        return self.cells.count("X")

    def play(self, index: int) -> ThreeInRow:
        _integer(index, 0, 8, "square")
        if self.outcome:
            raise ValueError("This round is finished. Start a new game or undo.")
        if self.cells[index] != ".":
            raise ValueError("Choose an empty square.")
        cells = self.cells[:index] + "X" + self.cells[index + 1:]
        if not winner(cells):
            # Deterministic full game-tree search, not a language model or network service.
            best = max((i for i in _MOVE_ORDER if cells[i] == "."),
                       key=lambda i: _score(cells[:i] + "O" + cells[i + 1:], "X"))
            cells = cells[:best] + "O" + cells[best + 1:]
        return ThreeInRow(cells)


Game = NumberGrid | SlidingTiles | ThreeInRow


def encode_game(game: Game) -> dict[str, object]:
    if type(game) not in (NumberGrid, SlidingTiles, ThreeInRow):
        raise ValueError("unsupported game type")
    return {"kind": game.kind, "version": 1, "state": asdict(game)}


def decode_game(payload: object) -> Game:
    if not isinstance(payload, dict) or set(payload) != {"kind", "version", "state"}:
        raise ValueError("invalid game envelope")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("unsupported game version")
    kind, state = payload["kind"], payload["state"]
    if not isinstance(kind, str) or kind not in KINDS or not isinstance(state, dict):
        raise ValueError("invalid game kind/state")
    expected = {"number_grid": {"givens", "cells", "moves", "hints"},
                "sliding": {"cells", "moves"}, "three_in_row": {"cells"}}[kind]
    if set(state) != expected:
        raise ValueError("invalid game state fields")
    fields = dict(state)
    for key in ("givens", "cells"):
        if key in fields and kind != "three_in_row":
            if not isinstance(fields[key], list):
                raise ValueError("board cells must be a JSON array")
            fields[key] = tuple(fields[key])
    return {"number_grid": NumberGrid, "sliding": SlidingTiles, "three_in_row": ThreeInRow}[kind](**fields)
