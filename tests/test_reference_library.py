import json
import socket
from importlib.resources import files

from fieldforge.content import install_reference_library
from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary


def test_bundled_corpus_is_substantial_attributed_and_entirely_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *_a, **_kw: (_ for _ in ()).throw(
        AssertionError("No networking during library installation")))
    library = KnowledgeLibrary(tmp_path / "library.db")
    result = install_reference_library(library)
    assert result["imported"] >= 200
    assert len(library.categories()) >= 12
    catalog = json.loads(files("fieldforge.content").joinpath("packs", "catalog.json").read_text("utf-8"))
    assert len(catalog["articles"]) == library.count()
    for source in catalog["articles"]:
        article = library.get(source["slug"])
        assert article.checksum == source["body_sha256"]
        assert len(article.body.split()) >= 180
        assert "oldid=" in article.source_url
        assert article.reviewed_on == ""
        assert "CC BY-SA" in article.license
        assert source["contributors"] in article.body
    for query in ("water", "voltage", "project", "software", "soil"):
        assert library.search(query), query
    first = catalog["articles"][0]["slug"]
    library.annotate(first, bookmarked=True, note="Keep private")
    again = install_reference_library(library)
    assert again["imported"] == 0 and again["unchanged"] == library.count()
    assert library.annotation(first)["note"] == "Keep private"


def test_conflicting_library_install_rolls_back_and_keeps_private_content(tmp_path):
    library = KnowledgeLibrary(tmp_path / "library.db")
    pack = json.loads(files("fieldforge.content").joinpath("packs", "reference-library.json").read_text("utf-8"))
    last = pack["data"]["articles"][-1]
    library.upsert(KnowledgeArticle(last["slug"], "User's version", "Keep this private article.",
                                   "private"))
    before = library.count()
    import pytest
    with pytest.raises(ValueError, match="different content"):
        install_reference_library(library)
    assert library.count() == before
    assert library.get(last["slug"]).title == "User's version"
