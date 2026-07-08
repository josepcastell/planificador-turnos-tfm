"""Auto-actualització del codi de l'app (només `app.py` + `src/` + `VERSION`).

El botó de la barra lateral consulta l'última versió publicada al GitHub,
i si n'hi ha una de nova, baixa `app_update.zip` de la release i el reemplaça
en local. NO toca les dades (`data/`, `dades/`) ni el Python del portable.

Per aplicar el codi nou cal **tancar i tornar a obrir** l'app (Python carrega
el codi a memòria a l'inici).
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

OWNER = "josepcastell"
REPO = "planificador-turnos-tfm"
_API_LATEST = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
_ASSET_URL = f"https://github.com/{OWNER}/{REPO}/releases/latest/download/app_update.zip"
_UA = {"User-Agent": "planner-updater"}


def current_version(app_root) -> str:
    f = Path(app_root) / "VERSION"
    try:
        return f.read_text(encoding="utf-8").strip() if f.exists() else "0"
    except Exception:
        return "0"


def latest_version(timeout: int = 10) -> str:
    """Tag de l'última release (sense la 'v' inicial). Pot llançar excepció
    (sense connexió, sense releases…)."""
    req = urllib.request.Request(
        _API_LATEST, headers={**_UA, "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    tag = str(data.get("tag_name") or "").strip()
    return tag[1:] if tag[:1].lower() == "v" else tag


def _vtuple(v: str) -> tuple:
    out = []
    for part in str(v).split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def is_newer(latest: str, current: str) -> bool:
    if not latest:
        return False
    return _vtuple(latest) > _vtuple(current)


def download_update(timeout: int = 120) -> bytes:
    """Baixa el zip d'actualització (app.py + src/ + VERSION)."""
    req = urllib.request.Request(_ASSET_URL, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _zip_root(extract_dir: Path) -> Path:
    """Arrel dins del zip extret on hi ha app.py (per si està anidat un nivell)."""
    if (extract_dir / "app.py").exists():
        return extract_dir
    for sub in extract_dir.iterdir():
        if sub.is_dir() and (sub / "app.py").exists():
            return sub
    return extract_dir


def apply_update(app_root, zip_bytes: bytes) -> None:
    """Reemplaça `src/`, `app.py` i `VERSION` a `app_root` amb el contingut del
    zip. NO toca `data/`, `dades/`, `outputs/`. Fa un *backup-swap* de `src/`
    per no deixar l'app trencada si alguna còpia falla."""
    app_root = Path(app_root)
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("El fitxer baixat no és un zip vàlid.") from exc

    names = zf.namelist()
    if not any(n == "app.py" or n.endswith("/app.py") for n in names):
        raise ValueError("El paquet d'actualització no és vàlid (falta app.py).")

    with tempfile.TemporaryDirectory() as tmp:
        zf.extractall(tmp)
        root = _zip_root(Path(tmp))
        new_src = root / "src"
        if not new_src.is_dir():
            raise ValueError("El paquet d'actualització no conté la carpeta src/.")

        # --- swap de src/ amb backup ---
        dst_src = app_root / "src"
        backup = app_root / "src__bak_update"
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        try:
            if dst_src.exists():
                dst_src.rename(backup)
            shutil.copytree(new_src, dst_src)
        except Exception:
            # restaurar el src/ original
            if not dst_src.exists() and backup.exists():
                backup.rename(dst_src)
            raise
        shutil.rmtree(backup, ignore_errors=True)

        # --- app.py i VERSION ---
        if (root / "app.py").exists():
            shutil.copy2(root / "app.py", app_root / "app.py")
        if (root / "VERSION").exists():
            shutil.copy2(root / "VERSION", app_root / "VERSION")
