import builtins
import sys
from types import SimpleNamespace

import pytest

from fieldforge_gps.session import Session, open_serial

from .test_nmea import rmc


def test_optional_serial_adapter_control_settings(monkeypatch):
    made = []

    class Receiver:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.events = []
            made.append(self)

        def open(self):
            self.events.append("open")
            assert self.port == "COM4"
            assert self.dtr is False and self.rts is False

        def reset_input_buffer(self):
            self.events.append("clear-input")

        def close(self):
            self.events.append("close")

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Receiver))
    receiver = open_serial("com4", 9600)
    assert receiver.options == dict(
        port=None,
        baudrate=9600,
        timeout=0.2,
        write_timeout=0.2,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    assert receiver.events == ["open", "clear-input"]
    receiver.close()


def test_missing_pyserial_explicit_diagnostic(monkeypatch):
    original = builtins.__import__

    def no_serial(name, *args, **kwargs):
        if name == "serial":
            raise ImportError("absent")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_serial)
    with pytest.raises(RuntimeError, match="pySerial"):
        open_serial("COM4", 9600)


def test_wrong_serial_module_rejected(monkeypatch):
    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace())
    with pytest.raises(RuntimeError, match="not compatible"):
        open_serial("COM4", 9600)


def test_serial_failed_open_closes(monkeypatch):
    receivers = []

    class Receiver:
        def __init__(self, **kwargs):
            self.closed = False
            receivers.append(self)

        def open(self):
            raise OSError("failed")

        def close(self):
            self.closed = True

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Receiver))
    with pytest.raises(OSError):
        open_serial("COM4", 9600)
    assert receivers[0].closed


def test_late_data_after_stop_is_ignored():
    s = Session("recorded")
    s.stop()
    s._feed(rmc())
    assert s.snapshot().position is None
    assert s.snapshot().accepted == 0


def test_changed_recording_cannot_be_exported(tmp_path, monkeypatch):
    import fieldforge_gps.session as module

    p = tmp_path / "changed.nmea"
    p.write_bytes(rmc())
    original = module._recording_stream

    class Changing:
        def __init__(self, stream):
            self.stream = stream
            self.once = False

        def read(self, n):
            value = self.stream.read(n)
            if not self.once:
                self.once = True
                with p.open("ab") as writer:
                    writer.write(rmc(time="120001"))
            return value

        def fileno(self):
            return self.stream.fileno()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

    def changed(path):
        stream, info = original(path)
        return Changing(stream), info

    monkeypatch.setattr(module, "_recording_stream", changed)
    s = Session("recorded")
    s.start_recording(p)
    assert s.wait(1)
    assert s.snapshot().position is None
    assert not s.snapshot().recording_sha256
