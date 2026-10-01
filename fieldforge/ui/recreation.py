"""Offline recreation: three playable games, saved moves, hints and local undo."""

from __future__ import annotations

import argparse
import os
import sqlite3
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from tkinter import messagebox, ttk

from fieldforge.recreation.games import (
    KINDS,
    NAMES,
    Game,
    NumberGrid,
    SlidingTiles,
    ThreeInRow,
    conflicts,
)
from fieldforge.recreation.store import GameStore, SavedGame

_RULES = {
    "number_grid": "Fill each row, column and 3 × 3 box with the digits 1–9.\n\n"
    "Select a square, then type a digit or use the buttons below. Arrow keys move the selection; "
    "Backspace clears it. Dark clues cannot be edited.\n\n"
    "Duplicate digits are highlighted. That check does not detect every wrong guess. "
    "Hint reveals the selected square's solution. Every new puzzle has one checked solution.",
    "sliding": "Put the tiles in order, 1–15, with the empty space at the bottom right.\n\n"
    "Select a tile directly beside the empty space to slide it. Arrow keys move the empty space.\n\n"
    "Each shuffle starts from legal moves, so the generated board is solvable. "
    "Undo reverses a move made in this window.",
    "three_in_row": "You are X. The computer is O. Put three of your marks in a row, column or diagonal.\n\n"
    "Select an empty square, or use number keys 1–9 (left to right, top to bottom). "
    "The computer replies locally, in the same turn.\n\n"
    "The opponent searches the game tree; no internet or language model is used. "
    "Undo takes back your move and the computer's reply.",
}
_ERRORS = (OSError, ValueError, sqlite3.Error)


def _new_game(kind: str, clues: int, cancel: Event) -> Game:
    if cancel.is_set():
        raise InterruptedError("new game cancelled")
    if kind == "number_grid":
        return NumberGrid.new(clues=clues, cancel=cancel)
    return SlidingTiles.new() if kind == "sliding" else ThreeInRow()


class RecreationTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, database: str | Path) -> None:
        super().__init__(parent, padding=16)
        self.store: GameStore | None = None
        self.current = SavedGame("number_grid")
        self.undo_states: list[Game] = []
        self.selected: int | None = None
        self.busy = False
        self._disposed = False
        self._generation = 0
        self._cancel = Event()
        self._poll_id = None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-puzzle")
        self.kind = tk.StringVar(value=NAMES["number_grid"])
        self.clues = tk.StringVar(value="More clues")
        self.title = tk.StringVar(value="Number Grid")
        self.summary = tk.StringVar(value="Choose New game to start, or resume a saved board.")
        self.status = tk.StringVar(value="No accounts, downloads, advertisements or internet connection required.")
        self.rules = tk.StringVar(value=_RULES["number_grid"])
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.bind("<Destroy>", self._on_destroy, add=True)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="Offline Recreation", font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
        ttk.Label(header, text="A few good games, wherever you are. Your current boards stay on this device.",
                  wraplength=950).pack(anchor="w", pady=(4, 0))
        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.game_picker = ttk.Combobox(toolbar, textvariable=self.kind, values=tuple(NAMES.values()),
                                        state="readonly", width=22)
        self.game_picker.pack(side="left")
        self.game_picker.bind("<<ComboboxSelected>>", lambda _: self.load())
        self.clue_picker = ttk.Combobox(toolbar, textvariable=self.clues, values=("More clues", "Fewer clues"),
                                        state="readonly", width=14)
        self.clue_picker.pack(side="left", padx=8)
        self.new_button = ttk.Button(toolbar, text="New game", command=self.new_game)
        self.new_button.pack(side="left")
        self.cancel_button = ttk.Button(toolbar, text="Cancel creation", command=self.cancel_new, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.reload_button = ttk.Button(toolbar, text="Reload saved game", command=self.load)
        self.reload_button.pack(side="right")

        middle = ttk.Frame(self)
        middle.grid(row=2, column=0, sticky="nsew")
        middle.columnconfigure(0, weight=3)
        middle.columnconfigure(1, weight=2)
        middle.rowconfigure(0, weight=1)
        play = ttk.LabelFrame(middle, text="Your board", padding=12)
        play.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        play.columnconfigure(0, weight=1)
        play.rowconfigure(2, weight=1)
        ttk.Label(play, textvariable=self.title, font=("TkDefaultFont", 17, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(play, textvariable=self.summary, wraplength=500).grid(row=1, column=0, sticky="w", pady=(4, 10))
        self.board = ttk.Frame(play, takefocus=True)
        self.board.grid(row=2, column=0)
        self.board.bind("<KeyPress>", self.key)
        self.cells: list[tk.Button] = []
        self.digits = ttk.Frame(play)
        self.digits.grid(row=3, column=0, pady=(10, 0))
        for value in range(1, 10):
            ttk.Button(self.digits, text=str(value), width=3,
                       command=lambda n=value: self.put(n)).pack(side="left", padx=1)
        side = ttk.Frame(middle, padding=(8, 4, 0, 0))
        side.grid(row=0, column=1, sticky="nsew")
        ttk.Label(side, text="HOW TO PLAY", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.help_label = ttk.Label(side, textvariable=self.rules, wraplength=310, justify="left")
        self.help_label.pack(fill="x", pady=(10, 20))
        ttk.Separator(side).pack(fill="x", pady=(0, 14))
        self.saved_help = ttk.Label(side, text="SAVE & RESUME\nEvery accepted move is saved before the board changes. "
                                    "One saved board per game, shared by everyone using this database.\n\n"
                                    "Undo is available for up to 200 moves made in this window. "
                                    "Changing games, reloading or closing clears undo history, not the saved board.",
                                    wraplength=310, justify="left")
        self.saved_help.pack(fill="x")
        side.bind("<Configure>", lambda e: [w.configure(wraplength=max(200, e.width - 16))
                                           for w in (self.help_label, self.saved_help)], add=True)
        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 8))
        self.undo_button = ttk.Button(actions, text="Undo turn", command=self.undo, state="disabled")
        self.undo_button.pack(side="left")
        self.hint_button = ttk.Button(actions, text="Hint for selected square", command=self.hint, state="disabled")
        self.hint_button.pack(side="left", padx=8)
        self.clear_button = ttk.Button(actions, text="Clear square", command=lambda: self.put(0), state="disabled")
        self.clear_button.pack(side="left")
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=1000, justify="left")
        self.footer.grid(row=4, column=0, sticky="ew")
        self.bind("<Configure>", lambda e: self.footer.configure(wraplength=max(400, e.width - 40)), add=True)
        try:
            self.store = GameStore(database)
            self.load()
        except _ERRORS as exc:
            self.status.set("Game storage unavailable; existing records were not reset. " + str(exc))
            self._buttons()

    def _kind(self) -> str:
        return next(key for key in KINDS if NAMES[key] == self.kind.get())

    def _buttons(self) -> None:
        available = self.store is not None and not self.busy
        for button in (self.new_button, self.reload_button):
            button.configure(state="normal" if available else "disabled")
        self.game_picker.configure(state="disabled" if self.busy else "readonly")
        self.cancel_button.configure(state="normal" if self.busy else "disabled")
        self.clue_picker.configure(state="readonly" if available and self._kind() == "number_grid" else "disabled")
        self.undo_button.configure(state="normal" if available and self.undo_states else "disabled")
        numbered = available and isinstance(self.current.game, NumberGrid) and not self.current.game.won
        for button in (self.hint_button, self.clear_button):
            button.configure(state="normal" if numbered else "disabled")
        for button in self.digits.winfo_children():
            button.configure(state="normal" if numbered else "disabled")

    def load(self) -> None:
        if self.busy or self.store is None:
            return
        try:
            self.current = self.store.load(self._kind())
        except _ERRORS as exc:
            self.current = SavedGame(self._kind(), error=str(exc))
            self.status.set("Could not load game. No stored board was changed. " + str(exc))
        else:
            self.status.set(self.current.error or ("Resumed the locally saved board." if self.current.game
                                                   else "No saved board for this game. Choose New game to start."))
        self.selected = None
        self.undo_states.clear()
        self.render()

    def new_game(self) -> None:
        if self.busy or self.store is None:
            return
        if self.current.revision and not messagebox.askyesno(
            "Replace this saved game?", "Starting a new game replaces the saved board for "
            f"{NAMES[self.current.kind]}. Other games and FieldForge records are unchanged. Continue?", parent=self,
        ):
            return
        self.busy = True
        self._generation += 1
        self._cancel = Event()
        self._buttons()
        self.status.set("Creating a new puzzle locally…")
        future = self._worker.submit(_new_game, self._kind(), 38 if self.clues.get() == "More clues" else 32, self._cancel)
        self._poll_id = self.after(50, self._poll, future, self._generation)

    def _poll(self, future: Future, generation: int) -> None:
        if self._disposed or generation != self._generation:
            return
        self._poll_id = None
        if not future.done():
            self._poll_id = self.after(50, self._poll, future, generation)
            return
        self.busy = False
        try:
            game = future.result()
            if self._apply(game, remember=False):
                self.undo_states.clear()
                self.selected = next((i for i, n in enumerate(game.givens) if not n), None) if isinstance(game, NumberGrid) else None
                self.render()
                self.status.set("New game saved on this device. Have fun!")
        except _ERRORS as exc:
            self.status.set("New game was not saved: " + str(exc))
        self._buttons()

    def cancel_new(self) -> None:
        if not self.busy:
            return
        self._cancel.set()
        self._generation += 1
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self.busy = False
        self.status.set("Creation cancelled. Your previous saved board is unchanged.")
        self._buttons()

    def _apply(self, game: Game, *, remember: bool = True) -> bool:
        if self.store is None or self.busy:
            return False
        old = self.current.game
        try:
            saved = self.store.save(game, expected_revision=self.current.revision)
        except _ERRORS as exc:
            self.status.set("Not saved; the displayed board has not advanced. " + str(exc))
            return False
        if remember and old is not None and old != game:
            self.undo_states.append(old)
            del self.undo_states[:-200]
        self.current = saved
        self.render()
        self.status.set("Saved locally. No game history or scores are sent anywhere.")
        return True

    def click(self, index: int) -> None:
        if self.busy or self.current.game is None:
            return
        game = self.current.game
        try:
            if isinstance(game, NumberGrid):
                self.selected = index
                self.render()
                self.status.set(f"Row {index // 9 + 1}, column {index % 9 + 1}. "
                                + ("Fixed clue." if game.givens[index] else "Type 1–9 or choose a digit. Backspace clears."))
            elif isinstance(game, SlidingTiles):
                if game.won:
                    raise ValueError("Puzzle solved. Start a new game or undo.")
                self._apply(game.move(index))
            else:
                self._apply(game.play(index))
        except _ERRORS as exc:
            self.status.set(str(exc))
        self.board.focus_set()

    def put(self, digit: int) -> None:
        if self.busy or not isinstance(self.current.game, NumberGrid):
            return
        if self.selected is None:
            self.status.set("Select an editable square first.")
            return
        try:
            self._apply(self.current.game.put(self.selected, digit))
        except _ERRORS as exc:
            self.status.set(str(exc))
        self.board.focus_set()

    def hint(self) -> None:
        if self.busy or not isinstance(self.current.game, NumberGrid):
            return
        if self.selected is None:
            self.status.set("Select an editable square for a hint.")
            return
        try:
            self._apply(self.current.game.hint(self.selected))
        except _ERRORS as exc:
            self.status.set(str(exc))
        self.board.focus_set()

    def undo(self) -> None:
        if not self.busy and self.undo_states:
            previous = self.undo_states[-1]
            if self._apply(previous, remember=False):
                self.undo_states.pop()
                self.status.set("Turn undone and saved. Move/hint counts reflect the restored board.")
                self._buttons()

    def key(self, event: tk.Event) -> str | None:
        if self.busy or self.current.game is None:
            return None
        game, key = self.current.game, event.keysym
        arrows = {"Left": (0, -1), "Right": (0, 1), "Up": (-1, 0), "Down": (1, 0)}
        if isinstance(game, NumberGrid):
            if key in arrows:
                dr, dc = arrows[key]
                r, c = divmod(self.selected if self.selected is not None else 0, 9)
                self.click(max(0, min(8, r + dr)) * 9 + max(0, min(8, c + dc)))
            elif key in ("BackSpace", "Delete", "0"):
                self.put(0)
            elif key in "123456789" and len(key) == 1:
                self.put(int(key))
            else:
                return None
        elif isinstance(game, SlidingTiles) and key in arrows:
            r, c = divmod(game.cells.index(0), 4)
            dr, dc = arrows[key]
            if 0 <= r + dr < 4 and 0 <= c + dc < 4:
                self.click((r + dr) * 4 + c + dc)
        elif isinstance(game, ThreeInRow) and key in "123456789" and len(key) == 1:
            self.click(int(key) - 1)
        else:
            return None
        return "break"

    def render(self) -> None:
        game = self.current.game
        self.title.set(NAMES[self.current.kind])
        self.rules.set(_RULES[self.current.kind])
        for widget in self.board.winfo_children():
            widget.destroy()
        self.cells.clear()
        if game is None:
            ttk.Label(self.board, text="Ready when you are.\n\nChoose New game to begin.",
                      font=("TkDefaultFont", 15), justify="center", padding=30).pack()
            self.summary.set("Saved board unavailable; it has not been reset." if self.current.error else "No game started yet.")
            self.digits.grid_remove()
            self._buttons()
            return
        if isinstance(game, NumberGrid):
            width, values = 9, game.cells
            bad = conflicts(game.cells)
            self.summary.set("Puzzle complete!" if game.won else
                             f"{sum(v != 0 for v in game.cells)}/81 filled · {game.moves} edits · {game.hints} hints · {len(bad)} conflicting squares")
            self.digits.grid()
        elif isinstance(game, SlidingTiles):
            width, values, bad = 4, game.cells, set()
            self.summary.set(f"Puzzle complete in {game.moves} moves!" if game.won else f"{game.moves} moves · put 1–15 in order")
            self.digits.grid_remove()
        else:
            width, values, bad = 3, game.cells, set()
            self.summary.set({"": "Your turn — X", "draw": "A draw. Try another round!", "X": "You won!", "O": "Computer won. Try again!"}[game.outcome])
            self.digits.grid_remove()
        for index, value in enumerate(values):
            number = isinstance(game, NumberGrid)
            fixed = number and game.givens[index] != 0
            background = "#e5ece7" if fixed else "#ffffff"
            foreground = "#1d382b" if fixed else "#285f85"
            if index in bad:
                background, foreground = "#fbe2df", "#822e26"
            if number and index == self.selected:
                background = "#cfe5f6"
            if not number and value in (0, "."):
                background = "#eaf0eb"
            text = "" if value in (0, ".") else str(value)
            button = tk.Button(self.board, text=text, width=3 if number else 5,
                               height=1 if number else 2, font=("TkDefaultFont", 15 if number else 23, "bold"),
                               bg=background, fg=foreground, activebackground="#d5e7dc", relief="flat", bd=1,
                               highlightthickness=1, highlightbackground="#b5c4b9", takefocus=True, padx=0, pady=0,
                               command=lambda i=index: self.click(i))
            row, col = divmod(index, width)
            button.grid(row=row, column=col, padx=(3 if number and col % 3 == 0 else 1, 1),
                        pady=(3 if number and row % 3 == 0 else 1, 1), ipadx=1, ipady=2)
            self.cells.append(button)
        self._buttons()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self and not self._disposed:
            self._disposed = True
            self._cancel.set()
            self._generation += 1
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
            self._worker.shutdown(wait=False, cancel_futures=True)


def add_recreation_tab(notebook: ttk.Notebook, database: str | Path) -> RecreationTab:
    frame = RecreationTab(notebook, database)
    notebook.add(frame, text="Recreation")
    return frame


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(
        os.environ.get("FIELDFORGE_DB", "~/.fieldforge/recreation.db")
    ).expanduser())
    args = parser.parse_args()
    root = tk.Tk()
    root.title("FieldForge — Offline Recreation")
    root.geometry("1120x820")
    root.minsize(960, 730)
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    frame = RecreationTab(root, args.database)
    frame.pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    run()
