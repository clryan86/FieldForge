"""Bundled lesson browser and session-only exact-arithmetic practice.

No lesson installation, grading history, personal reading links or practice
records are written until a user explicitly installs missing article content.
"""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.knowledge.foundations import (
    NOTICE,
    STATES,
    InstallReport,
    catalog,
    foundation_articles,
    inspect_foundations,
    install_foundations,
)


_ROW_STATES = {"missing": "Not installed", "installed": "Installed", "preserved": "Preserved"}


class FoundationsDialog(tk.Toplevel):
    def __init__(self, parent, library, *, on_close=None):
        super().__init__(parent)
        self.library, self.on_close = library, on_close
        self.lessons, self.articles = catalog(), foundation_articles()
        self.result: InstallReport | None = None
        self.states = {}
        self.selected = 0
        self.busy = ""
        self._disposed = False
        self._poll_id = None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-foundations")
        self.title("FieldForge — Foundations Learning Pack")
        self.geometry("1150x830")
        self.minsize(980, 720)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.lesson_title = tk.StringVar()
        self.lesson_info = tk.StringVar()
        self.exercise_choice = tk.StringVar(value="Exercise 1")
        self.question = tk.StringVar()
        self.response = tk.StringVar()
        self.feedback = tk.StringVar(value="Answers are not saved. This does not change your Pathways progress.")
        self.acknowledged = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Checking which lessons are installed…")
        header = ttk.Frame(self, padding=(16, 14))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Learn the practical foundations", font=("TkDefaultFont", 21, "bold")).pack(anchor="w")
        ttk.Label(header, text=f"{len(self.lessons)} complete lessons · {sum(len(l.exercises) for l in self.lessons)} "
                  "self-check exercises · no downloads", font=("TkDefaultFont", 11)).pack(anchor="w", pady=(4, 0))
        self.notice = ttk.Label(self, text=NOTICE, wraplength=1090, justify="left", padding=(16, 0, 16, 12))
        self.notice.grid(row=1, column=0, sticky="ew")
        panes = self.panes = ttk.Panedwindow(self, orient="horizontal")
        self._pane_width = 0
        panes.bind("<Configure>", self._split, add=True)
        panes.grid(row=2, column=0, sticky="nsew", padx=16)
        left, right = ttk.Frame(panes), ttk.Frame(panes, padding=(12, 0, 0, 0))
        panes.add(left, weight=4)
        panes.add(right, weight=6)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(left, columns=("state",), show="tree headings", selectmode="browse", height=15)
        self.tree.heading("#0", text="Suggested lesson order")
        self.tree.heading("state", text="Installed copy")
        self.tree.column("#0", width=290, minwidth=180)
        self.tree.column("state", width=110, minwidth=100, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(left, command=self.tree.yview)
        horizontal = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        for i, lesson in enumerate(self.lessons):
            self.tree.insert("", "end", iid=str(i), text=f"{i+1:02d}. {lesson.title}", values=("Checking…",))
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.select())
        self.title_label = ttk.Label(right, textvariable=self.lesson_title, wraplength=590,
                                     font=("TkDefaultFont", 15, "bold"), justify="left")
        self.title_label.pack(fill="x", pady=(0, 6))
        self.info_label = ttk.Label(right, textvariable=self.lesson_info, wraplength=590, justify="left")
        self.info_label.pack(fill="x", pady=(0, 10))
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        reading = ttk.Frame(self.tabs)
        practice = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(reading, text="Read bundled lesson")
        self.tabs.add(practice, text="Practice & check")
        self.body = ScrolledText(reading, wrap="word", width=40, height=15,
                                 font=("TkDefaultFont", 12), state="disabled", padx=12, pady=12)
        self.body.pack(fill="both", expand=True)
        self.exercise_picker = ttk.Combobox(practice, textvariable=self.exercise_choice,
                                            values=("Exercise 1", "Exercise 2"), state="readonly", width=18)
        self.exercise_picker.pack(anchor="w", pady=(0, 10))
        self.exercise_picker.bind("<<ComboboxSelected>>", lambda _: self.choose_exercise())
        self.question_label = ttk.Label(practice, textvariable=self.question, wraplength=550, justify="left")
        self.question_label.pack(fill="x", pady=(0, 10))
        self.answer_entry = ttk.Entry(practice, textvariable=self.response)
        self.answer_entry.pack(fill="x")
        self.answer_entry.bind("<Return>", lambda _: self.check())
        ttk.Label(practice, text="Enter an exact number, decimal or fraction (for example 12, 0.5 or 1/2). "
                  "Do not include units. No expressions are executed.", wraplength=520, justify="left").pack(fill="x", pady=8)
        actions = ttk.Frame(practice)
        actions.pack(fill="x", pady=(4, 10))
        self.check_button = ttk.Button(actions, text="Check answer", command=self.check)
        self.check_button.pack(side="left")
        self.answer_button = ttk.Button(actions, text="Show worked answer", command=self.show_answer)
        self.answer_button.pack(side="left", padx=8)
        self.feedback_text = ScrolledText(practice, wrap="word", width=35, height=6,
                                          font=("TkDefaultFont", 11), state="disabled")
        self.feedback_text.pack(fill="both", expand=True)
        self.response.trace_add("write", lambda *_: self._feedback("Answer changed; check again. No answers are saved."))
        navigation = ttk.Frame(right)
        navigation.pack(fill="x", pady=(10, 0))
        self.previous = ttk.Button(navigation, text="Previous lesson", command=lambda: self.step(-1))
        self.previous.pack(side="left")
        self.next = ttk.Button(navigation, text="Next lesson", command=lambda: self.step(1))
        self.next.pack(side="right")
        right.bind("<Configure>", self._right_size, add=True)
        bottom = ttk.Frame(self, padding=(16, 12))
        bottom.grid(row=3, column=0, sticky="ew")
        self.consent = ttk.Checkbutton(bottom, variable=self.acknowledged,
                                      text="I understand this is original AI-drafted material, not specialist-reviewed guidance.",
                                      command=self._buttons)
        self.consent.pack(anchor="w", pady=(0, 8))
        buttons = ttk.Frame(bottom)
        buttons.pack(fill="x")
        self.install_button = ttk.Button(buttons, text="Add missing lessons to Library", command=self.install)
        self.install_button.pack(side="left")
        self.refresh_button = ttk.Button(buttons, text="Recheck installed copies", command=self.inspect)
        self.refresh_button.pack(side="left", padx=8)
        self.close_button = ttk.Button(buttons, text="Close", command=self.close)
        self.close_button.pack(side="right")
        self.footer = ttk.Label(bottom, textvariable=self.status, wraplength=1080, justify="left")
        self.footer.pack(fill="x", pady=(8, 0))
        self.bind("<Configure>", self._resize, add=True)
        self.tree.selection_set("0")
        self.select()
        self.inspect()
        self.grab_set()

    @staticmethod
    def _text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _resize(self, event):
        if event.widget is self:
            for label in (self.notice, self.footer):
                label.configure(wraplength=max(400, event.width-40))

    def _split(self, event):
        # A toplevel Configure can arrive before the pane has usable geometry.
        # Resize the split from the realized pane, never from an unrealized width.
        if event.widget is self.panes and event.width >= 600 and event.width != self._pane_width:
            self._pane_width = event.width
            self.panes.sashpos(0, max(300, int(event.width * 0.36)))

    def _right_size(self, event):
        for label in (self.title_label, self.info_label, self.question_label):
            label.configure(wraplength=max(250, event.width-40))

    def _feedback(self, value):
        self.feedback.set(value)
        self._text(self.feedback_text, value)

    def _buttons(self):
        self.install_button.configure(state="normal" if not self.busy and self.acknowledged.get() else "disabled")
        self.refresh_button.configure(state="disabled" if self.busy else "normal")
        self.consent.configure(state="disabled" if self.busy else "normal")
        self.close_button.configure(state="disabled" if self.busy == "install" else "normal")

    def select(self):
        selection = self.tree.selection()
        if not selection:
            return
        self.selected = int(selection[0])
        lesson, article = self.lessons[self.selected], self.articles[self.selected]
        self.lesson_title.set(article.title)
        state = STATES.get(self.states.get(article.slug), "Checking installed state")
        self.lesson_info.set(f"BUNDLED EDITION PREVIEW · {state}\n"
                             "Edited installed copies stay separate; existing records are never replaced.")
        self._text(self.body, article.body)
        self.exercise_picker.configure(values=tuple(f"Exercise {i+1}" for i in range(len(lesson.exercises))))
        self.exercise_picker.current(0)
        self.choose_exercise()
        self.previous.configure(state="normal" if self.selected else "disabled")
        self.next.configure(state="normal" if self.selected < len(self.lessons)-1 else "disabled")

    def step(self, direction):
        target = min(len(self.lessons)-1, max(0, self.selected+direction))
        self.tree.selection_set(str(target))
        self.tree.see(str(target))
        self.select()

    def _exercise(self):
        index = self.exercise_picker.current()
        if index < 0:
            raise ValueError("Choose an exercise first.")
        return self.lessons[self.selected].exercises[index]

    def choose_exercise(self):
        exercise = self._exercise()
        self.question.set(f"{exercise.question}\nAnswer unit: {exercise.unit}")
        self.response.set("")
        self._feedback("Try the exercise, then check your number or reveal the worked answer. "
                       "No score, personal record or Pathways progress is saved.")

    def check(self):
        try:
            exercise = self._exercise()
            correct = exercise.check(self.response.get())
            self._feedback(("Matches this exercise's expected value.\n\n" + exercise.explanation +
                            "\n\nArithmetic match only; no competence or safety certification.") if correct else
                           "Not yet. Recheck the units, operation order and assumptions in the lesson. "
                           "You can reveal the worked answer for the steps. No response is saved.")
        except ValueError as exc:
            self._feedback(str(exc))

    def show_answer(self):
        exercise = self._exercise()
        self._feedback(f"Worked answer: {exercise.answer} {exercise.unit}\n\n{exercise.explanation}\n\n"
                       "This is an explanation for the stated fictional inputs, not a saved grade or practice record.")

    def _start(self, operation, function, **kwargs):
        self.busy = operation
        self._buttons()
        self.status.set("Adding missing lessons in one transaction…" if operation == "install" else "Checking installed article copies…")
        future = self._worker.submit(function, self.library, **kwargs)
        self._poll_id = self.after(60, self._poll, future, operation)

    def inspect(self):
        if not self.busy and not self._disposed:
            self._start("inspect", inspect_foundations)

    def install(self):
        if not self.busy and not self._disposed and self.acknowledged.get():
            self._start("install", install_foundations, acknowledged=True)

    def _poll(self, future: Future, operation: str):
        if self._disposed:
            return
        self._poll_id = None
        if not future.done():
            self._poll_id = self.after(60, self._poll, future, operation)
            return
        self.busy = ""
        try:
            result = future.result()
            if operation == "install":
                self.result = result
                self.states = {slug: "installed" for slug in (*result.added, *result.unchanged)}
                self.states.update({slug: "preserved" for slug in result.preserved})
                self.status.set(str(result) + " Close this window to browse the installed lessons.")
            else:
                self.states = {row.slug: row.state for row in result}
                counts = {state: sum(value == state for value in self.states.values()) for state in STATES}
                self.status.set(f"{counts['missing']} not installed · {counts['installed']} identical · "
                                f"{counts['preserved']} different/unreadable and preserved. Preview/practice works before installation.")
            for i, article in enumerate(self.articles):
                self.tree.set(str(i), "state", _ROW_STATES[self.states[article.slug]])
            # Refresh the edition label without discarding an in-progress answer.
            article = self.articles[self.selected]
            self.lesson_info.set(f"BUNDLED EDITION PREVIEW · {STATES[self.states[article.slug]]}\n"
                                 "Edited installed copies stay separate; existing records are never replaced.")
        except Exception as exc:
            self.status.set("Operation failed: " + str(exc) + ". No successful installation is claimed for this attempt.")
        self._buttons()

    def close(self):
        if self.busy == "install":
            self.status.set("Let the installation finish before closing. Existing articles and private notes are not replaced.")
            return
        self.destroy()

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
            self._worker.shutdown(wait=False, cancel_futures=True)
            if self.on_close:
                self.on_close(self.result)


def open_foundations(knowledge_tab):
    if knowledge_tab.busy or not knowledge_tab.save_current():
        return None
    knowledge_tab.busy = True

    def finished(report):
        knowledge_tab.busy = False
        if report is None or not knowledge_tab.winfo_exists() or not knowledge_tab.body.winfo_exists():
            return
        knowledge_tab.query.set("foundations")
        knowledge_tab.category.set("All categories")
        knowledge_tab.favorites.set(False)
        knowledge_tab.refresh()
        knowledge_tab.status.set(str(report))

    try:
        return FoundationsDialog(knowledge_tab, knowledge_tab.library, on_close=finished)
    except Exception:
        knowledge_tab.busy = False
        raise
