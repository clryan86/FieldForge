"""Saved-message search preserves current private audiences and unread state."""

import http.client
import json
import sqlite3

import pytest
import test_commons_chat

from fieldforge.online.account_lifecycle import AccountLifecycleStore
from fieldforge.online.accounts import AccountStore
from fieldforge.online.chat_store import SESSION_SECONDS, ChatError
from fieldforge.online.commons_preview import COOKIE_NAME
from fieldforge.online.owner import OwnerStore
from fieldforge.online.private_chat import PRIVATE_SEARCH_PAGE_SIZE, PrivateChatStore

preview_server = test_commons_chat.preview_server
SEARCH_API = "/api/commons/private/search"
PASSWORD = "TEST search only: river trail passphrase"
INVALID_CURSORS = (True, False, 0, -1, 1.0, "1", [], {}, 2**53, 2**63, 2**80)


def make_store(tmp_path, store_class=PrivateChatStore):
    now = [1000.0]
    store = store_class(tmp_path / "search.sqlite3", clock=lambda: now[0])
    store.test_clock = now
    return store


@pytest.fixture
def store(tmp_path):
    return make_store(tmp_path)


def people(store):
    if not hasattr(store, "test_clock"):
        store.test_clock = [1000.0]
        store.clock = lambda: store.test_clock[0]
    return [store.join(name, "") for name in
            ("TEST Alice", "TEST Bob", "TEST Carol", "TEST Outside")]


def key(store):
    store.test_search_sequence = getattr(store, "test_search_sequence", 0) + 1
    return f"{store.test_search_sequence:032x}"


def conversation(store, owner, recipients, *, title="TEST search subject", accept=True):
    thread = store.private_create(owner[0], title, "group" if len(recipients) > 1 else "direct",
                                  [person[1]["id"] for person in recipients], key(store))["thread"]
    if accept:
        for person in recipients:
            store.private_accept(person[0], thread)
    return thread


def message(store, author, thread, body="TEST matching body", lifetime="saved"):
    store.test_clock[0] += 2
    return store.private_send(author[0], thread, body, lifetime, key(store))["id"]


def ids(page):
    return [item["id"] for item in page["results"]]


def denied(operation, status):
    with pytest.raises(ChatError) as error:
        operation()
    assert error.value.status == status
    return str(error.value)


def snapshot(store):
    with sqlite3.connect(store.path) as db:
        return {
            "messages": db.execute("SELECT * FROM private_messages ORDER BY id").fetchall(),
            "deliveries": db.execute("SELECT * FROM private_deliveries ORDER BY message,recipient").fetchall(),
            "schema": db.execute("SELECT * FROM sqlite_master ORDER BY name").fetchall(),
            "version": db.execute("PRAGMA user_version").fetchone(),
        }


def test_unicode_casefold_and_literal_body_matching_preserve_result_metadata(store):
    alice, bob, carol, _ = people(store)
    direct = conversation(store, alice, [bob], title="TEST title-only-secret")
    group = conversation(store, carol, [alice, bob], title="TEST field group")
    notes = [
        (alice, direct, "TEST Straße and ΣΟΣ"),
        (bob, group, "TEST 100%_ready a  b and [x].* O'Brien"),
        (carol, group, "TEST 100Xready a b and xyz"),
        (alice, direct, "TEST ordinary separate body"),
    ]
    sent = [message(store, author, thread, body) for author, thread, body in notes]
    for query, expected in (("STRASSE", [sent[0]]), ("σος", [sent[0]]),
                            ("%", [sent[1]]), ("_", [sent[1]]), ("[x].*", [sent[1]]),
                            ("a  b", [sent[1]]), ("O'Brien", [sent[1]]),
                            ("' OR 1=1--", []), ("title-only-secret", []), ("TEST Carol", [])):
        assert ids(store.private_search(bob[0], query)) == expected

    page = store.private_search(bob[0], "  TeSt  ")
    assert set(page) == {"query", "thread", "before", "older_before", "results"}
    assert page["query"] == "TeSt" and page["thread"] is None and page["before"] is None
    assert page["older_before"] is None
    assert ids(page) == list(reversed(sent))
    for result, (author, thread, body) in zip(page["results"], reversed(notes)):
        assert set(result) == {"id", "thread", "title", "kind", "author", "name", "created", "body", "own"}
        assert result["thread"] == thread and result["body"] == body
        assert result["name"] == author[1]["name"] and result["author"] == author[1]["id"]
        assert result["own"] is (author is bob)
        assert result["title"] == ("TEST field group" if thread == group else "TEST title-only-secret")
        assert result["kind"] == ("group" if thread == group else "direct")
        assert isinstance(result["created"], float)


@pytest.mark.parametrize("query", [
    None, True, 1, 1.0, [], {}, "", "   ", "x" * 101, "😀" * 101,
    "a\x00b", "a\tb", "a\nb", "a\rb", "a\x7fb", "a\x85b", "a\u2028b", "a\u2029b",
    "a\u202eb", "a\u2069b", "a\ud800b", "a\uffffb", "\nTEST", "TEST\t",
])
def test_search_requires_bounded_plain_single_line_text(store, query):
    alice, *_ = people(store)
    denied(lambda: store.private_search(alice[0], query), 400)


def test_query_limit_counts_unicode_characters_before_casefold(store):
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    emoji = message(store, alice, thread, "😀" * 100)
    expanding = message(store, alice, thread, "ß" * 100)
    assert ids(store.private_search(bob[0], "  " + "😀" * 100 + "  ")) == [emoji]
    assert ids(store.private_search(bob[0], "ß" * 100)) == [expanding]


def test_search_pages_follow_global_ids_across_threads_and_new_arrivals(store):
    alice, bob, carol, outsider = people(store)
    direct = conversation(store, alice, [bob])
    other = conversation(store, carol, [bob])
    foreign = conversation(store, outsider, [alice], title="TEST forbidden title")
    sent, foreign_ids = [], []
    for number in range(45):
        sent.append(message(store, alice if number % 2 else carol,
                            direct if number % 2 else other, f"TEST beacon {number}"))
        foreign_ids.append(message(store, outsider, foreign, "TEST beacon forbidden body"))
    latest = store.private_search(bob[0], "beacon")
    assert PRIVATE_SEARCH_PAGE_SIZE == 20
    assert ids(latest) == sent[-20:][::-1]
    assert latest["older_before"] == sent[-20]
    second = store.private_search(bob[0], "beacon", before=latest["older_before"])
    assert second["before"] == sent[-20]
    assert ids(second) == sent[-40:-20][::-1]
    assert second["older_before"] == sent[-40]
    final = store.private_search(bob[0], "beacon", before=second["older_before"])
    assert ids(final) == sent[:-40][::-1] and final["older_before"] is None
    assert "forbidden" not in json.dumps([latest, second, final])
    assert len(set(ids(latest) + ids(second) + ids(final))) == 45

    # A cursor may belong to another conversation or no longer exist. It is
    # just an exclusive boundary, with authorization repeated on every page.
    bounded = store.private_search(bob[0], "beacon", before=foreign_ids[18])
    assert ids(bounded) == [item for item in reversed(sent) if item < foreign_ids[18]][:20]
    newest = message(store, alice, direct, "TEST beacon new arrival")
    assert store.private_search(bob[0], "beacon", before=latest["older_before"]) == second
    assert ids(store.private_search(bob[0], "beacon", thread=direct)) == [newest] + sent[1::2][::-1][:19]
    scoped = store.private_search(bob[0], "beacon", thread=other)
    assert scoped["thread"] == other and ids(scoped) == sent[::2][-20:][::-1]
    assert scoped["older_before"] == sent[::2][-20]


@pytest.mark.parametrize("count", [0, 20, 21, 40])
def test_empty_and_exact_result_pages_have_no_phantom_cursor(store, count):
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    sent = [message(store, alice, thread) for _ in range(count)]
    page = store.private_search(bob[0], "matching", thread=None, before=None)
    assert ids(page) == sent[-20:][::-1]
    assert page["older_before"] == (sent[-20] if count > 20 else None)
    if count > 20:
        older = store.private_search(bob[0], "matching", before=page["older_before"])
        assert ids(older) == sent[:-20][::-1] and older["older_before"] is None
    first = store.private_search(bob[0], "matching", before=1)
    assert first["results"] == [] and first["before"] == 1 and first["older_before"] is None
    assert store.private_search(bob[0], "absent word")["older_before"] is None


@pytest.mark.parametrize("before", INVALID_CURSORS)
def test_cursors_are_positive_exact_javascript_safe_integers(store, before):
    alice, *_ = people(store)
    denied(lambda: store.private_search(alice[0], "TEST", before=before), 400)


def test_largest_javascript_safe_cursor_is_accepted(store):
    alice, *_ = people(store)
    page = store.private_search(alice[0], "TEST", before=2**53 - 1)
    assert page["before"] == 2**53 - 1 and page["results"] == []


@pytest.mark.parametrize("reverse_block", [False, True])
def test_visibility_and_matching_precede_limits_even_past_a_full_history_page(store, reverse_block):
    alice, bob, carol, _ = people(store)
    thread = conversation(store, alice, [bob, carol])
    own = message(store, bob, thread, "TEST beacon own oldest")
    visible = [own] + [message(store, carol, thread, "TEST beacon old saved") for _ in range(21)]
    missing = []
    for number in range(178):
        variant = number % 4
        author = alice if variant == 0 else carol
        identifier = message(store, author, thread,
                             "TEST unrelated newer body" if variant == 1 else "TEST beacon hidden newer body",
                             "view_once" if variant == 2 else "saved")
        if variant == 3:
            missing.append(identifier)
    with sqlite3.connect(store.path) as db:
        db.executemany("DELETE FROM private_deliveries WHERE recipient=? AND message=?",
                       [(bob[1]["id"], identifier) for identifier in missing])
    blocker, target = (alice, bob) if reverse_block else (bob, alice)
    store.block(blocker[0], target[1]["id"], True)
    before = snapshot(store)
    page = store.private_search(bob[0], "beacon", thread=thread)
    assert ids(page) == visible[-20:][::-1]
    assert page["older_before"] == visible[-20]
    older = store.private_search(bob[0], "beacon", thread=thread, before=page["older_before"])
    assert ids(older) == visible[:-20][::-1] and older["older_before"] is None
    assert older["results"][-1]["own"] is True
    assert "hidden newer body" not in json.dumps([page, older])
    assert snapshot(store) == before


def test_search_finds_old_matches_beyond_one_hundred_visible_nonmatching_saved_messages(store):
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    matching = [message(store, alice, thread, "TEST old beacon") for _ in range(23)]
    for _ in range(177):
        message(store, alice, thread, "TEST newer unrelated body")
    page = store.private_search(bob[0], "beacon")
    assert ids(page) == matching[-20:][::-1] and page["older_before"] == matching[-20]
    older = store.private_search(bob[0], "beacon", before=page["older_before"])
    assert ids(older) == matching[:-20][::-1] and older["older_before"] is None
    # Retention may prune a previously issued cursor. It must never be required
    # to remain in storage or cause already pruned bodies to reappear.
    for _ in range(25):
        message(store, alice, thread, "TEST new unrelated body after retention")
    assert store.private_search(bob[0], "beacon", before=page["older_before"])["results"] == []


def test_invited_left_outsider_and_invalid_scopes_cannot_reveal_bodies_or_titles(store):
    alice, bob, carol, outsider = people(store)
    accepted = conversation(store, alice, [bob], title="TEST accepted subject")
    invited = conversation(store, carol, [bob], title="TEST sealed invitation title", accept=False)
    saved = message(store, alice, accepted, "TEST beacon visible")
    message(store, carol, invited, "TEST beacon invitation secret")
    assert ids(store.private_search(bob[0], "beacon")) == [saved]
    for viewer, scope in ((bob, invited), (outsider, accepted), (outsider, invited), (bob, "f" * 24)):
        error = denied(lambda: store.private_search(viewer[0], "beacon", scope, 2**53 - 1), 404)
        assert "sealed" not in error and "secret" not in error and "accepted subject" not in error
    assert store.private_search(outsider[0], "beacon")["results"] == []
    for invalid in ("", "short", "x" * 24, False, 5, [], {}):
        denied(lambda: store.private_search(bob[0], "beacon", thread=invalid), 400)
    store.private_leave(bob[0], accepted)
    assert store.private_search(bob[0], "beacon")["results"] == []
    denied(lambda: store.private_search(bob[0], "beacon", thread=accepted), 404)
    store.private_accept(bob[0], invited)
    assert [item["body"] for item in store.private_search(bob[0], "beacon")["results"]] == [
        "TEST beacon invitation secret",
    ]


def test_search_never_opens_once_marks_saved_read_or_persists_query_content(store):
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    sent = [message(store, alice, thread, f"TEST payload saved {index}") for index in range(25)]
    sealed = message(store, alice, thread, "TEST payload never open", "view_once")
    own_sealed = message(store, bob, thread, "TEST payload never return own", "view_once")
    before = snapshot(store)
    assert all(row[2] is None for row in before["deliveries"])
    for viewer in (alice, bob):
        page = store.private_search(viewer[0], "payload")
        assert ids(page) == sent[-20:][::-1]
        assert not {sealed, own_sealed} & set(ids(page))
        assert "never" not in json.dumps(page)
        assert store.private_search(viewer[0], "TEST QUERY MUST NEVER BE STORED")["results"] == []
    assert snapshot(store) == before
    assert b"TEST QUERY MUST NEVER BE STORED" not in store.path.read_bytes()
    assert store.private_inbox(bob[0])["threads"][0]["unread"] == 26
    assert store.private_open_once(bob[0], thread, sealed)["body"] == "TEST payload never open"


def test_older_search_rechecks_withdrawal_and_runs_once_expiry(store, monkeypatch):
    monkeypatch.setattr("fieldforge.online.private_chat.VIEW_ONCE_SECONDS", 100)
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    withdrawn = message(store, alice, thread, "TEST beacon withdrawn later")
    once = message(store, alice, thread, "TEST beacon expires unseen", "view_once")
    for _ in range(21):
        message(store, alice, thread, "TEST beacon retained saved")
    page = store.private_search(bob[0], "beacon")
    cursor = page["older_before"]
    assert withdrawn in ids(store.private_search(bob[0], "beacon", before=cursor))
    store.private_delete(alice[0], thread, withdrawn)
    store.test_clock[0] += 101
    refreshed = store.private_search(bob[0], "beacon", before=cursor)
    assert withdrawn not in ids(refreshed) and refreshed["older_before"] is None
    assert "withdrawn later" not in json.dumps(refreshed)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT body,redacted FROM private_messages WHERE id=?", (once,)).fetchone() == ("", "expired")
    store.block(alice[0], bob[1]["id"], True)
    assert store.private_search(bob[0], "beacon", before=cursor)["results"] == []


@pytest.mark.parametrize("store_class", [PrivateChatStore, AccountStore, OwnerStore, AccountLifecycleStore])
def test_each_store_layer_reauthenticates_expiry_and_revocation_on_every_search(tmp_path, store_class):
    store = make_store(tmp_path, store_class)
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    message(store, alice, thread)
    assert store.private_search(bob[0], "matching")["results"]
    denied(lambda: store.private_search(None, "matching"), 401)
    denied(lambda: store.private_search("invalid", "matching", thread=thread), 401)
    store.leave(bob[0])
    denied(lambda: store.private_search(bob[0], "matching", thread=thread), 401)
    store.test_clock[0] += SESSION_SECONDS
    denied(lambda: store.private_search(alice[0], "matching"), 401)


@pytest.mark.parametrize("store_class", [OwnerStore, AccountLifecycleStore])
def test_search_respects_current_suspension_even_with_a_still_valid_token(tmp_path, store_class):
    store = make_store(tmp_path, store_class)
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    message(store, alice, thread)
    assert store.private_search(bob[0], "matching")["results"]
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO participant_controls VALUES(?,1,?,?)",
                   (bob[1]["id"], "TEST suspension", store.clock()))
    for scope in (None, thread):
        denied(lambda: store.private_search(bob[0], "matching", thread=scope), 401)


def test_account_closure_withdraws_searchable_bodies_and_revokes_access(tmp_path):
    store = make_store(tmp_path, AccountLifecycleStore)
    alice_token, alice_data = store.account_register("TEST_Alice", PASSWORD, "")
    bob_token, bob_data = store.account_register("TEST_Bob", PASSWORD, "")
    alice, bob = (alice_token, alice_data["viewer"]), (bob_token, bob_data["viewer"])
    thread = conversation(store, alice, [bob])
    closed = message(store, alice, thread, "TEST beacon closed account body")
    kept = message(store, bob, thread, "TEST beacon still retained")
    assert ids(store.private_search(bob[0], "beacon")) == [kept, closed]
    store.account_close(alice[0], PASSWORD, "TEST_Alice", True)
    denied(lambda: store.private_search(alice[0], "beacon"), 401)
    assert ids(store.private_search(bob[0], "beacon", thread=thread)) == [kept]
    assert "closed account body" not in json.dumps(store.private_search(bob[0], "beacon"))


def request(server, payload, person=None, *, participant=None, origin=True, custom=True,
            method="POST", path=SEARCH_API):
    host = f"127.0.0.1:{server.server_address[1]}"
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = "http://" + host if origin is True else origin
    if custom:
        headers["X-FieldForge-Chat"] = "preview-v1"
    if person:
        headers["Cookie"] = f"{COOKIE_NAME}={person[0]}"
    if participant is not None:
        headers["X-FieldForge-Participant"] = participant
    connection = http.client.HTTPConnection(host, timeout=10)
    try:
        connection.request(method, path, json.dumps(payload), headers)
        response = connection.getresponse()
        body = response.read()
        return response.status, dict(response.getheaders()), json.loads(body) if body else None
    finally:
        connection.close()


def test_http_search_uses_post_origin_session_participant_and_no_store_controls(preview_server):
    store = preview_server.app.store
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    sent = message(store, alice, thread)
    payload = {"query": "matching"}
    for options in ({"origin": False}, {"origin": "https://attacker.invalid"}, {"custom": False},
                    *[{"method": method} for method in ("GET", "HEAD", "OPTIONS", "PUT", "DELETE", "PATCH")]):
        assert request(preview_server, payload, bob, **options)[0] == 403
    assert request(preview_server, payload)[0] == 401
    for identity in ("malformed", alice[1]["id"]):
        assert request(preview_server, payload, bob, participant=identity)[0] == 401
    status, headers, result = request(preview_server, payload, bob, participant=bob[1]["id"])
    assert status == 200 and ids(result) == [sent]
    assert headers["Cache-Control"] == "no-store"
    assert "Set-Cookie" not in headers and "Access-Control-Allow-Origin" not in headers
    assert "token" not in json.dumps(result)
    assert request(preview_server, payload, bob, path=SEARCH_API + "/extra")[0] == 404
    assert request(preview_server, payload, bob, path=SEARCH_API + "?query=matching")[0] == 400


def test_http_search_schema_requires_query_allows_null_options_and_rejects_unknown_fields(preview_server):
    store = preview_server.app.store
    alice, bob, _, outsider = people(store)
    thread = conversation(store, alice, [bob], accept=False)
    sent = message(store, alice, thread)
    for payload in ({}, {"before": 1}, {"query": None}, {"query": []}, {"query": "x\ny"},
                    {"query": "x", "participant": alice[1]["id"]}, {"query": "x", "limit": 100},
                    {"query": "x", "offset": 0}, {"query": "x", "thread": []}, [], None):
        assert request(preview_server, payload, bob)[0] == 400
    for before in INVALID_CURSORS:
        assert request(preview_server, {"query": "matching", "before": before}, bob)[0] == 400
    assert request(preview_server, {"query": "matching", "thread": thread}, bob)[0] == 404
    assert request(preview_server, {"query": "matching", "thread": thread}, outsider)[0] == 404
    assert request(preview_server, {"query": "matching"}, bob)[2]["results"] == []
    store.private_accept(bob[0], thread)
    for payload in ({"query": "matching"}, {"query": "matching", "thread": None, "before": None},
                    {"query": "matching", "thread": thread}, {"query": "matching", "before": 2**53 - 1}):
        status, _, result = request(preview_server, payload, bob)
        assert status == 200 and ids(result) == [sent]
    before = snapshot(store)
    request(preview_server, {"query": "matching"}, bob)
    assert snapshot(store) == before
    store.leave(bob[0])
    assert request(preview_server, {"query": "matching"}, bob)[0] == 401
