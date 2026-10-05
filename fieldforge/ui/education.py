"""Offline education workspace: read, attempt, explain, compare, revisit."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.knowledge.education import (
    NOTICE,
    StudyStore,
    check,
    lessons,
    revise,
    worksheet,
)
from fieldforge.ui.fraction_lab import FractionLab, draw_fraction
from fieldforge.ui.lifecycle import release_tk_references


class EducationTab(ttk.Frame):
    def __init__(self, parent, database):
        super().__init__(parent, padding=12)
        self.store = StudyStore(database)
        self.catalog = lessons()
        self.by_id = {lesson.id: lesson for lesson in self.catalog}
        self.lesson = None
        self.work = None
        self.question_index = 0
        self.diagram_index = 0
        self._timer = None
        self._loading = False
        self._save_error = ""
        self.search = tk.StringVar()
        self.track = tk.StringVar(value="Guided: Numbers & operations")
        self.status = tk.StringVar(value="Choose a lesson. Practice is stored in this device's FieldForge database.")
        self.progress = tk.StringVar()
        self.question_choice = tk.StringVar()
        self.choice_response = tk.StringVar()
        self.prerequisite_choice = tk.StringVar()

        heading = ttk.Frame(self)
        heading.pack(fill="x")
        ttk.Label(heading, text="Education", style="Header.TLabel").pack(side="left")
        ttk.Button(heading, text="Export worksheet…", command=self.export).pack(side="right")
        ttk.Button(heading, text="Reload saved answer…", command=self.reload_saved).pack(side="right", padx=8)
        self.notice = ttk.Label(self, text="Learn → try → explain → review. Choose numbers, fractions, measurement, literacy, evidence or reference courses below.")
        self.notice.pack(anchor="w", pady=(2, 8))
        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        browser = ttk.Frame(panes, width=285)
        detail = ttk.Frame(panes, padding=(12, 0, 0, 0))
        panes.add(browser, weight=1)
        panes.add(detail, weight=3)
        ttk.Label(browser, text="Search title, goal or lesson text").pack(anchor="w")
        search = ttk.Entry(browser, textvariable=self.search)
        search.pack(fill="x", pady=(2, 6))
        search.bind("<Return>", lambda _e: self.refresh())
        ttk.Button(browser, text="Search", command=self.refresh).pack(anchor="e")
        self.track_picker = ttk.Combobox(browser, textvariable=self.track, state="readonly",
                                         values=["All lessons", *sorted({lesson.track for lesson in self.catalog if lesson.guided}),
                                                 *sorted({lesson.track for lesson in self.catalog if not lesson.guided})])
        self.track_picker.pack(fill="x", pady=8)
        self.track_picker.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        ttk.Button(browser, text="Resume saved practice", command=self.resume).pack(fill="x", pady=(0, 8))
        tree_frame = ttk.Frame(browser)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse", height=12)
        bar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.column("#0", width=285, minwidth=220, stretch=True)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._select_lesson)
        ttk.Label(browser, text="All practice is personal to this local database.\nExport a worksheet to keep a separate learner's copy.",
                  wraplength=280).pack(anchor="w", pady=(8, 0))

        self.title = ttk.Label(detail, font=("TkDefaultFont", 14, "bold"), wraplength=650)
        self.title.pack(anchor="w")
        ttk.Label(detail, textvariable=self.progress).pack(anchor="w", pady=(3, 6))
        requirements = ttk.Frame(detail)
        requirements.pack(fill="x", pady=(0, 6))
        ttk.Label(requirements, text="Earlier lesson").pack(side="left", padx=(0, 6))
        self.prerequisite = ttk.Combobox(requirements, state="readonly", width=35,
                                        textvariable=self.prerequisite_choice)
        self.prerequisite.pack(side="left", fill="x", expand=True)
        self.prerequisite_button = ttk.Button(requirements, text="Open", command=self.open_prerequisite)
        self.prerequisite_button.pack(side="left", padx=(6, 0))
        self.pages = ttk.Notebook(detail)
        self.pages.pack(fill="both", expand=True)
        self.read_page = ttk.Frame(self.pages)
        self.practice_page = ttk.Frame(self.pages, padding=8)
        self.pages.add(self.read_page, text="Learn & worked examples")
        self.pages.add(self.practice_page, text="Practice & explain")
        self.fraction_lab = FractionLab(self.pages)
        self.pages.add(self.fraction_lab, text="Fraction lab")
        self.pages.hide(self.fraction_lab)
        self.reading = ScrolledText(self.read_page, wrap="word", height=12, padx=14, pady=12,
                                   font=("TkDefaultFont", 11), state="disabled")
        self.reading.pack(fill="both", expand=True)
        self.reading.tag_configure("heading", font=("TkDefaultFont", 11, "bold"), spacing1=14, spacing3=5)
        self.reading.tag_configure("body", spacing3=12)
        self.diagram_frame = ttk.Frame(self.read_page)
        self.diagram_controls = ttk.Frame(self.diagram_frame)
        self.diagram_previous = ttk.Button(self.diagram_controls, text="← Previous step", command=lambda: self.move_diagram(-1))
        self.diagram_previous.pack(side="left")
        self.diagram_next = ttk.Button(self.diagram_controls, text="Next step →", command=lambda: self.move_diagram(1))
        self.diagram_next.pack(side="right")
        self.diagram_step = ttk.Label(self.diagram_controls, anchor="center")
        self.diagram_step.pack(fill="x", expand=True)
        self.diagram = tk.Canvas(self.diagram_frame, height=132, background="#f0f5f8", highlightthickness=0)
        self.diagram.pack(fill="x")
        self.diagram_caption = ttk.Label(self.diagram_frame, wraplength=650)
        self.diagram.bind("<Configure>", lambda _e: self.draw_diagram())
        ttk.Button(self.read_page, text="Try the practice →", command=lambda: self.pages.select(self.practice_page)).pack(anchor="e", pady=6)

        practice = self.practice_page
        practice.columnconfigure(0, weight=1)
        practice.rowconfigure(1, weight=2)
        practice.rowconfigure(7, weight=2)
        nav = ttk.Frame(practice)
        nav.grid(row=0, column=0, sticky="ew")
        self.previous = ttk.Button(nav, text="← Previous", command=lambda: self.move_question(-1))
        self.previous.pack(side="left")
        self.question_picker = ttk.Combobox(nav, state="readonly", textvariable=self.question_choice, width=23)
        self.question_picker.pack(side="left", fill="x", expand=True, padx=6)
        self.question_picker.bind("<<ComboboxSelected>>", self._select_question)
        self.next = ttk.Button(nav, text="Next →", command=lambda: self.move_question(1))
        self.next.pack(side="right")
        self.question_pages = ttk.Notebook(practice)
        self.question_pages.grid(row=1, column=0, sticky="nsew", pady=6)
        self.prompt = ScrolledText(self.question_pages, wrap="word", height=5, padx=8, pady=8,
                                  state="disabled", font=("TkDefaultFont", 11))
        self.source_text = ScrolledText(self.question_pages, wrap="word", height=5, padx=8, pady=8,
                                       state="disabled", font=("TkDefaultFont", 11))
        self.question_pages.add(self.prompt.frame, text="Question & options")
        self.question_pages.add(self.source_text.frame, text="Passage / model")
        self.response_label = ttk.Label(practice)
        self.response_label.grid(row=2, column=0, sticky="w")
        self.response = ScrolledText(practice, wrap="word", height=2, font=("TkDefaultFont", 11), undo=True)
        self.response.grid(row=3, column=0, sticky="ew", pady=(3, 6))
        self.choices = ttk.Frame(practice)
        self.choices.grid(row=3, column=0, sticky="ew", pady=(3, 6))
        self.choices.grid_remove()
        ttk.Label(practice, text="Explain your method, evidence or uncertainty").grid(row=4, column=0, sticky="w")
        self.reasoning = ScrolledText(practice, wrap="word", height=2, font=("TkDefaultFont", 11), undo=True)
        self.reasoning.grid(row=5, column=0, sticky="ew", pady=(3, 6))
        actions = ttk.Frame(practice)
        actions.grid(row=6, column=0, sticky="ew")
        self.check_button = ttk.Button(actions, text="Check number", command=self.check_answer)
        self.check_button.pack(side="left")
        self.hint_button = ttk.Button(actions, text="One hint", command=self.hint)
        self.hint_button.pack(side="left", padx=5)
        self.reveal_button = ttk.Button(actions, text="Show worked answer", command=self.reveal)
        self.reveal_button.pack(side="left")
        ttk.Button(actions, text="Save", command=self.save_current).pack(side="right")
        self.feedback = ScrolledText(practice, wrap="word", height=5, padx=8, pady=8,
                                    state="disabled", font=("TkDefaultFont", 10))
        self.feedback.grid(row=7, column=0, sticky="nsew", pady=6)
        reflection = ttk.Frame(practice)
        reflection.grid(row=8, column=0, sticky="ew")
        ttk.Label(reflection, text="After comparing:").pack(side="left")
        self.review_button = ttk.Button(reflection, text="I need more practice", command=lambda: self.reflect("needs practice"))
        self.review_button.pack(side="left", padx=5)
        self.explained_button = ttk.Button(reflection, text="I can explain it", command=lambda: self.reflect("explained it"))
        self.explained_button.pack(side="left")
        self.status_label = ttk.Label(self, textvariable=self.status, wraplength=1050)
        # Reserve the footer before the expanding pane requests its space.
        # Otherwise a compact window can hide save errors below the viewport.
        self.status_label.pack(side="bottom", fill="x", pady=(8, 0), before=panes)
        for entry in (self.response, self.reasoning):
            entry.bind("<<Modified>>", self._edited)
        self.bind("<Configure>", self._resize, add=True)
        self.bind("<Destroy>", self._destroy, add=True)
        self.refresh()

    @property
    def question(self):
        return self.lesson.questions[self.question_index]

    @staticmethod
    def _text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _resize(self, event):
        if event.widget is self:
            self.title.configure(wraplength=max(250, self.winfo_width() - 340))
            self.notice.configure(wraplength=max(250, self.winfo_width() - 30))
            self.status_label.configure(wraplength=max(250, self.winfo_width() - 30))

    def refresh(self):
        if not self.save_current():
            return
        query = self.search.get().strip().casefold()
        rows = [lesson for lesson in self.catalog
                if (self.track.get() == "All lessons" or lesson.track == self.track.get())
                and query in " ".join((lesson.title, lesson.goal, *lesson.paragraphs)).casefold()]
        self._populate_lessons(rows)
        if rows:
            selected = self.lesson.id if self.lesson and self.lesson.id in {r.id for r in rows} else rows[0].id
            self.open_lesson(selected)
        else:
            self.status.set("No lessons match. Clear the search or choose All lessons. Your current work remains open.")

    def _populate_lessons(self, rows):
        self._loading = True
        try:
            self.tree.delete(*self.tree.get_children())
            for lesson in rows:
                self.tree.insert("", "end", iid=lesson.id, text=lesson.title)
        finally:
            self._loading = False

    def _select_lesson(self, _event):
        selected = self.tree.selection()
        if self._loading or not selected or (self.lesson and selected[0] == self.lesson.id):
            return
        if not self.open_lesson(selected[0]) and self.lesson and self.tree.exists(self.lesson.id):
            self.tree.selection_set(self.lesson.id)

    def open_lesson(self, key):
        if not self.save_current():
            return False
        lesson = self.by_id[key]
        try:
            work = self.store.read(key, lesson.questions[0])
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.status.set(f"Could not open practice: {exc}")
            return False
        self.lesson, self.question_index, self.work = lesson, 0, work
        self.diagram_index = 0
        if not self.tree.exists(key):
            # A prerequisite or saved lesson can be outside the current filter.
            # Select it in the browser too, so queued selection events cannot
            # reopen the previously selected lesson after navigation finishes.
            self.track.set(lesson.track)
            self.search.set("")
            self._populate_lessons([item for item in self.catalog if item.track == lesson.track])
        self.tree.selection_set(key)
        self.tree.see(key)
        self.title.configure(text=lesson.title)
        values = [self.by_id[key].title for key in lesson.prerequisites]
        self.prerequisite.configure(values=values)
        self.prerequisite_choice.set(values[0] if values else "No earlier lesson required")
        self.prerequisite_button.configure(state="normal" if values else "disabled")
        self.reading.configure(state="normal")
        self.reading.delete("1.0", "end")
        sections = ["GOAL\n" + lesson.goal, "MATERIALS\n" + lesson.materials, *lesson.paragraphs]
        if lesson.diagram:
            sections.append("DIAGRAM DESCRIPTION\n" + lesson.diagram["description"])
            for index, step in enumerate(lesson.diagram.get("steps", []), 1):
                if lesson.diagram["kind"] == "fraction_steps":
                    groups = "; ".join(f"{r['label']}: {r['selected']}/{r['parts']} of one whole" for r in step["rows"])
                else:
                    groups = "; ".join(f"{g['label']}: {g['tens']} tens and {g['ones']} ones" for g in step["groups"])
                sections.append(f"DIAGRAM STEP {index} · {step['title']}\n{step['caption']}\n{groups}")
        sections.extend(["ABOUT THESE MATERIALS\n" + NOTICE,
                         "BACKGROUND REFERENCES\n" + "\n\n".join(lesson.references)])
        for section in sections:
            heading, separator, body = section.partition("\n")
            if separator:
                self.reading.insert("end", heading + "\n", "heading")
                self.reading.insert("end", body + "\n\n", "body")
            else:
                self.reading.insert("end", section + "\n\n", "body")
        self.reading.configure(state="disabled")
        self.reading.yview_moveto(0)
        if lesson.diagram:
            self.diagram_frame.pack(fill="x", before=self.reading)
            if lesson.diagram["kind"] in {"counters", "fraction_steps"}:
                self.diagram_controls.pack(fill="x", before=self.diagram)
                self.diagram_caption.pack(fill="x", pady=(2, 5))
                self.diagram.configure(height=208 if lesson.diagram["kind"] == "fraction_steps" else 174)
            else:
                self.diagram_controls.pack_forget()
                self.diagram_caption.pack_forget()
                self.diagram.configure(height=132)
            self.draw_diagram()
        else:
            self.diagram_frame.pack_forget()
        if lesson.id.startswith("fraction-") or lesson.id == "guide-fractions":
            self.pages.add(self.fraction_lab, text="Fraction lab")
        else:
            self.pages.hide(self.fraction_lab)
        self.question_picker.configure(values=[f"{i+1} of {len(lesson.questions)} · {q.kind.title() if q.kind != 'reflection' else 'Explain'}"
                                               for i, q in enumerate(lesson.questions)])
        self._show_question()
        self.pages.select(self.read_page)
        return True

    def open_prerequisite(self):
        index = self.prerequisite.current()
        if self.lesson and 0 <= index < len(self.lesson.prerequisites):
            self.open_lesson(self.lesson.prerequisites[index])

    def resume(self):
        if not self.save_current():
            return
        try:
            recent = self.store.recent()
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.status.set(f"Could not resume practice: {exc}")
            return
        if recent and self.open_lesson(recent[0]):
            self.move_question(recent[1])
            self.pages.select(self.practice_page)
        elif not recent:
            self.status.set("No saved practice yet. Choose a lesson and write an answer.")

    def reload_saved(self):
        if not self.lesson:
            return
        try:
            saved = self.store.read(self.lesson.id, self.question)
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.status.set(f"Could not reload practice: {exc}")
            return
        if self._draft() != saved and not messagebox.askyesno(
                "Replace current response?", "Reload the saved answer for this exercise? Your current unsaved text "
                "will be replaced. Choose No and Export worksheet first if you need to keep it.", parent=self):
            return
        if self._timer is not None:
            self.after_cancel(self._timer)
            self._timer = None
        self.work, self._save_error = saved, ""
        self._show_question()

    def _select_question(self, _event):
        self.move_question(self.question_picker.current() - self.question_index)

    def move_question(self, delta):
        target = self.question_index + delta
        if not self.lesson or not 0 <= target < len(self.lesson.questions):
            return
        if self.save_current():
            try:
                work = self.store.read(self.lesson.id, self.lesson.questions[target])
            except (OSError, ValueError, sqlite3.Error) as exc:
                self.status.set(f"Could not load practice: {exc}")
            else:
                self.question_index, self.work = target, work
                self._show_question()
        self.question_picker.current(self.question_index)

    def _show_question(self):
        self._loading = True
        q = self.question
        self.question_picker.current(self.question_index)
        options = "\n\n" + "\n\n".join(f"{key}. {label}" for key, label in q.choices) if q.choices else ""
        self._text(self.prompt, q.prompt + options)
        self._text(self.source_text, q.passage)
        if q.passage:
            self.question_pages.add(self.source_text.frame, text="Passage / model")
        else:
            self.question_pages.hide(self.source_text.frame)
        self.question_pages.select(self.prompt.frame)
        self.prompt.yview_moveto(0)
        self.source_text.yview_moveto(0)
        label = (f"Your answer in {q.unit} — number, decimal or fraction only" if q.kind == "number"
                 else "Choose an option above; explain the supporting evidence below" if q.kind == "choice"
                 else "Your written response — compare it yourself; no automatic grading")
        self.response_label.configure(text=label)
        for child in self.choices.winfo_children():
            child.destroy()
        self.choice_response.set(self.work.response)
        if q.kind == "choice":
            self.response.grid_remove()
            self.choices.grid()
            for key, _label in q.choices:
                ttk.Radiobutton(self.choices, text=key, value=key, variable=self.choice_response,
                                command=self._schedule_save).pack(side="left", padx=(0, 24))
        else:
            self.choices.grid_remove()
            self.response.grid()
        for widget, value in ((self.response, self.work.response), (self.reasoning, self.work.reasoning)):
            widget.delete("1.0", "end")
            widget.insert("1.0", value)
            widget.edit_reset()
            widget.edit_modified(False)
        self._loading = False
        self.previous.configure(state="normal" if self.question_index else "disabled")
        self.next.configure(state="normal" if self.question_index + 1 < len(self.lesson.questions) else "disabled")
        self.check_button.configure(state="disabled" if q.kind == "reflection" else "normal",
                                    text="Check choice" if q.kind == "choice" else "Check number")
        self._controls()
        self._feedback()
        self._progress()
        self.status.set("Saved work loaded." if self.work.revision else "Write an answer before comparing. Drafts save automatically on this device.")

    def _controls(self):
        self.hint_button.configure(state="normal" if self.work.hints < len(self.question.hints) else "disabled")
        for button in (self.review_button, self.explained_button):
            button.configure(state="normal" if self.work.revealed else "disabled")

    def _feedback(self, message=""):
        pieces = [message] if message else []
        if self.work.result == "correct":
            support = "with a hint/answer shown" if self.work.hints or self.work.revealed else "before hints/answer reveal"
            label = "numeric answer" if self.question.kind == "number" else "selected option"
            pieces.append(f"Latest {label} matches ({support}). Your explanation is not automatically graded.")
        elif self.work.result == "retry":
            pieces.append("Latest answer needs another try.")
        pieces.extend(f"Hint {i+1}: {hint}" for i, hint in enumerate(self.question.hints[:self.work.hints]))
        if self.work.revealed:
            pieces.append("WORKED ANSWER / COMPARISON CRITERIA\n" + self.question.explanation)
        if self.work.reflection:
            pieces.append("Your self-review: " + self.work.reflection)
        self._text(self.feedback, "\n\n".join(pieces) or "Try first. Hints and worked answers are available when you need them.")

    def _edited(self, event):
        widget = event.widget
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        self._schedule_save()

    def _schedule_save(self):
        if self._loading or not self.lesson:
            return
        if self._timer is not None:
            self.after_cancel(self._timer)
        self.status.set("Unsaved changes…")
        self._timer = self.after(700, self.save_current)

    def _draft(self):
        response = self.choice_response.get() if self.question.kind == "choice" else self.response.get("1.0", "end-1c")
        return revise(self.work, response, self.reasoning.get("1.0", "end-1c"))

    def _persist(self, work):
        if self._timer is not None:
            self.after_cancel(self._timer)
            self._timer = None
        if work == self.work:
            return True
        try:
            self.work = self.store.save(self.lesson.id, self.question, work)
            self._save_error = ""
            self.status.set("Saved on this device. Full database backups include education work.")
            self._progress()
            return True
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._save_error = str(exc)
            self.status.set(f"NOT SAVED: {exc} Your response remains here; use Export worksheet to preserve it.")
            return False

    def save_current(self):
        if not self.lesson:
            return True
        draft = self._draft()
        success = self._persist(draft)
        if success:
            self._feedback()
        return success

    def can_close(self):
        if self.save_current():
            return True
        messagebox.showerror("Education work is not saved", self._save_error, parent=self)
        return False

    def _progress(self):
        try:
            self.progress.set(self.store.summary(self.lesson) + " · Personal practice record")
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.progress.set(f"Progress unavailable: {exc}")

    def check_answer(self):
        if not self.lesson:
            return
        updated, feedback = check(self.question, self._draft())
        if self._persist(updated):
            self._feedback(feedback)

    def hint(self):
        if self.lesson and self.work.hints < len(self.question.hints) and self._persist(replace(self._draft(), hints=self.work.hints + 1)):
            self._controls()
            self._feedback()

    def reveal(self):
        if self.lesson and self._persist(replace(self._draft(), revealed=True)):
            self._controls()
            self._feedback()

    def reflect(self, value):
        if self.lesson and self.work.revealed and self._persist(replace(self._draft(), reflection=value)):
            self._feedback()

    def export(self):
        if not self.lesson:
            return
        # Export is also a recovery path for an unsaved edit / concurrent update.
        target = filedialog.asksaveasfilename(parent=self, title="Save a new offline worksheet",
                                             defaultextension=".html", initialfile=self.lesson.id + "-worksheet.html",
                                             filetypes=[("Offline HTML worksheet", "*.html")])
        if not target:
            return
        try:
            records = tuple(self._draft() if i == self.question_index else self.store.read(self.lesson.id, q)
                            for i, q in enumerate(self.lesson.questions))
            with Path(target).open("x", encoding="utf-8") as stream:
                stream.write(worksheet(self.lesson, records))
            self.status.set("Worksheet exported with your current text. It contains personal responses and a collapsible answer key.")
        except (OSError, ValueError, sqlite3.Error) as exc:
            messagebox.showerror("Worksheet was not exported", str(exc), parent=self)

    def move_diagram(self, offset):
        if not self.lesson or not self.lesson.diagram or self.lesson.diagram["kind"] not in {"counters", "fraction_steps"}:
            return
        self.diagram_index = max(0, min(len(self.lesson.diagram["steps"]) - 1, self.diagram_index + offset))
        self.draw_diagram()

    def draw_diagram(self):
        if not self.lesson or not self.lesson.diagram:
            return
        canvas = self.diagram
        canvas.delete("all")
        width = max(300, canvas.winfo_width())
        diagram = self.lesson.diagram
        kind = diagram["kind"]
        color, ink = "#2c7f99", "#18394a"
        if kind in {"counters", "fraction_steps"}:
            step = diagram["steps"][self.diagram_index]
            self.diagram_step.configure(text=f"{self.diagram_index + 1}/{len(diagram['steps'])} · {step['title']}")
            self.diagram_caption.configure(text=step["caption"], wraplength=max(250, width - 12))
            self.diagram_previous.configure(state="disabled" if self.diagram_index == 0 else "normal")
            self.diagram_next.configure(state="disabled" if self.diagram_index == len(diagram["steps"]) - 1 else "normal")
        if kind == "fraction_steps":
            draw_fraction(canvas, diagram, self.diagram_index)
        elif kind == "counters":
            from fieldforge.knowledge.education_visuals import counter_scene
            for mark in counter_scene(diagram, self.diagram_index, width):
                if mark.kind == "text":
                    canvas.create_text(*mark.coords, text=mark.text, fill=ink, font=("TkDefaultFont", 9))
                elif mark.kind == "one":
                    canvas.create_oval(*mark.coords, fill=color, outline="", tags=("one",))
                else:
                    canvas.create_rectangle(*mark.coords, fill="#dcebf0" if mark.kind == "ten" else "",
                                            outline=ink, tags=(mark.kind,))
        elif kind == "bars":
            from fieldforge.knowledge.education import bar_chart
            canvas.create_text(width / 2, 14, text=diagram["title"], fill=ink)
            for label, left, top, right, bottom, value in bar_chart(diagram, width):
                canvas.create_text(left - 8, top + 7, text=label, anchor="e", fill=ink)
                canvas.create_rectangle(left, top, right, bottom, fill=color, outline="")
                canvas.create_text(right + 6, top + 7, text=value, anchor="w", fill=ink)
            canvas.create_line(102, 25, 102, 103, width - 70, 103, fill=ink)
            for x, value in ((102, 0), ((102 + width - 70) / 2, diagram["maximum"] / 2),
                             (width - 70, diagram["maximum"])):
                canvas.create_text(x, 121, text=f"{value:g}", fill=ink)
        elif kind == "fraction":
            step = (width - 70) / diagram["parts"]
            for i in range(diagram["parts"]):
                x = 35 + i * step
                filled = i < diagram["selected"]
                canvas.create_rectangle(x, 25, x + step, 78, fill=color if filled else "white", outline=ink)
                if filled:
                    canvas.create_text(x + step / 2, 51, text="X", fill="white")
            canvas.create_text(width / 2, 105, text="3 of 8 equal parts of the SAME whole", fill=ink)
        elif kind == "ruler":
            step = (width - 70) / diagram["maximum"]
            canvas.create_line(35, 70, width - 35, 70, fill=ink)
            for i in range(diagram["maximum"] + 1):
                x = 35 + i * step
                canvas.create_line(x, 63, x, 77, fill=ink)
                canvas.create_text(x, 90, text=str(i), fill=ink)
            canvas.create_line(35 + step * diagram["start"], 42, 35 + step * diagram["end"], 42,
                               fill=color, width=8, arrow="both")
            canvas.create_text(width / 2, 117, text="2 cm to 9 cm · length = 7 cm · schematic", fill=ink)
        elif kind == "grid":
            step = min((width - 80) / diagram["columns"], 23)
            left = (width - step * diagram["columns"]) / 2
            for row in range(diagram["rows"]):
                for col in range(diagram["columns"]):
                    x, y = left + col * step, 7 + row * step
                    canvas.create_rectangle(x, y, x + step, y + step, fill="#dcebf0", outline=ink)
            text = "24 squares · each 1 cm²" if self.lesson.id == "guide-area" else "24 squares · each 100 cm² · full face 60 × 40 cm"
            canvas.create_text(width / 2, 116, text=text, fill=ink)
        elif kind == "scale":
            canvas.create_rectangle(width * .12, 35, width * .28, 85, outline=ink, width=2)
            canvas.create_line(width * .36, 60, width * .54, 60, arrow="last", fill=color, width=3)
            canvas.create_rectangle(width * .62, 20, width * .87, 96, outline=ink, width=2)
            canvas.create_text(width * .2, 112, text="Drawing: 3 × 2 cm", fill=ink)
            canvas.create_text(width * .75, 112, text="Object: 30 × 20 cm", fill=ink)
            canvas.create_text(width * .45, 35, text="1 : 10", fill=ink)

    def _destroy(self, event):
        if event.widget is self:
            if self._timer is not None:
                self.after_cancel(self._timer)
                self._timer = None
            release_tk_references(self)
