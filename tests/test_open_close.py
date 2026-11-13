"""Obrir i tancar el programa al portable: tancar la finestra l'atura
(auto_shutdown) i un doble clic l'obre, o només n'obre la finestra si ja
corre (obrir_planificador). Abans el servidor quedava viu amagat en tancar
el navegador i cada doble clic el matava i el tornava a engegar."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from src.services import auto_shutdown, portable_launcher
from src.tools import obrir_planificador as launcher


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _watch(counts, grace=20, startup_grace=120, poll=2):
    """Executa el vigilant amb una seqüència de finestres connectades i
    retorna quants segons ha tardat a decidir aturar (None si no atura)."""
    clock = _FakeClock()
    seq = iter(counts)

    def count():
        try:
            return next(seq)
        except StopIteration:
            raise TimeoutError

    try:
        auto_shutdown.wait_until_idle(count, grace=grace, startup_grace=startup_grace,
                                      poll=poll, clock=clock, sleep=clock.sleep)
    except TimeoutError:
        return None
    return clock.now


def test_closing_the_window_stops_after_grace():
    # 1 finestra durant 10 s, després cap: s'atura 20 s després de tancar-la.
    assert _watch([1] * 5 + [0] * 20) == 10 + 20


def test_reload_does_not_stop():
    # Una recàrrega desconnecta uns segons i torna: no s'atura.
    assert _watch([1] * 5 + [0] * 3 + [1] * 50) is None


def test_never_opened_window_stops_after_startup_grace():
    assert _watch([0] * 100) == 120


def test_unknown_window_count_never_stops():
    # Si l'API interna de Streamlit canvia, val més no apagar mai.
    assert _watch([None] * 200) is None


def test_watchdog_only_runs_when_the_launcher_asks(monkeypatch):
    monkeypatch.delenv("PLANNER_AUTO_SHUTDOWN", raising=False)
    monkeypatch.setattr(auto_shutdown, "_started", False)
    auto_shutdown.start()
    assert auto_shutdown._started is False


def test_watchdog_always_runs_in_the_portable(monkeypatch):
    # Sense botó de tancar, al portable és l'única manera d'aturar-lo — també
    # si l'ha engegat un llançador antic que no posa la variable.
    monkeypatch.delenv("PLANNER_AUTO_SHUTDOWN", raising=False)
    monkeypatch.setattr(auto_shutdown, "_started", False)
    started = []
    monkeypatch.setattr(
        auto_shutdown.threading, "Thread",
        lambda **kw: SimpleNamespace(start=lambda: started.append(kw["name"])),
    )
    auto_shutdown.start(portable=True)
    assert started == ["planner-auto-shutdown"]


@pytest.fixture
def calls(monkeypatch):
    log = []
    monkeypatch.setattr(launcher, "_single_instance", lambda: True)
    monkeypatch.setattr(launcher, "open_window", lambda: log.append("finestra"))
    monkeypatch.setattr(launcher, "stop_server", lambda pid: log.append(f"atura {pid}"))
    monkeypatch.setattr(launcher, "_error", lambda text: log.append("error"))
    return log


def _server(monkeypatch, calls, ready_after_start, pid=None, hung=False):
    state = {"started": False}

    def start():
        calls.append("arrenca")
        state["started"] = True
        return 1234

    monkeypatch.setattr(launcher, "start_server", start)
    monkeypatch.setattr(launcher, "our_server_pid", lambda: pid)
    monkeypatch.setattr(launcher, "server_ready", lambda timeout=1.0: state["started"] and ready_after_start)
    monkeypatch.setattr(launcher, "wait_ready", lambda s: (not hung and pid is not None) or (state["started"] and ready_after_start))


def test_already_running_only_opens_the_window(monkeypatch, calls):
    monkeypatch.setattr(launcher, "server_ready", lambda timeout=1.0: True)
    monkeypatch.setattr(launcher, "start_server", lambda: calls.append("arrenca"))
    assert launcher.main() == 0
    assert calls == ["finestra"]


def test_closed_program_starts_and_opens(monkeypatch, calls):
    _server(monkeypatch, calls, ready_after_start=True)
    assert launcher.main() == 0
    assert calls == ["arrenca", "finestra"]


def test_hung_server_is_restarted(monkeypatch, calls):
    _server(monkeypatch, calls, ready_after_start=True, pid=999, hung=True)
    assert launcher.main() == 0
    assert calls == ["atura 999", "arrenca", "finestra"]


def test_server_that_never_starts_shows_error_and_no_window(monkeypatch, calls):
    _server(monkeypatch, calls, ready_after_start=False)
    assert launcher.main() == 1
    assert calls == ["arrenca", "error"]


def test_second_double_click_while_opening_does_nothing(monkeypatch, calls):
    monkeypatch.setattr(launcher, "_single_instance", lambda: False)
    assert launcher.main() == 0
    assert calls == []


def _fake_bundle(tmp_path):
    (tmp_path / "python").mkdir()
    (tmp_path / "python" / "python.exe").write_bytes(b"")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "app.py").write_text("")
    return tmp_path


def test_bundle_root_only_in_the_portable(tmp_path):
    root = _fake_bundle(tmp_path)
    assert portable_launcher.bundle_root(str(root / "python" / "python.exe")) == root.resolve()
    assert portable_launcher.bundle_root(str(root / "app" / "python.exe")) is None


def test_launchers_call_the_new_launcher_and_are_rewritten_once(tmp_path):
    root = _fake_bundle(tmp_path)
    (root / "Planificador.vbs").write_text("antic: matava el port i engegava streamlit")
    assert portable_launcher.write_launchers(root) == ["Planificador.vbs", "run.bat"]
    for name in ("Planificador.vbs", "run.bat"):
        text = (root / name).read_bytes().decode("ascii")
        assert r"python\pythonw.exe" in text
        assert r"app\src\tools\obrir_planificador.py" in text
        assert "\r\n" in text
    assert portable_launcher.write_launchers(root) == []
