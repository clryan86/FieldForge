# Offline Recreation

This starts the requested entertainment section with three playable classic
puzzle/strategy games, not placeholders. The implementations and interface are
original code. No third-party game artwork, sound, movie, book or music assets
are copied or downloaded. This change does not choose or change the repository's
redistribution license. It does not add a generative AI model or expand the
survival/reference corpus.

## Play

In the updated desktop choose **Recreation**, select a game and **New game**.
No accounts, advertisements, purchases, internet connection or additional runtime
dependencies are required. Keyboard input is bound to the game board, not global
application shortcuts. Click a square to focus the board first.

- **Number Grid:** a Sudoku-style 9×9 puzzle. Fill each row, column and 3×3 box
  with 1–9. Fixed clues cannot be edited. Click a square and type 1–9 or use the
  digit buttons; Backspace/Delete clears an editable square. Arrow keys select
  neighboring squares. Duplicate digits are highlighted and counted, but this
  does not identify every wrong guess. Hint reveals the selected square from
  the unique solution and increments the hint count. More/Fewer clues selects
  a generation target, not a validated human difficulty grade. Every generated
  board is checked for a single solution before acceptance.
- **Sliding Tiles:** arrange 1–15 with the empty space at bottom right. Click a
  tile adjacent to the empty space, or use arrows to move the empty space. New
  boards are produced using legal moves from a solved board and are therefore
  solvable. A saved impossible permutation is rejected.
- **Three in a Row:** the player is X, computer is O. Click or use keys 1–9,
  counted left to right and top to bottom. A turn contains the player move and
  the computer reply. The deterministic minimax opponent searches the finite
  game tree; it is not a language model or online service. Tests explore all
  possible player choices against this opponent and check that it cannot lose.

## Save, resume, undo and conflicts

There is one current saved board per game per database, shared by anyone using
that database. No player profile, timer, leaderboard, lifetime score, telemetry,
achievement, or play-history log is created. An accepted move is saved before
advancing the displayed board; storage failures leave the previous board visible.
Choose Reload saved game to see changes made by another application window.
Revision checks prevent a stale window from silently overwriting newer play.

New game requires confirmation when that slot already contains a saved board.
Other game slots and unrelated application tables are not changed. Corrupt or
incompatible game payloads are reported without being silently reset. The user
can deliberately replace a damaged slot with a confirmed new game, provided its
revision is still current. An unknown table schema is rejected, not downgraded.

Undo restores the preceding whole turn (including the computer reply) and saves
that restored board. Up to 200 preceding turns in the current view are retained
in memory. Switching games, reloading or closing clears undo history; the current
saved board remains. Counts reflect the restored board, so undo also rolls back
move/hint counts. It is not a permanent puzzle archive or tamperproof score record.

Number-grid generation runs on a worker; only the main thread touches Tk.
Cancel creation or close the window to discard unfinished generation. A late
worker result cannot replace a board after cancellation. Individual game saves
use short SQLite transactions with a 250 ms lock wait; this is not a hard-real-time
or power-loss guarantee. The solver is work-bounded and cached, not a general
untrusted-code sandbox. No commands or executable objects are loaded from saves.

## Data and backups

`recreation_meta` and `recreation_games` are additive tables. The latter stores
small, bounded, versioned JSON boards, body checksums, revisions and device-UTC
update times. Only these tables are accessed by the recreation store. Household,
medical/planning notes, article text, and emergency records are not used as game
input. No user details are filled from accounts or prior conversations.

The main app uses its currently selected database. Complete SQLite snapshots
include these tables even though the existing recovery report does not display
separate game counts. Article JSON knowledge packs and the older household JSON
backup do not contain saved games. Databases remain unencrypted. Checksums detect
accidental changes, not authenticity or encryption.

The standalone command is:

```sh
python -m fieldforge.ui.recreation
```

It honors `FIELDFORGE_DB`; otherwise it defaults to
`~/.fieldforge/recreation.db`, separate from the household database. Override
explicitly with `--database`. Backing up a different application database does
not capture this separate standalone file. On Windows `py -3` may replace
`python`. The standalone screen still requires Python 3.10+ and Tkinter; it is
not a packaged Windows or mobile binary.

## Delivery and verification

A new source-bundle CI job runs only after all baseline/Linux graphical/Windows
workflow jobs succeed. It archives the checked-out Git commit (tracked source
only, not `.git` credentials, runtime databases or personal records), records its
commit ID and provides an expiring development-source artifact. The artifact
is not a signed installer or a release; it can use GitHub's tested PR merge
commit rather than the branch tip. Do not call it verified until those jobs
actually finish successfully. An existing downloaded ZIP still does not update
itself. Close the old app and back up its database before replacing source files.

Targeted tests cover unique puzzles, editable clues, duplicate detection, hints,
valid tile parity and moves, all player branches against the computer, strict
save decoding, persistence, concurrent/stale writes, rollback, unknown schema,
privacy separation, no-network operation, real Tk controls, save errors, undo,
keyboard input, cancellation and minimum-window geometry. Full-checkout tests
add recovery, knowledge-pack privacy and the real desktop close lifecycle.
Linux and hosted Windows CI explicitly require a graphical display for UI tests.
Their results must be checked for the exact commit; adding a job is not evidence
that it passed. No Apple, Android/iOS or universal screen-reader qualification is
claimed. No physical health/cognitive training benefit is claimed for the games.

Technical references consulted:
- Python random: https://docs.python.org/3/library/random.html
- Python SQLite transactions/lifecycle: https://docs.python.org/3/library/sqlite3.html
- Python ttk widgets: https://docs.python.org/3.10/library/tkinter.ttk.html
- GitHub artifact action: https://github.com/actions/upload-artifact
