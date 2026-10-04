"""Original lesson arithmetic and actual-library installation/export regressions."""

import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from fractions import Fraction as F

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge._learning_model import Exercise, parse_number
from fieldforge.knowledge.foundations import (
    NOTICE,
    PREFIX,
    article_for,
    catalog,
    export_foundations,
    foundation_articles,
    inspect_foundations,
    install_foundations,
    main,
)
from fieldforge.knowledge.packs import import_pack
from fieldforge.knowledge.pathways import PathwayStore, default_catalog
from fieldforge.knowledge.starter import install_starter

# Independently calculate every numeric practice answer from its stated inputs.
# Avoid float rounding, eval or copying a string answer from the content itself.
_CALCULATIONS = (
    (5*12+7, 84-9),
    (18+6*4, 53-6*8),
    (1-F(3, 8)-F(1, 4), F(625, 1000)),
    (45*F(2, 5), 10+2*10),
    (80*(1-F(15, 100)), (150-120)/F(120)*100),
    (F('3.6')*1000, 18*F('25.4')),
    (F('2.4')*F('1.5')-F('0.6')*F('0.5'), 2*(F('2.4')+F('1.5'))),
    (F(40*30*25, 1000), F(40*30*20, 1000)),
    ((F('19.8')+20+F('20.2'))/3, F('10.1')+F('5.1')),
    (F(6*25, 100), 7-2),
    (1+F(45, 60), 12+8*3),
    (85+24-37, 70-72),
    (240*(1-F(10, 100))/18, F(216, 27)),
    (8*5+20*3, F(400, 50)),
    (F(12, 4), F(38-8, 5)),
    (3+5+4+8, F(20-8, 4-2)),
    (F(4+5+5+6+20, 5), F(12+24, 2+8)),
    (F(18, 20)*100, 90-80),
    (40+12-9, abs(42-43)),
    (8*3*2+8, 10+3*5),
)


@pytest.mark.parametrize('index', range(20), ids=[lesson.slug for lesson in catalog()])
def test_each_practice_answer_matches_independent_exact_arithmetic(index):
    lesson = catalog()[index]
    assert len(lesson.exercises) == 2
    for exercise, expected in zip(lesson.exercises, _CALCULATIONS[index]):
        assert parse_number(exercise.answer) == F(expected)
        assert exercise.check(str(expected))
        assert not exercise.check(str(F(expected)+1))
        assert exercise.explanation and exercise.unit


def test_content_is_substantial_ordered_original_and_not_mislabeled_as_reviewed():
    items = catalog()
    assert len(items) == len({lesson.slug for lesson in items}) == 20
    assert sum(len(lesson.exercises) for lesson in items) == 40
    assert sum(len(lesson.text.split()) for lesson in items) >= 7500
    assert all(len(lesson.text.split()) >= 350 for lesson in items)
    seen = set()
    goals = default_catalog().by_id
    for lesson, article in zip(items, foundation_articles()):
        assert set(lesson.prerequisites) <= seen
        assert set(lesson.goals) <= set(goals)
        seen.add(lesson.slug)
        assert article.slug == PREFIX+lesson.slug
        assert 'LEARNING GOAL' in article.body
        assert 'WORKED EXAMPLE' in article.body or lesson.slug == 'teach-back-capstone'
        assert 'PRACTICE —' in article.body and 'WORKED ANSWERS' in article.body
        assert NOTICE in article.body
        assert article.reviewed_on == '' and article.source_publisher == 'FieldForge'
        assert 'Original FieldForge text' in article.license
        for exercise in lesson.exercises:
            assert exercise.question in article.body and exercise.explanation in article.body
        if lesson.reference_url:
            assert lesson.reference_url in article.body and 'has not reviewed or endorsed' in article.body


@pytest.mark.parametrize('text,expected', [('0.5', F(1, 2)), (' 2/4 ', F(1, 2)), ('.625', F(5, 8)),
                                         ('-2', F(-2)), ('+3.00', F(3)), ('0006/0002', F(3))])
def test_bounded_exact_number_inputs(text, expected):
    assert parse_number(text) == expected


@pytest.mark.parametrize('value', ['', ' ', 'NaN', 'inf', '1e100000000', '1/0', '2+3', '4 kg', '25%',
                                  '1,000', '1/2/3', '\x00', '1_000', '９', True, None, [], '9'*1000,
                                  '__import__("os").system("echo bad")'])
def test_invalid_responses_do_not_evaluate_code_or_allocate_huge_numbers(value):
    with pytest.raises(ValueError):
        parse_number(value)


def test_fraction_comparison_does_not_claim_rounded_decimal_is_exact():
    exercise = Exercise('One third?', '1/3', 'of one whole', 'Divide one into three equal parts.')
    assert exercise.check('2/6')
    assert not exercise.check('0.33333333')
    with pytest.raises(ValueError):
        Exercise('Bad denominator', '1/0', 'unit', 'No such value.')


@pytest.fixture(params=[True, False], ids=['fts', 'fallback'])
def library(tmp_path, request):
    return KnowledgeLibrary(tmp_path/'library #1.db', use_fts=request.param)


def test_preview_and_practice_do_not_install_or_change_personal_records(library):
    store = PathwayStore(library)
    progress = store.save('measurement', status='exploring', note='PRIVATE_PROGRESS', expected_revision=0)
    before = library.database_path.read_bytes()
    assert all(state.state == 'missing' for state in inspect_foundations(library))
    assert catalog()[0].exercises[0].check('67')
    assert library.count() == 0 and store.progress('measurement') == progress
    assert library.database_path.read_bytes() == before


def test_explicit_install_and_repeat_are_atomic_and_idempotent(library):
    before = library.database_path.read_bytes()
    for acknowledged in (False, None, 1, 'yes'):
        with pytest.raises(ValueError, match='acknowledge'):
            install_foundations(library, acknowledged=acknowledged)
    assert library.database_path.read_bytes() == before
    report = install_foundations(library, acknowledged=True)
    assert len(report.added) == 20 and not report.preserved and not report.unchanged
    before = library.database_path.read_bytes()
    again = install_foundations(library, acknowledged=True)
    assert len(again.unchanged) == 20 and not again.added
    assert library.database_path.read_bytes() == before
    assert all(row.state == 'installed' for row in inspect_foundations(library))
    assert library.search('cumulative')


def test_existing_starters_and_other_articles_are_not_replaced(library):
    install_starter(library)
    custom = KnowledgeArticle('custom', 'My article', 'Preserve my exact body\n\n', 'private exercise')
    library.upsert(custom)
    library.annotate(custom.slug, bookmarked=True, note='PRIVATE_NOTE')
    install_foundations(library, acknowledged=True)
    assert library.count() == 33  # 12 previous starters + 20 lessons + the custom record.
    assert library.get(custom.slug) == custom
    assert library.annotation(custom.slug) == {'bookmarked': True, 'note': 'PRIVATE_NOTE'}


@pytest.mark.parametrize('change', ['body', 'metadata', 'checksum', 'invalid'])
def test_conflicting_or_damaged_rows_are_reported_and_preserved(library, change):
    original = foundation_articles()[0]
    library.upsert(original)
    library.annotate(original.slug, bookmarked=True, note='Keep annotation\n\n')
    with library.connect() as db:
        if change == 'body':
            library._write(db, replace(original, body='My edited lesson'))
        elif change == 'metadata':
            library._write(db, replace(original, license='My different metadata'))
        elif change == 'checksum':
            db.execute('UPDATE knowledge_articles SET checksum=? WHERE slug=?', ('bad', original.slug))
        else:
            db.execute('UPDATE knowledge_articles SET safety_level=? WHERE slug=?', ('unknown-label', original.slug))
        before = dict(db.execute('SELECT * FROM knowledge_articles WHERE slug=?', (original.slug,)).fetchone())
    assert inspect_foundations(library)[0].state == 'preserved'
    report = install_foundations(library, acknowledged=True)
    assert report.preserved == (original.slug,) and len(report.added) == 19
    with library.connect() as db:
        assert dict(db.execute('SELECT * FROM knowledge_articles WHERE slug=?', (original.slug,)).fetchone()) == before
    assert library.annotation(original.slug)['note'] == 'Keep annotation\n\n'


def test_concurrent_installers_add_one_copy_of_each_lesson(library):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: install_foundations(library, acknowledged=True), range(2)))
    assert sum(len(report.added) for report in results) == 20
    assert sum(len(report.unchanged) for report in results) == 20
    assert library.count() == 20


def test_changed_after_inspection_is_preserved_at_install(library):
    assert inspect_foundations(library)[0].state == 'missing'
    newer = replace(foundation_articles()[0], body='Another window installed an edited edition')
    library.upsert(newer)
    report = install_foundations(library, acknowledged=True)
    assert report.preserved == (newer.slug,) and library.get(newer.slug) == newer


def test_write_failure_rolls_back_every_added_lesson(library):
    denied = foundation_articles()[3].slug
    with library.connect() as db:
        db.execute(f"CREATE TRIGGER deny_foundation BEFORE INSERT ON knowledge_articles WHEN NEW.slug='{denied}' "
                   "BEGIN SELECT RAISE(ABORT,'simulated write failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='simulated'):
        install_foundations(library, acknowledged=True)
    assert library.count() == 0
    assert not library.search('foundations')


def test_install_never_reads_note_bodies_or_writes_personal_records(library, monkeypatch):
    original = sqlite3.connect
    def connect(*args, **kwargs):
        db = original(*args, **kwargs)
        def authorize(action, table, column, *_):
            # SQLite can inspect the FK key while compiling the library upsert.
            # That key is not a private note or bookmark, and no annotation is written.
            if action == sqlite3.SQLITE_READ and table == 'knowledge_annotations' and column == 'slug':
                return sqlite3.SQLITE_OK
            if action in {sqlite3.SQLITE_READ, sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE} and table in {
                'knowledge_annotations', 'household_members', 'pathway_progress', 'pathway_reading_links'
            }:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        return db
    monkeypatch.setattr(sqlite3, 'connect', connect)
    assert len(install_foundations(library, acknowledged=True).added) == 20
    assert inspect_foundations(library)


def test_no_network_during_preview_practice_install_or_export(library, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No network expected')
    for name in ('socket', 'create_connection', 'getaddrinfo'):
        monkeypatch.setattr(socket, name, forbidden)
    assert catalog()[0].exercises[0].check('67')
    install_foundations(library, acknowledged=True)
    assert inspect_foundations(library)
    assert export_foundations(tmp_path/'offline.json').exists()


def test_export_is_deterministic_content_only_and_older_pack_compatible(tmp_path):
    first = export_foundations(tmp_path/'first.json')
    second = export_foundations(tmp_path/'second.json')
    assert first.read_bytes() == second.read_bytes()
    data = json.loads(first.read_text())
    assert data['data']['annotations'] == [] and len(data['data']['articles']) == 20
    library = KnowledgeLibrary(tmp_path/'older-reader.db')
    assert import_pack(library, first)['imported'] == 20
    assert tuple(library.get(a.slug) for a in foundation_articles()) == foundation_articles()
    with pytest.raises(FileExistsError):
        export_foundations(first)
    assert first.read_bytes() == second.read_bytes()


def test_failed_export_removes_only_its_partial_new_file(tmp_path, monkeypatch):
    from fieldforge.knowledge import foundations
    real = foundations.os.fsync
    calls = []
    def fail_on_publication(fd):
        calls.append(fd)
        if len(calls) == 2:  # First sync belongs to the temporary compatible pack writer.
            raise OSError('simulated flush failure')
        return real(fd)
    monkeypatch.setattr(foundations.os, 'fsync', fail_on_publication)
    with pytest.raises(OSError, match='flush'):
        export_foundations(tmp_path/'partial.json')
    assert not (tmp_path/'partial.json').exists()


def test_cli_refuses_unacknowledged_install_before_creating_database(tmp_path, capsys):
    missing = tmp_path/'not-created.db'
    with pytest.raises(SystemExit):
        main(['install', '--database', str(missing)])
    assert not missing.exists()
    assert main(['install', '--database', str(missing), '--acknowledge-unreviewed']) == 0
    assert 'Added 20 lessons' in capsys.readouterr().out
    with pytest.raises(ValueError):
        article_for(replace(catalog()[0], title='Not this edition'))
