"""Source/frozen command decisions; real frozen execution is required separately in CI."""

import json
import os
import sys
from pathlib import Path

import pytest

from fieldforge import launcher, package_checks, runtime
from fieldforge.core import recovery


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    root = tmp_path / "Bundle with spaces résumé"
    root.mkdir()
    for name in ("FieldForge.exe", "FieldForgeTools.exe"):
        (root / name).write_bytes(b"Test filename only, not an executable")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(root / "FieldForge.exe"))
    return root


def test_source_commands_keep_existing_python_module_contract(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert runtime.pdf_command() == [sys.executable, "-m", "fieldforge.knowledge.pdf_worker"]
    assert runtime.desktop_command() == [sys.executable, "-m", "fieldforge.ui.desktop"]


def test_frozen_roles_are_fixed_siblings_not_python_or_arbitrary_modules(frozen):
    assert runtime.pdf_command() == [str(frozen / "FieldForgeTools.exe"), "--pdf-worker"]
    assert runtime.desktop_command() == [str(frozen / "FieldForge.exe")]


def test_helper_can_start_gui_without_trying_to_relaunch_itself(frozen, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(frozen / "FieldForgeTools.exe"))
    assert runtime.desktop_command() == [str(frozen / "FieldForge.exe")]


@pytest.mark.parametrize("name,action", [("FieldForge.exe", runtime.desktop_command),
                                        ("FieldForgeTools.exe", runtime.pdf_command)])
def test_missing_sibling_fails_explicitly_without_system_python_fallback(frozen, name, action):
    (frozen / name).unlink()
    with pytest.raises(FileNotFoundError, match="Extract the whole FieldForge"):
        action()


def test_recovered_child_environment_is_independent_and_parent_unchanged(frozen, monkeypatch, tmp_path):
    monkeypatch.setenv("FIELDFORGE_DB", "prior-database")
    monkeypatch.delenv("PYINSTALLER_RESET_ENVIRONMENT", raising=False)
    before = dict(os.environ)
    path = tmp_path / "Recovered data.db"
    environment = runtime.desktop_environment(path)
    assert environment["FIELDFORGE_DB"] == str(path.resolve())
    assert environment["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert dict(os.environ) == before


def test_actual_recovery_service_uses_graphical_exe_and_fixed_argv(frozen, monkeypatch, tmp_path):
    path = tmp_path / "Restored & checked.db"
    path.write_bytes(b"dummy for launch contract test")
    calls = []
    monkeypatch.setattr(recovery.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)) or "child")
    assert recovery.launch_recovered_copy(path) == "child"
    args, options = calls[0]
    assert args == ([str(frozen / "FieldForge.exe")],)
    assert options["env"]["FIELDFORGE_DB"] == str(path)
    assert options["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert options["shell"] is False


def test_missing_recovery_database_never_starts_a_process(frozen, monkeypatch, tmp_path):
    monkeypatch.setattr(recovery.subprocess, "Popen", lambda *_a, **_k: pytest.fail("must not start"))
    with pytest.raises(FileNotFoundError):
        recovery.launch_recovered_copy(tmp_path / "missing.db")


def test_build_identity_reads_bounded_known_fields_without_defaulting_to_verified(frozen, monkeypatch):
    module = frozen / "runtime.py"
    monkeypatch.setattr(runtime, "__file__", str(module))
    missing = runtime.build_identity()
    assert "unavailable" in missing["target"]
    data = {"version": "0.1.0", "source_commit": "a"*40, "branch_commit": "b"*40, "target": "Windows x64 development"}
    (frozen / "_build.json").write_text(json.dumps(data), encoding="utf-8")
    assert runtime.build_identity() == data
    for altered in ({**data, "source_commit": "not a hash"}, {**data, "target": "bad\nline"},
                    {**data, "extra": "unexpected"}, {**data, "target": 1}):
        (frozen / "_build.json").write_text(json.dumps(altered), encoding="utf-8")
        assert "unavailable" in runtime.build_identity()["target"]
    (frozen / "_build.json").write_bytes(b"x"*4097)
    assert "unavailable" in runtime.build_identity()["target"]


def test_source_identity_does_not_trust_a_stray_build_file(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(runtime, "__file__", str(tmp_path / "runtime.py"))
    (tmp_path / "_build.json").write_text('{"source_commit":"pretend"}')
    assert runtime.build_identity()["source_commit"] == "Not recorded in this source build"


@pytest.mark.parametrize("option", [None, "environment", "argument"])
def test_launcher_database_choice_matches_existing_windows_launcher(tmp_path, monkeypatch, option):
    from fieldforge.ui import desktop
    monkeypatch.delenv("FIELDFORGE_DB", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    calls = []
    monkeypatch.setattr(desktop, "run", lambda: calls.append(desktop._database_path()))
    arguments = []
    expected = tmp_path / ".fieldforge" / "playground.db"
    if option in {"environment", "argument"}:
        monkeypatch.setenv("FIELDFORGE_DB", str(tmp_path / "chosen-environment.db"))
        expected = tmp_path / "chosen-environment.db"
    if option == "argument":
        expected = tmp_path / "explicit résumé.db"
        arguments = ["--database", str(expected)]
    assert launcher.main(arguments) == 0
    assert calls == [expected]
    assert not expected.exists()  # The mocked entry point did not initialize anything.


def test_recovery_only_launcher_does_not_call_main_desktop(tmp_path, monkeypatch):
    from fieldforge.ui import desktop
    from fieldforge.ui import recovery as screen
    path = tmp_path / "not-created.db"
    monkeypatch.setattr(desktop, "run", lambda: pytest.fail("wrong entry point"))
    calls = []
    monkeypatch.setattr(screen, "run", lambda: calls.append(os.environ["FIELDFORGE_DB"]))
    assert launcher.main(["--recovery", "--database", str(path)]) == 0
    assert calls == [str(path)] and not path.exists()


def test_start_failure_is_visible_nonzero_and_does_not_reset_data(tmp_path, monkeypatch):
    from tkinter import messagebox

    from fieldforge.ui import desktop
    path = tmp_path / "data.db"
    path.write_bytes(b"retain this data")
    monkeypatch.setattr(desktop, "run", lambda: (_ for _ in ()).throw(ValueError("Simulated startup problem")))
    messages = []
    monkeypatch.setattr(messagebox, "showerror", lambda *args, **kwargs: messages.append(args))
    assert launcher.main(["--database", str(path)]) == 1
    assert "No data reset" in messages[0][1]
    assert path.read_bytes() == b"retain this data"


@pytest.mark.parametrize("args", [["-m", "os"], ["--pdf-worker"], ["--unknown"], ["--database"]])
def test_graphical_launcher_never_dispatches_arbitrary_module_or_worker(args, monkeypatch):
    monkeypatch.setenv("FIELDFORGE_DB", "unchanged")
    with pytest.raises(SystemExit) as error:
        launcher.main(args)
    assert error.value.code == 2
    assert os.environ["FIELDFORGE_DB"] == "unchanged"


def test_console_helper_dispatches_only_fixed_pdf_role(monkeypatch):
    from fieldforge.knowledge import pdf_worker
    calls = []
    monkeypatch.setattr(pdf_worker, "main", lambda: calls.append(True) or 7)
    monkeypatch.setattr(package_checks, "verify_installation", lambda: pytest.fail("must not run diagnostic"))
    assert package_checks.main(["--pdf-worker"]) == 7 and calls == [True]


@pytest.mark.parametrize("args", [[], ["--pdf-worker", "--verify-installation"], ["-m", "os"]])
def test_helper_does_not_start_ui_or_execute_arbitrary_args(args, monkeypatch):
    monkeypatch.setattr(package_checks, "verify_installation", lambda: pytest.fail("must not execute"))
    with pytest.raises(SystemExit) as error:
        package_checks.main(args)
    assert error.value.code == 2


def test_failed_install_diagnostic_reports_nonzero_not_fake_success(monkeypatch, capsys):
    monkeypatch.setattr(package_checks, "verify_installation", lambda: (_ for _ in ()).throw(ValueError("test failure")))
    assert package_checks.main(["--verify-installation"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "failed", "error": "ValueError: test failure"}
