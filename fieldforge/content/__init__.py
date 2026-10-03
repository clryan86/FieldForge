"""Bundled offline reference packs; explicit local installation, no downloads."""

from __future__ import annotations

from importlib.resources import as_file, files

from fieldforge.knowledge.packs import import_pack


def install_reference_library(library):
    resource = files(__package__).joinpath("packs", "reference-library.json")
    with as_file(resource) as path:
        result = import_pack(library, path)
    return {**result, "packs": 1}
