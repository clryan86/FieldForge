import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fieldforge.cli import main as app_main
from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.__main__ import main
from fieldforge.knowledge.assistant import (
    GenerationCancelled,
    LocalModelError,
    OllamaClient,
    draft_answer,
)


@pytest.fixture
def library(tmp_path):
    library = KnowledgeLibrary(tmp_path / "knowledge.db")
    library.upsert(KnowledgeArticle(
        "reference", "Test reference", "Keep a printed inventory of your reference books.", "records",
        source_title="Example only", safety_level="caution", license="Test fixture",
    ))
    library.annotate("reference", bookmarked=True, note="PRIVATE NOTE MUST STAY OUT")
    return library


@pytest.fixture
def server():
    class State:
        requests = []
        entered = threading.Event()
        release = threading.Event()
        stall = None
        stall_body = False
        chunked = False
        responses = {
            "/api/status": {"cloud": {"disabled": True}},
            "/api/tags": {"models": [{"name": "example:small", "details": {"format": "gguf"}}]},
            "/api/show": {"details": {"format": "gguf"}, "capabilities": ["completion"]},
            "/api/chat": {"done": True, "message": {"role": "assistant", "content": "Keep a printed inventory. [S1]"}},
        }
        codes = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle_request(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            State.requests.append((self.path, json.loads(raw) if raw else None))
            if State.stall == self.path and not State.stall_body:
                State.entered.set()
                State.release.wait(5)
            response = State.responses.get(self.path, {})
            if callable(response):
                response = response()
            body = response if isinstance(response, bytes) else json.dumps(response).encode()
            self.send_response(State.codes.get(self.path, 200))
            if State.chunked:
                self.send_header("Transfer-Encoding", "chunked")
                body = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
            else:
                self.send_header("Content-Length", str(len(body)))
            self.send_header("Location", "http://example.invalid/should-never-be-contacted")
            self.end_headers()
            try:
                if State.stall == self.path and State.stall_body:
                    self.wfile.write(body[:1])
                    self.wfile.flush()
                    State.entered.set()
                    State.release.wait(5)
                    body = body[1:]
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        do_GET = handle_request
        do_POST = handle_request

        def log_message(self, *_args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    State.port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield State
    finally:
        State.release.set()
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def client(server, **kwargs):
    return OllamaClient(port=server.port, **kwargs)


def test_draft_uses_exact_sources_without_private_notes_or_proxies(server, library, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://example.invalid:1234")
    monkeypatch.setenv("ALL_PROXY", "http://example.invalid:1234")
    result = draft_answer(library, "printed inventory", "example:small", client(server))
    assert result.status == "draft"
    assert result.citations == ("S1",)
    assert len(result.warnings) == 1
    assert "do not verify" in result.warnings[0]
    paths = [p for p, _ in server.requests]
    assert paths == ["/api/status", "/api/tags", "/api/show", "/api/status", "/api/chat"]
    payload = server.requests[-1][1]
    assert payload["stream"] is False
    assert payload["keep_alive"] == 0
    assert "tools" not in payload
    assert "PRIVATE NOTE" not in json.dumps(payload)
    assert "PRIVATE NOTE" not in json.dumps(result.as_dict())
    source = json.loads(payload["messages"][1]["content"])["sources"][0]
    assert source["id"] == "S1"
    assert source["passage"] == result.evidence[0].passage
    assert source["safety_level"] == "caution"
    assert result.as_dict()["evidence"][0]["checksum"] == library.get("reference").checksum
    assert library.annotation("reference")["note"] == "PRIVATE NOTE MUST STAY OUT"


def test_no_evidence_never_contacts_model(library, monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *_a, **_k: pytest.fail("network access"))
    result = draft_answer(library, "unmatchedword", "anything", OllamaClient())
    assert result.status == "no_evidence"
    assert result.model is None
    assert result.evidence == ()


def test_chunked_http_responses_are_supported(server, library):
    server.chunked = True
    result = draft_answer(library, "inventory", "example:small", client(server))
    assert result.answer == "Keep a printed inventory. [S1]"


@pytest.mark.parametrize("status", [{}, {"cloud": None}, {"cloud": {"disabled": False}},
                                    {"cloud": {"disabled": "true"}}, {"cloud": {"disabled": 1}}])
def test_cloud_must_be_explicitly_disabled(server, library, status):
    server.responses["/api/status"] = status
    with pytest.raises(LocalModelError, match="OLLAMA_NO_CLOUD"):
        draft_answer(library, "inventory", "example:small", client(server))
    assert server.requests == [("/api/status", None)]


def test_older_server_without_cloud_status_fails_closed(server):
    server.codes["/api/status"] = 404
    with pytest.raises(LocalModelError, match="/api/status"):
        client(server).list_models()


def test_cloud_status_is_rechecked_before_sending_question(server, library):
    def status():
        count = sum(path == "/api/status" for path, _ in server.requests)
        return {"cloud": {"disabled": count == 1}}

    server.responses["/api/status"] = status
    with pytest.raises(LocalModelError, match="OLLAMA_NO_CLOUD"):
        draft_answer(library, "inventory", "example:small", client(server))
    assert [p for p, _ in server.requests] == ["/api/status", "/api/tags", "/api/show", "/api/status"]


@pytest.mark.parametrize("details", [
    {"remote_host": "https://ollama.com"}, {"remote_model": "aliased-cloud"},
    {"capabilities": ["embedding"]}, {"capabilities": None}, {"details": {}},
])
def test_remote_aliases_and_incompatible_models_never_receive_prompt(server, library, details):
    server.responses["/api/show"].update(details)
    with pytest.raises(LocalModelError, match="local text completion"):
        draft_answer(library, "inventory", "example:small", client(server))
    assert not any(path == "/api/chat" for path, _ in server.requests)
    assert "inventory" not in json.dumps(server.requests)


def test_missing_model_never_receives_prompt(server, library):
    with pytest.raises(LocalModelError, match="not installed"):
        draft_answer(library, "inventory", "missing", client(server))
    assert not any(path == "/api/chat" for path, _ in server.requests)


def test_model_listing_filters_cloud_and_nontext_models(server):
    server.responses["/api/tags"]["models"] += [
        {"name": "remote", "details": {"format": "gguf"}, "remote_model": "hidden-remote"},
        {"name": "embed", "details": {"format": "gguf"}, "capabilities": ["embedding"]},
        {"name": "other", "details": {"format": "other"}},
        {"name": "malformed", "details": None},
    ]
    assert client(server).list_models() == ["example:small"]


@pytest.mark.parametrize("code", [301, 302, 307, 500])
def test_redirects_and_http_errors_are_not_followed(server, code):
    server.codes["/api/tags"] = code
    with pytest.raises(LocalModelError, match=f"HTTP {code}"):
        client(server).list_models()
    assert [p for p, _ in server.requests] == ["/api/status", "/api/tags"]


@pytest.mark.parametrize("response", [b"not json", b"\xff", b"[]", {"error": "failed"}, {"models": None}])
def test_invalid_server_responses_have_actionable_errors(server, response):
    server.responses["/api/tags"] = response
    with pytest.raises(LocalModelError):
        client(server).list_models()


def test_response_size_is_bounded(server, monkeypatch):
    monkeypatch.setattr("fieldforge.knowledge.assistant._MAX_RESPONSE", 100)
    server.responses["/api/tags"] = b" " * 101
    with pytest.raises(LocalModelError, match="size limit"):
        client(server).list_models()


@pytest.mark.parametrize("reply", [
    {"done": False}, {"remote_host": "https://ollama.com"},
    {"message": {"role": "assistant", "content": "", "thinking": "no visible answer"}},
    {"message": {"role": "assistant", "content": "x" * 16_001}},
    {"message": {"role": "assistant", "content": "draft", "tool_calls": [{"name": "execute"}]}},
    {"message": {"role": "user", "content": "wrong role"}},
])
def test_incomplete_empty_oversized_and_tool_responses_are_rejected(server, library, reply):
    server.responses["/api/chat"].update(reply)
    with pytest.raises(LocalModelError):
        draft_answer(library, "inventory", "example:small", client(server))


def test_bad_citations_and_truncated_answer_are_visible(server, library):
    server.responses["/api/chat"]["message"]["content"] = "Unverified claim. [S99] [S01]"
    server.responses["/api/chat"]["done_reason"] = "length"
    result = draft_answer(library, "inventory", "example:small", client(server))
    assert result.citations == ()
    assert any("no recognized" in w for w in result.warnings)
    assert any("S99" in w and "S01" in w for w in result.warnings)
    assert any("incomplete" in w for w in result.warnings)


@pytest.mark.parametrize("body", [False, True])
def test_cancel_interrupts_stalled_response(server, library, body):
    server.stall = "/api/chat"
    server.stall_body = body
    cancelled = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(draft_answer, library, "inventory", "example:small", client(server), cancel=cancelled)
        assert server.entered.wait(2)
        cancelled.set()
        with pytest.raises(GenerationCancelled):
            future.result(timeout=2)


@pytest.mark.parametrize("body", [False, True])
def test_deadline_interrupts_stalled_model(server, library, body):
    server.stall = "/api/chat"
    server.stall_body = body
    started = time.monotonic()
    with pytest.raises(LocalModelError, match="timed out"):
        draft_answer(library, "inventory", "example:small", client(server, timeout=0.2))
    assert time.monotonic() - started < 2


@pytest.mark.parametrize("options", [{"port": 0}, {"port": True}, {"port": 65536},
                                     {"timeout": float("nan")}, {"timeout": 301}])
def test_invalid_configuration_is_rejected(options):
    with pytest.raises(ValueError):
        OllamaClient(**options)


def test_both_clis_support_local_drafts_and_model_listing(server, library, capsys):
    for command, models_command in [(main, "models"), (app_main, "local-models")]:
        common = ["--database", str(library.database_path)]
        assert command(common + [models_command, "--port", str(server.port)]) == 0
        assert json.loads(capsys.readouterr().out)["models"] == ["example:small"]
        assert command(common + ["ask", "inventory", "--model", "example:small", "--port", str(server.port)]) == 0
        assert json.loads(capsys.readouterr().out)["evidence"][0]["id"] == "S1"


def test_cli_reports_local_server_failure_without_traceback(server, library, capsys):
    server.responses["/api/status"] = {"cloud": {"disabled": False}}
    with pytest.raises(SystemExit) as error:
        app_main(["--database", str(library.database_path), "ask", "inventory", "--model", "example:small", "--port", str(server.port)])
    assert error.value.code == 2
    assert "OLLAMA_NO_CLOUD" in capsys.readouterr().err
