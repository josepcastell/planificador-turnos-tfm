"""«Desar com a fitxer…» i «Obrir una sessió desada en fitxer»: una sessió
sencera en un sol .zip, per continuar-la en un altre ordinador (p. ex. el
de la feina i el de casa)."""

import io
import zipfile

import pytest

from src.services import session_store
from test_app_smoke import _run_app_in


def _session(root, name="Equip_TC", section="Equip TC", who="ZZ"):
    d = root / name
    (d / "data").mkdir(parents=True)
    (d / "session.txt").write_text(
        session_store.session_manifest(2026, 12, section), encoding="utf-8",
    )
    (d / "data" / "professionals.csv").write_text(
        f"professional_id,name\n{who},Nom\n", encoding="utf-8",
    )
    (d / "_snapshots" / "20261101_100000").mkdir(parents=True)
    (d / "_snapshots" / "20261101_100000" / "vell.txt").write_text("x", encoding="utf-8")
    return d


def test_save_as_file_and_open_it_on_another_computer(tmp_path):
    feina = _session(tmp_path / "feina")
    zip_path = session_store.export_session_file(feina, tmp_path / "usb")
    assert zip_path.name.startswith("Planificador_Equip_TC_") and zip_path.suffix == ".zip"
    names = zipfile.ZipFile(zip_path).namelist()
    assert "session.txt" in names and "data/professionals.csv" in names
    assert not any(n.startswith("_snapshots") for n in names)  # versions: no

    data = zip_path.read_bytes()
    assert session_store.read_session_file_manifest(data)["section"] == "Equip TC"
    casa = tmp_path / "casa" / session_store.safe_session_name("Equip TC")
    session_store.import_session_file(data, casa)
    assert (casa / "data" / "professionals.csv").read_text(encoding="utf-8").endswith("ZZ,Nom\n")
    assert session_store.list_session_folders(tmp_path / "casa") == [casa]


def test_replacing_keeps_a_version_of_what_was_there(tmp_path):
    data = session_store.export_session_file(
        _session(tmp_path / "feina", who="NOU"), tmp_path,
    ).read_bytes()
    casa = _session(tmp_path / "casa", who="VELL")
    with pytest.raises(session_store.SessionFileError):
        session_store.import_session_file(data, casa)  # sense substituir: no
    session_store.import_session_file(data, casa, replace=True)
    assert "NOU" in (casa / "data" / "professionals.csv").read_text(encoding="utf-8")
    versions = session_store.list_session_snapshots(casa)
    assert len(versions) == 2  # la que hi havia + la de seguretat d'abans de substituir
    assert "VELL" in (versions[0] / "data" / "professionals.csv").read_text(encoding="utf-8")


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


@pytest.mark.parametrize("data", [
    b"no soc un zip",
    _zip({"data/professionals.csv": "x"}),                      # sense session.txt
    _zip({"session.txt": "section=X", "../fora.txt": "x"}),     # ruta fora de la sessió
])
def test_a_file_that_is_not_a_session_is_refused(tmp_path, data):
    with pytest.raises(session_store.SessionFileError):
        session_store.import_session_file(data, tmp_path / "X")
    assert not (tmp_path / "X").exists()
    assert not (tmp_path / "fora.txt").exists()


_APP_SCRIPT = """
import dataclasses, sys
from pathlib import Path
from streamlit.testing.v1 import AppTest
import src.ui.session_sidebar as sb
from src.services import session_store

at = AppTest.from_file('app.py', default_timeout=180)
at.run()
if at.exception:
    print('EXCEPCIO al render:', at.exception[0].value, file=sys.stderr); sys.exit(1)

# Una sessio d'un altre ordinador, desada en fitxer.
altre = Path('altre_pc') / 'Equip_TC'
(altre / 'data').mkdir(parents=True)
(altre / 'session.txt').write_text(
    session_store.session_manifest(2026, 12, 'Equip TC'), encoding='utf-8')
(altre / 'data' / 'professionals.csv').write_text(
    'professional_id,name,fallback\\nZZ,De la feina,0\\n', encoding='utf-8')
data = session_store.export_session_file(altre, Path('usb')).read_bytes()

orig = sb.render_session_sidebar_actions
pending = [
    dict(import_request={'data': data, 'title': 'Equip TC', 'replace': False}),
    dict(export_requested=True, export_dir=str(Path('sortida').resolve())),
]
def fake(*args, **kwargs):
    actions = orig(*args, **kwargs)
    return dataclasses.replace(actions, **pending.pop(0)) if pending else actions
sb.render_session_sidebar_actions = fake

at.run()   # obre la sessio del fitxer
if at.exception:
    print('EXCEPCIO en obrir:', at.exception[0].value, file=sys.stderr); sys.exit(1)
if Path(at.session_state['loaded_session_dir']).name != 'Equip_TC':
    print('ERROR: sessio carregada', at.session_state['loaded_session_dir'], file=sys.stderr); sys.exit(1)
if at.text_input(key='section_name_for_manifest').value != 'Equip TC':
    print('ERROR: titol', at.text_input(key='section_name_for_manifest').value, file=sys.stderr); sys.exit(1)
if 'ZZ' not in Path('data/professionals.csv').read_text(encoding='utf-8'):
    print('ERROR: les dades de la sessio no s han carregat', file=sys.stderr); sys.exit(1)

at.run()   # desar com a fitxer
if at.exception:
    print('EXCEPCIO en desar:', at.exception[0].value, file=sys.stderr); sys.exit(1)
fitxers = list(Path('sortida').glob('Planificador_Equip_TC_*.zip'))
if len(fitxers) != 1:
    print('ERROR: fitxer desat', fitxers, file=sys.stderr); sys.exit(1)
print('OK')
"""


def test_open_and_save_from_the_app(tmp_path):
    res = _run_app_in(tmp_path, _APP_SCRIPT)
    assert res.returncode == 0, res.stderr[-3000:]


_NEW_SESSION_SCRIPT = """
import sys
from pathlib import Path
from streamlit.testing.v1 import AppTest

at = AppTest.from_file('app.py', default_timeout=120)
at.run()
actual = Path(at.session_state['loaded_session_dir']).name
titol = at.text_input(key='section_name_for_manifest').value

def nova(nom):
    at.button(key='new_session_btn').click().run()
    at.text_input(key='new_session_name_input').set_value(nom)
    at.button(key='new_session_create').click().run()
    if at.exception:
        print('EXCEPCIO:', at.exception[0].value, file=sys.stderr); sys.exit(1)

# Amb el nom d'una sessio que ja existeix: error, sense bucle ni carpeta nova.
nova(titol)
if not any('Ja existeix' in e.value for e in at.error):
    print('ERROR: no avisa que ja existeix', file=sys.stderr); sys.exit(1)
root = Path(at.session_state['loaded_session_dir']).parent
if sorted(p.name for p in root.iterdir() if p.is_dir()) != [actual]:
    print('ERROR: carpetes', sorted(p.name for p in root.iterdir()), file=sys.stderr); sys.exit(1)

# Amb un nom nou: carpeta sense l'any i carregada.
at.button(key='new_session_cancel').click().run()
nova('Equip Nou')
if Path(at.session_state['loaded_session_dir']).name != 'Equip_Nou':
    print('ERROR: sessio nova', at.session_state['loaded_session_dir'], file=sys.stderr); sys.exit(1)
print('OK')
"""


def test_new_session_with_an_existing_name_does_not_loop(tmp_path):
    res = _run_app_in(tmp_path, _NEW_SESSION_SCRIPT)
    assert res.returncode == 0, res.stderr[-3000:]
