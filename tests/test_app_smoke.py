"""Smoke test de l'APP SENCERA amb el runner de Streamlit.

Executa `app.py` de dalt a baix (totes les pestanyes es renderitzen a
cada run) i falla si hi ha QUALSEVOL excepció. Aquesta prova hauria
d'haver caçat l'IndexError de `cols_form[5]` que va deixar el planner
inservible: la suite d'unitat no toca el codi de la UI.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Fitxers mínims perquè l'app arrenqui en un workspace nou.
_SEED_DIRS = ["data", "outputs"]


def _run_app_in(tmp_path: Path) -> subprocess.CompletedProcess:
    """Copia l'app a un directori net (amb data/ només de capçaleres) i
    l'executa amb AppTest en un subprocés, per no contaminar el repo."""
    for name in ["app.py", "src"]:
        src = REPO / name
        dst = tmp_path / name
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy(src, dst)
    (tmp_path / "outputs").mkdir(exist_ok=True)

    runner = tmp_path / "_smoke_runner.py"
    runner.write_text(
        "import sys\n"
        "from streamlit.testing.v1 import AppTest\n"
        "at = AppTest.from_file('app.py', default_timeout=180)\n"
        "at.run()\n"
        "if at.exception:\n"
        "    for e in at.exception:\n"
        "        print('EXCEPCIO:', e.value, file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "print('OK: app renderitzada sense excepcions')\n",
        encoding="utf-8",
    )
    env = dict(os.environ, PYTHONPATH=str(tmp_path))
    return subprocess.run(
        [sys.executable, str(runner)],
        cwd=tmp_path, capture_output=True, text=True, timeout=600, env=env,
    )


def test_app_renders_without_exceptions(tmp_path):
    res = _run_app_in(tmp_path)
    assert res.returncode == 0, (
        "l'app ha llançat una excepció en renderitzar-se:\n"
        f"{res.stderr[-3000:]}"
    )
