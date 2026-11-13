"""Llançador del Planificador al portable de Windows.

Un doble clic (drecera «Planificador» de l'Escriptori, o Planificador.vbs de
la carpeta del programa) obre el programa en una finestra pròpia, i tancar
aquesta finestra el tanca (vegeu src/services/auto_shutdown.py):

  · Si el programa ja està obert, només n'obre la finestra: no el reinicia
    (abans es matava i es tornava a engegar a cada doble clic).
  · Si no, l'arrenca sense cap finestra de terminal ni cap avís i, quan
    està llest, obre la finestra: Edge o Chrome en mode
    aplicació (sense pestanyes ni barra d'adreces) o, si no n'hi ha cap, el
    navegador per defecte.
  · Un servidor d'aquest mateix paquet que no respon es mata i es torna a
    engegar.

Només fa servir la llibreria estàndard i s'executa amb el pythonw.exe del
paquet (sense consola):
    python\\pythonw.exe app\\src\\tools\\obrir_planificador.py
Viu dins src/ perquè el botó «Actualitzar» també el posi al dia.
PLANNER_PORT canvia el port (per a proves)."""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
import urllib.request
import webbrowser
from pathlib import Path

PORT = int(os.environ.get("PLANNER_PORT", "8501"))
URL = f"http://127.0.0.1:{PORT}"
APP_DIR = Path(__file__).resolve().parents[2]
BUNDLE = APP_DIR.parent
PYTHON = BUNDLE / "python" / "python.exe"
DADES = BUNDLE / "dades"
PID_FILE = DADES / ".servidor.pid"
LOG_FILE = DADES / "planificador.log"
START_TIMEOUT = 120
HUNG_TIMEOUT = 20
CREATE_NO_WINDOW = 0x08000000

# Les peticions a 127.0.0.1 no han de passar mai pel proxy de l'hospital.
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_mutex = None


def server_ready(timeout: float = 1.0) -> bool:
    try:
        with _LOCAL.open(f"{URL}/_stcore/health", timeout=timeout) as resp:
            return resp.status == 200
    except OSError:
        return False


def wait_ready(seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if server_ready():
            return True
        time.sleep(0.5)
    return server_ready()


def _process_path(pid: int) -> str:
    """Executable d'un procés (buit si ja no existeix)."""
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(len(buf))
        ok = k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return buf.value if ok else ""
    finally:
        k32.CloseHandle(handle)


def our_server_pid() -> int | None:
    """PID del servidor que va engegar aquest llançador, si encara és viu i
    és el python d'AQUEST paquet (mai un altre programa amb el PID reciclat)."""
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    path = _process_path(pid)
    return pid if path and Path(path) == PYTHON else None


def stop_server(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True, creationflags=CREATE_NO_WINDOW,
    )


def start_server() -> int:
    (DADES / "PDFs").mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        PYTHONUTF8="1",               # el log del solver té caràcters Unicode
        PLANNER_AUTO_SHUTDOWN="1",    # tancar la finestra = tancar el programa
        PAC3_PDF_OUTPUT_DIR=str(DADES / "PDFs"),
        PAC3_DESKTOP_DIR=str(DADES / "PDFs"),
    )
    cmd = [
        str(PYTHON), "-m", "streamlit", "run", "app.py",
        "--server.headless=true", "--browser.gatherUsageStats=false",
        # Només accessible des d'aquest PC, mai des de la xarxa.
        "--server.address=127.0.0.1", f"--server.port={PORT}",
    ]
    with open(LOG_FILE, "wb") as log:
        proc = subprocess.Popen(
            cmd, cwd=APP_DIR, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW,
        )
    PID_FILE.write_text(str(proc.pid), encoding="ascii")
    return proc.pid


def _app_browser() -> Path | None:
    bases = [os.environ.get(v) for v in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData")]
    candidates = [
        Path(base) / rel
        for rel in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe")
        for base in bases if base
    ]
    return next((c for c in candidates if c.is_file()), None)


def open_window() -> None:
    """Finestra pròpia del programa (mode aplicació): tancar-la el tanca."""
    browser = _app_browser()
    if browser is None:
        webbrowser.open(URL)
        return
    subprocess.Popen([str(browser), f"--app={URL}", "--start-maximized"])


def _error(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "Planificador", 0x10)  # MB_ICONERROR


def _single_instance() -> bool:
    """Un doble clic repetit mentre s'obre no engega res més."""
    global _mutex
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex = k32.CreateMutexW(None, False, "Local\\PlanificadorLlancador")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def _ensure_server() -> bool:
    pid = our_server_pid()
    if pid is not None and not wait_ready(HUNG_TIMEOUT):
        stop_server(pid)  # penjat: es torna a engegar
    if server_ready():
        return True
    start_server()
    return wait_ready(START_TIMEOUT)


def main() -> int:
    if not _single_instance():
        return 0
    if not server_ready():
        ok = _ensure_server()
        if not ok:
            _error(
                "No s'ha pogut obrir el Planificador.\n\n"
                f"Detalls tècnics a:\n{LOG_FILE}"
            )
            return 1
    open_window()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
