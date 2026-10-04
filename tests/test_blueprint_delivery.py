"""Exercise the shipped desktop entry point and a real offline create/edit/export path."""

import copy
import os
import socket

import pytest

from fieldforge.blueprints.layout import create_layout
from fieldforge.blueprints.parameters import prepare_part_edit
from fieldforge.blueprints.render import (
    export_blueprint,
    load_blueprint,
    normalized_document,
    save_blueprint,
)
from fieldforge.knowledge import KnowledgeLibrary


def parts():
    return [{"name": "Panel", "material": "User supplied plywood",
             "size": ["24 in", "30 cm", "18 mm"], "position": ["0", "0", "0"]},
            {"name": "Second panel", "material": "User supplied plywood",
             "size": ["24 in", "30 cm", "18 mm"], "position": ["0", "0", "40 cm"]}]


def test_manual_dimensions_survive_edit_save_reopen_and_offline_export(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Manual drafting must not need a network or model")
    monkeypatch.setattr(socket, "socket", forbidden)
    rows = parts()
    original = copy.deepcopy(rows)
    value = create_layout("Two panel layout", rows)
    assert rows == original
    assert value["design"]["parts"][0]["size_mm"] == [609.6, 300, 18]
    assert value["sources"] == [] and value["review"] is None and value["attempts"] == []
    assert value["status"] == "needs_revision" and "no AI" in value["model"]
    edited = prepare_part_edit(value, "P2", position=["0", "0", "50 cm"])["blueprint"]
    assert value["design"]["parts"][1]["position_mm"][2] == 400
    saved = save_blueprint(edited, tmp_path / "layout.json")
    reopened = load_blueprint(saved)
    assert reopened["design"]["parts"][1]["position_mm"][2] == 500
    export_blueprint(reopened, tmp_path / "drawings")
    for name in ("top.svg", "front.svg", "side.svg", "isometric.svg", "part-001.svg",
                 "part-002.svg", "parts.csv", "materials.csv", "report.html", "blueprint.json"):
        assert (tmp_path / "drawings" / name).is_file()
    assert load_blueprint(tmp_path / "drawings/blueprint.json")["design"] == reopened["design"]


@pytest.mark.parametrize("field, value", [("size", ["0", "1", "1"]),
                                         ("size", ["nan", "1", "1"]),
                                         ("position", ["-1", "0", "0"]),
                                         ("material", "")])
def test_invalid_layout_input_cannot_become_a_design(field, value):
    rows = parts()
    rows[0][field] = value
    with pytest.raises(ValueError):
        create_layout("Invalid layout", rows)


def test_manual_layout_cannot_claim_a_model_review():
    value = create_layout("Panel layout", parts())
    value["review"] = {"findings": [], "missing_information": []}
    with pytest.raises(ValueError, match="manual layout"):
        normalized_document(value)
    value["review"] = None
    value["model"] = "invented-model"
    with pytest.raises(ValueError, match="sources"):
        normalized_document(value)


@pytest.fixture
def root():
    import tkinter as tk
    try:
        window = tk.Tk()
    except tk.TclError:
        if os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1":
            raise
        pytest.skip("A display is required; graphical CI must set FIELDFORGE_REQUIRE_GUI=1")
    errors = []
    window.report_callback_exception = lambda *args: errors.append(args)
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass
    assert not errors


def test_home_form_creates_real_drawing_and_guards_unapplied_inputs(root, tmp_path, monkeypatch):
    from fieldforge.ui.blueprint_home import BlueprintHome
    home = BlueprintHome(root, KnowledgeLibrary(tmp_path / "test.db"))
    home.pack(fill="both", expand=True)
    form = home.new_layout()
    form.name.set("My measured layout")
    form.part_name.set("Panel")
    form.material.set("Recorded plywood")
    for field, value in zip(form.size, ["1 m", "30 cm", "18 mm"]):
        field.set(value)
    form.add()
    form.size[0].set("2 m")
    form.create()
    assert home.studio is None and "update" in form.status.get()
    form.rows.selection_set("0")
    form.update_part()
    form.geometry("760x650")
    root.update()
    button = form.create_button
    assert button.winfo_rooty() + button.winfo_height() <= form.winfo_rooty() + form.winfo_height()
    button.invoke()
    root.update()
    studio = home.studio
    maker = studio.makers["engineering"]
    assert maker.blueprint["design"]["parts"][0]["size_mm"][0] == 2000
    assert str(maker.pages.select()) == str(maker.preview)
    assert home.layout_form is None
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *_a, **_kw: False)
    assert not home.can_close()
    saved = tmp_path / "ui-created.json"
    monkeypatch.setattr("fieldforge.ui.blueprints.filedialog.asksaveasfilename", lambda **_kw: str(saved))
    maker.save()
    assert load_blueprint(saved)["design"] == maker.blueprint["design"]
    assert home.can_close()
    for mode in ("project", "software"):
        assert home.open_maker(mode) is studio
        assert str(studio.pages.select()) == str(studio.makers[mode])


def test_normal_desktop_has_blueprints_beside_dashboard_and_keeps_existing_sections(root, tmp_path, monkeypatch):
    import tkinter as tk
    from tkinter import ttk

    from fieldforge.ui import desktop
    from fieldforge.ui.blueprint_home import BlueprintHome
    database = tmp_path / "desktop.db"
    library = KnowledgeLibrary(database)
    monkeypatch.setenv("FIELDFORGE_DB", str(database))
    monkeypatch.setattr(tk, "Tk", lambda: root)

    def inspect():
        root.update()
        book = next(child for child in root.winfo_children() if isinstance(child, ttk.Notebook))
        labels = [book.tab(tab, "text") for tab in book.tabs()]
        assert labels[:2] == ["Dashboard", "Blueprints"]
        assert {"Maps", "Online Maps", "Knowledge Library", "Places"} <= set(labels)
        home = next(root.nametowidget(tab) for tab in book.tabs() if book.tab(tab, "text") == "Blueprints")
        assert isinstance(home, BlueprintHome)
        book.select(home)
        root.update()
        assert home.new_button.winfo_ismapped()
        knowledge = next(root.nametowidget(tab) for tab in book.tabs()
                         if book.tab(tab, "text") == "Knowledge Library")
        assert library.count() == 439 and not knowledge.busy
        knowledge._blueprints()
        assert home.studio is not None
        assert knowledge._blueprint_studio is None

    monkeypatch.setattr(root, "mainloop", inspect)
    desktop.run()
