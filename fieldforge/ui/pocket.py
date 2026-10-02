"""Portable reader export uses the same preview/save lifecycle as Field Binder."""

from fieldforge.knowledge.pocket import capture_pocket, save_pocket
from fieldforge.ui.binder import BinderDialog, open_binder


class PocketDialog(BinderDialog):
    default_filename = "FieldForge-Pocket-Library.html"
    save_dialog_title = "Save a NEW offline pocket reader"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title("FieldForge — Portable Pocket Library")
        self.heading.configure(text="Your library, in a portable reading copy")
        self.title_label.configure(text="Collection title")
        self.binder_title.set("FieldForge Pocket Library")
        self.notes.set(False)
        self.note_box.grid_remove()
        self._controls = [(control, state) for control, state in self._controls if control is not self.note_box]
        self.save_button.configure(text="Save NEW pocket reader…")
        self.open_button.configure(text="Open saved reader…")
        self.privacy.configure(text=(
            "This unencrypted HTML file includes full article text and source labels, NEVER private article notes. "
            "Titles/bodies can themselves contain private information. Copy only material you have permission to share. "
            "Household, learning and incident records are excluded."
        ))
        self.notice.configure(text=(
            "A read-only, phone-friendly HTML copy with local search, categories and reading-size controls. "
            "No Python/server needed to read it. A compatible browser must allow local HTML/scripts for interactive "
            "search; static articles remain readable without scripts. This is not a native mobile app or an AI model."
        ))
        self.status.set("Select the current article or all bookmarks (up to 50). Preview before exporting. Notes are always excluded.")
        self._buttons()

    def capture_snapshot(self, *args, **kwargs):
        if kwargs.pop("include_notes", False) is not False:
            raise ValueError("Pocket Library never exports private article notes")
        return capture_pocket(*args, **kwargs)

    def save_snapshot(self, *args, **kwargs):
        return save_pocket(*args, **kwargs)


def open_pocket(knowledge_tab):
    return open_binder(knowledge_tab, dialog_type=PocketDialog)
