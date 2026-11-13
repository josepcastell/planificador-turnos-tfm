"""Tancar la finestra = tancar el programa.

Streamlit és un servidor: si l'usuari tancava el navegador, continuava
corrent amagat, el port quedava ocupat i reobrir el programa fallava o anava
lent. Aquest vigilant mira cada pocs segons quantes finestres hi ha
connectades i, quan fa GRACE_SECONDS que no n'hi ha cap (marge per a una
recàrrega de pàgina), executa `before_exit` (desar la sessió) i atura el
procés. Si en arrencar no s'hi connecta cap finestra en
STARTUP_GRACE_SECONDS, també s'atura (el llançador no l'ha pogut obrir).

S'activa sempre que l'app corre des del portable (és l'única manera de
tancar-lo: no hi ha botó), i fora d'ell només amb PLANNER_AUTO_SHUTDOWN=1:
en desenvolupament i als tests el servidor no s'atura sol."""

from __future__ import annotations

import os
import threading
import time
from typing import Callable

GRACE_SECONDS = 20.0
STARTUP_GRACE_SECONDS = 120.0
POLL_SECONDS = 2.0

_lock = threading.Lock()
_started = False
_before_exit: Callable[[], None] | None = None


def set_before_exit(fn: Callable[[], None] | None) -> None:
    """Què cal fer just abans d'aturar (desar la sessió). Cada execució de
    l'app hi registra la funció amb l'estat actual (sessió, any, mes)."""
    global _before_exit
    _before_exit = fn


def active_windows() -> int | None:
    """Finestres del navegador connectades ara mateix. None si no se sap
    (API interna de Streamlit canviada): llavors no s'atura mai."""
    try:
        from streamlit.runtime import Runtime
        if not Runtime.exists():
            return None
        return len(Runtime.instance()._session_mgr.list_active_sessions())
    except Exception:
        return None


def wait_until_idle(count_windows: Callable[[], int | None], *, grace: float,
                    startup_grace: float, poll: float,
                    clock: Callable[[], float] = time.monotonic,
                    sleep: Callable[[float], None] = time.sleep) -> None:
    """Torna quan fa `grace` segons que no hi ha cap finestra connectada
    (`startup_grace` si encara no se n'ha connectat cap)."""
    last_seen = clock()
    seen_any = False
    while True:
        sleep(poll)
        n = count_windows()
        now = clock()
        if n is None or n > 0:
            last_seen = now
            seen_any = seen_any or bool(n)
            continue
        if now - last_seen >= (grace if seen_any else startup_grace):
            return


def _run() -> None:
    wait_until_idle(
        active_windows, grace=GRACE_SECONDS,
        startup_grace=STARTUP_GRACE_SECONDS, poll=POLL_SECONDS,
    )
    if _before_exit is not None:
        try:
            _before_exit()
        except Exception:
            pass  # apagar igualment: el workspace a disc ja té els autosaves
    os._exit(0)


def start(portable: bool = False) -> None:
    """Engega el vigilant (un sol cop per procés; l'app es re-executa a
    cada interacció però aquest mòdul només s'importa una vegada).
    `portable`: l'app corre des del paquet portable — llavors sempre, encara
    que l'hagi engegat un llançador antic que no posa la variable."""
    global _started
    if not portable and os.environ.get("PLANNER_AUTO_SHUTDOWN") != "1":
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_run, name="planner-auto-shutdown", daemon=True).start()
