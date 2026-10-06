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


_RENDER_SCRIPT = """
import sys
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('app.py', default_timeout=180)
at.run()
if at.exception:
    for e in at.exception:
        print('EXCEPCIO:', e.value, file=sys.stderr)
    sys.exit(1)
print('OK: app renderitzada sense excepcions')
"""

# L'any viu a l'ambit (no a la barra lateral) i canviar-lo ha de funcionar
# sense excepcions. El render sol no ho cobreix: el cami del canvi d'any
# nomes s'executa quan l'any canvia de debo.
_YEAR_SCRIPT = """
import sys
from streamlit.testing.v1 import AppTest

at = AppTest.from_file('app.py', default_timeout=180)
at.run()
if at.exception:
    for e in at.exception:
        print('EXCEPCIO al render:', e.value, file=sys.stderr)
    sys.exit(1)

if any('ny' in (w.label or '') for w in at.sidebar.number_input):
    print('ERROR: encara hi ha un selector d any a la barra lateral',
          file=sys.stderr)
    sys.exit(1)

anys = [w for w in at.selectbox if w.label == 'Any']
if not anys:
    print('ERROR: no hi ha el selector d any a l ambit', file=sys.stderr)
    sys.exit(1)

sel = anys[0]
altre = [o for o in sel.options if o != sel.value][0]
sel.set_value(altre).run()
if at.exception:
    for e in at.exception:
        print('EXCEPCIO en canviar d any:', e.value, file=sys.stderr)
    sys.exit(1)
if int(at.session_state['weekday_selected_year']) != int(altre):
    print('ERROR: el canvi d any no ha propagat', file=sys.stderr)
    sys.exit(1)
print('OK: any a l ambit i canvi sense excepcions')
"""


# Canviar el TITOL reanomena la sessio carregada (no en crea cap de nova).
# Aquest cami tenia un NameError latent (`_prev_section`) que nomes es
# dispara quan el reanomenament falla o hi ha colisio de noms, i cap test
# no el trepitjava.
_RENAME_SCRIPT = """
import sys
from pathlib import Path
from streamlit.testing.v1 import AppTest

at = AppTest.from_file('app.py', default_timeout=180)
at.run()
if at.exception:
    for e in at.exception:
        print('EXCEPCIO al render:', e.value, file=sys.stderr)
    sys.exit(1)

titols = [w for w in at.sidebar.text_input if 'tol' in (w.label or '')]
if not titols:
    print('ERROR: no hi ha el camp del titol', file=sys.stderr)
    sys.exit(1)

abans = Path(at.session_state['loaded_session_dir'])
(abans / 'data').mkdir(parents=True, exist_ok=True)
(abans / 'data' / 'marca.txt').write_text('la feina', encoding='utf-8')

titols[0].set_value('Proves Renom').run()
if at.exception:
    for e in at.exception:
        print('EXCEPCIO en reanomenar:', e.value, file=sys.stderr)
    sys.exit(1)

despres = Path(at.session_state['loaded_session_dir'])
if despres.name != 'Proves_Renom':
    print('ERROR: la sessio carregada es %s' % despres.name, file=sys.stderr)
    sys.exit(1)
if not despres.exists():
    print('ERROR: la carpeta reanomenada no existeix', file=sys.stderr)
    sys.exit(1)
if (despres / 'data' / 'marca.txt').read_text(encoding='utf-8') != 'la feina':
    print('ERROR: la feina no ha sobreviscut al reanomenament', file=sys.stderr)
    sys.exit(1)
if abans.exists() and abans != despres:
    print('ERROR: ha quedat una sessio duplicada (%s)' % abans.name,
          file=sys.stderr)
    sys.exit(1)

# I ara una COLISIO: es torna al titol de partida, que ja te carpeta.
arrel = despres.parent
(arrel / 'Ocupada').mkdir(parents=True, exist_ok=True)
titols = [w for w in at.sidebar.text_input if 'tol' in (w.label or '')]
titols[0].set_value('Ocupada').run()
if at.exception:
    for e in at.exception:
        print('EXCEPCIO en la colisio de noms:', e.value, file=sys.stderr)
    sys.exit(1)
if Path(at.session_state['loaded_session_dir']).name != 'Proves_Renom':
    print('ERROR: la colisio no ha retornat a la sessio anterior',
          file=sys.stderr)
    sys.exit(1)
print('OK: reanomenar i colisio sense excepcions')
"""


def _run_app_in(tmp_path: Path, script: str = None) -> subprocess.CompletedProcess:
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
    runner.write_text(script or _RENDER_SCRIPT, encoding="utf-8")
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


def test_year_selector_lives_in_the_scope_and_can_change(tmp_path):
    """REGRESSIÓ: en treure l'any de la barra lateral, el camí del canvi
    d'any petava amb NameError (usava una variable encara no calculada).
    El render sol no ho detectava."""
    res = _run_app_in(tmp_path, _YEAR_SCRIPT)
    assert res.returncode == 0, (
        "el canvi d'any falla:\n%s" % res.stderr[-3000:]
    )


def test_renaming_a_session_keeps_the_work_and_survives_a_collision(tmp_path):
    """REGRESSIÓ (C1): el camí del reanomenament llegia `_prev_section`
    sense definir-la, i petava justament quan el títol xocava amb una
    sessió existent o quan el rename fallava."""
    res = _run_app_in(tmp_path, _RENAME_SCRIPT)
    assert res.returncode == 0, (
        "el reanomenament de sessio falla:%s%s" % (chr(10), res.stderr[-3000:])
    )
