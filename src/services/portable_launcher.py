"""Al portable, deixa al dia els llançadors de l'arrel del paquet.

El botó «Actualitzar» només substitueix el codi (app.py, src/, VERSION), no
els fitxers de l'arrel. Per això l'app mateixa, en arrencar, reescriu
Planificador.vbs i run.bat perquè cridin el llançador actual
(src/tools/obrir_planificador.py) i crea, un sol cop, la drecera
«Planificador» a l'Escriptori per tornar-lo a obrir amb un doble clic.

Fora del portable (desenvolupament) no fa res. PLANNER_DESKTOP_SHORTCUT=0
evita la drecera (per a proves)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

LAUNCHER_REL = r"app\src\tools\obrir_planificador.py"

# Només ASCII: el Windows Script Host i el cmd no llegeixen UTF-8.
LAUNCHER_VBS = rf"""' Obre el Planificador amb un doble clic. Tancar la seva finestra el tanca.
' Fitxer generat pel programa (es reescriu sol en actualitzar-lo).
Dim fso, root
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run Chr(34) & root & "\python\pythonw.exe" & Chr(34) & " " & Chr(34) & root & "\{LAUNCHER_REL}" & Chr(34), 0, False
"""

RUN_BAT = rf"""@echo off
rem Obre el Planificador (igual que Planificador.vbs). Fitxer generat pel programa.
start "" "%~dp0python\pythonw.exe" "%~dp0{LAUNCHER_REL}"
"""

_done = False


def bundle_root(executable: str | None = None) -> Path | None:
    """Carpeta del paquet portable (la que conté python\\ i app\\), o None
    si l'app no corre des d'un portable."""
    exe = Path(executable or sys.executable).resolve()
    root = exe.parent.parent
    if exe.parent.name.lower() == "python" and (root / "app" / "app.py").is_file():
        return root
    return None


def write_launchers(root: Path) -> list[str]:
    """Escriu Planificador.vbs i run.bat si no hi són o han canviat.
    Retorna els noms dels fitxers reescrits."""
    changed = []
    for name, text in (("Planificador.vbs", LAUNCHER_VBS), ("run.bat", RUN_BAT)):
        path = Path(root) / name
        data = text.replace("\n", "\r\n").encode("ascii")
        try:
            if path.is_file() and path.read_bytes() == data:
                continue
            path.write_bytes(data)
            changed.append(name)
        except OSError:
            pass  # carpeta de només lectura: el llançador antic segueix funcionant
    return changed


def _ps_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def ensure_desktop_shortcut(root: Path) -> bool:
    """Crea la drecera «Planificador» a l'Escriptori un sol cop per carpeta
    del programa (si es mou la carpeta, se'n fa una de nova). Si l'usuari
    l'esborra, no es torna a crear."""
    root = Path(root)
    marker = root / "dades" / ".drecera_escriptori"
    try:
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == str(root):
            return False
    except OSError:
        return False
    script = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Planificador.lnk'));"
        f"$s.TargetPath={_ps_quote(root / 'python' / 'pythonw.exe')};"
        f"$s.Arguments={_ps_quote(chr(34) + str(root / LAUNCHER_REL) + chr(34))};"
        f"$s.WorkingDirectory={_ps_quote(root / 'app')};"
        "$s.Description='Obre el Planificador de torns';"
        "$s.Save()"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=60, creationflags=0x08000000,  # sense finestra
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if done.returncode != 0:
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(root), encoding="utf-8")
    except OSError:
        pass
    return True


def ensure_once() -> None:
    """Un cop per procés: llançadors al dia i drecera (en segon pla, perquè
    PowerShell tarda un segon i no ha d'alentir l'arrencada)."""
    global _done
    if _done:
        return
    _done = True
    root = bundle_root()
    if root is None:
        return
    write_launchers(root)
    if os.environ.get("PLANNER_DESKTOP_SHORTCUT", "1") != "0":
        threading.Thread(target=ensure_desktop_shortcut, args=(root,), daemon=True).start()
