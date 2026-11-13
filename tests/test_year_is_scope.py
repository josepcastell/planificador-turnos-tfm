"""L'ANY és un ÀMBIT, no part de la sessió.

Abans la carpeta d'una sessió era «{secció}_{any}»: canviar l'any a la
barra lateral obria una sessió DIFERENT i la configuració (màquines
fixes, rodes, llistes de màquines i llocs) no hi era — l'usuària ho havia
de reintroduir tot. Ara una mateixa sessió conté tots els anys.
"""

from pathlib import Path

from src.services.session_store import (
    infer_section_year_from_session_name,
    load_session_folder,
    migrate_year_suffixed_sessions,
    save_session_folder,
)


def _session(root: Path, name: str, year: int = 2026) -> Path:
    d = root / name
    (d / "data" / "weekday").mkdir(parents=True)
    (d / "data" / "weekday" / "fixed_machines.csv").write_text(
        "professional_id,slot_id,weekday_name,franja\nP1,ECO_A,MONDAY,MATI\n",
        encoding="utf-8-sig",
    )
    (d / "data" / f"base_calendar_{year}.csv").write_text(
        "day,year\n%d-01-01,%d\n" % (year, year), encoding="utf-8-sig",
    )
    (d / "session.txt").write_text("section=%s\n" % name, encoding="utf-8")
    return d


class TestInferName:
    def test_new_naming_keeps_the_whole_name_as_section(self):
        # REGRESSIÓ: amb «Mama» retornava («Seccio», …) i es perdia el títol.
        assert infer_section_year_from_session_name("Mama", 2026) == ("Mama", 2026)

    def test_old_naming_still_understood(self):
        assert infer_section_year_from_session_name("Mama_2026", 2030) == ("Mama", 2026)

    def test_name_with_underscore_but_no_year(self):
        assert infer_section_year_from_session_name("Seccio_Mama", 2026) == (
            "Seccio_Mama", 2026,
        )

    def test_empty_falls_back(self):
        assert infer_section_year_from_session_name("", 2026) == ("Seccio", 2026)


class TestMigration:
    def test_renames_year_suffixed_session(self, tmp_path):
        _session(tmp_path, "Mama_2026")
        fets = migrate_year_suffixed_sessions(tmp_path)
        assert fets == [("Mama_2026", "Mama")]
        assert (tmp_path / "Mama").is_dir()
        assert not (tmp_path / "Mama_2026").exists()

    def test_data_survives_the_rename(self, tmp_path):
        _session(tmp_path, "Mama_2026")
        migrate_year_suffixed_sessions(tmp_path)
        fixes = tmp_path / "Mama" / "data" / "weekday" / "fixed_machines.csv"
        assert fixes.exists()
        assert "ECO_A" in fixes.read_text(encoding="utf-8-sig")

    def test_updates_last_session_pointer(self, tmp_path):
        _session(tmp_path, "Mama_2026")
        last = tmp_path / ".last_session"
        last.write_text("Mama_2026", encoding="utf-8")
        migrate_year_suffixed_sessions(tmp_path, last)
        assert last.read_text(encoding="utf-8").strip() == "Mama"

    def test_several_years_keeps_the_newest_and_touches_nothing_else(self, tmp_path):
        _session(tmp_path, "Mama_2026", 2026)
        _session(tmp_path, "Mama_2027", 2027)
        fets = migrate_year_suffixed_sessions(tmp_path)
        assert fets == [("Mama_2027", "Mama")]
        # La del 2026 es conserva intacta: mai s'esborra ni es fusiona res.
        assert (tmp_path / "Mama_2026").is_dir()
        assert (tmp_path / "Mama" / "data" / "base_calendar_2027.csv").exists()

    def test_does_not_touch_an_existing_destination(self, tmp_path):
        _session(tmp_path, "Mama")
        _session(tmp_path, "Mama_2026")
        assert migrate_year_suffixed_sessions(tmp_path) == []
        assert (tmp_path / "Mama_2026").is_dir()

    def test_ignores_names_without_a_year(self, tmp_path):
        _session(tmp_path, "Mama")
        _session(tmp_path, "Neuro_radiologia")
        assert migrate_year_suffixed_sessions(tmp_path) == []

    def test_empty_root_is_safe(self, tmp_path):
        assert migrate_year_suffixed_sessions(tmp_path / "no_hi_es") == []


class TestConfigSurvivesYearChange:
    """La configuració compartida ha de sobreviure a un canvi d'any dins
    de la mateixa sessió (desar l'any que deixem + carregar el nou)."""

    CONFIG = {
        "data/maquines.csv": "nom\nECO\nMX\n",
        "data/llocs.csv": "nom\nZONA_A\n",
        "data/weekday/fixed_machines.csv":
            "professional_id,slot_id,weekday_name,franja\nP1,ECO_A,MONDAY,MATI\n",
        "data/weekday/wheel_slots.csv":
            "slot_id,weekday_name,professionals\nECO_A,,P1;P2\n",
        "data/professionals.csv":
            "professional_id,name,doubled_machines,non_working_weekdays,"
            "no_pres_weekdays,pres_weekdays,fallback,presence_mode\nP1,,,,,,0,\n",
    }

    def _workspace(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.chdir(ws)
        for rel, text in self.CONFIG.items():
            p = ws / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8-sig")
        return ws

    def test_shared_config_still_there_after_switching_year(
        self, tmp_path, monkeypatch,
    ):
        ws = self._workspace(tmp_path, monkeypatch)
        sess = tmp_path / "Mama"
        pdfs = tmp_path / "pdfs"
        last = tmp_path / ".last_session"

        # Treballa el 2026 i desa.
        save_session_folder(sess, 2026, 1, "Mama", last, pdfs)
        # El workspace es BUIDA entremig: així el test comprova de debò
        # que la configuració torna de la carpeta de sessió i no que es
        # compara amb ella mateixa (abans el test era tautològic).
        for rel in self.CONFIG:
            (ws / rel).unlink()
        # Canvia al 2027: carrega de la sessió el que toca.
        load_session_folder(sess, 2027, 1, pdfs)

        for rel, text in self.CONFIG.items():
            actual = (ws / rel).read_text(encoding="utf-8-sig")
            assert actual.strip() == text.strip(), (
                "s'ha perdut %s en canviar d'any" % rel
            )

    def test_machine_and_place_lists_are_saved_in_the_session(
        self, tmp_path, monkeypatch,
    ):
        # REGRESSIÓ: maquines.csv i llocs.csv no eren al registre, així que
        # no es desaven mai amb la sessió.
        self._workspace(tmp_path, monkeypatch)
        sess = tmp_path / "Mama"
        save_session_folder(sess, 2026, 1, "Mama", tmp_path / ".last", tmp_path / "pdfs")
        assert (sess / "data" / "maquines.csv").exists()
        assert (sess / "data" / "llocs.csv").exists()


class TestMigrationIsSafe:
    """Casos que una migració que s'executa a cada rerun faria malbé."""

    def test_runs_only_once(self, tmp_path):
        _session(tmp_path, "Mama_2026")
        assert migrate_year_suffixed_sessions(tmp_path) == [("Mama_2026", "Mama")]
        # Segona passada: no ha de tocar res mai més.
        _session(tmp_path, "TC_2026")
        assert migrate_year_suffixed_sessions(tmp_path) == []
        assert (tmp_path / "TC_2026").is_dir()

    def test_user_title_with_a_year_is_not_eaten(self, tmp_path):
        # REGRESSIÓ: un títol com «TC 2026» crea la carpeta TC_2026; sense
        # el marcador, el rerun següent la renombrava a «TC» i el títol
        # quedava descasat de la carpeta.
        (tmp_path / ".year_scope_migrated").write_text("x", encoding="utf-8")
        _session(tmp_path, "TC_2026")
        assert migrate_year_suffixed_sessions(tmp_path) == []
        assert (tmp_path / "TC_2026").is_dir()

    def test_two_years_inside_the_name(self, tmp_path):
        # Només s'ha de retallar l'any FINAL: una secció titulada
        # «Seccio 2026» treballada el 2027 donava la carpeta
        # «Seccio_2026_2027», i el títol que cal conservar és «Seccio 2026».
        # La migració i la inferència del nom han de dir el mateix.
        _session(tmp_path, "Seccio_2026_2027")
        assert migrate_year_suffixed_sessions(tmp_path) == [
            ("Seccio_2026_2027", "Seccio_2026"),
        ]
        assert infer_section_year_from_session_name("Seccio_2026_2027", 2030) == (
            "Seccio_2026", 2027,
        )

    def test_four_digits_that_are_not_a_year(self, tmp_path):
        _session(tmp_path, "Sala_1234")
        assert migrate_year_suffixed_sessions(tmp_path) == []
        assert (tmp_path / "Sala_1234").is_dir()

    def test_last_session_pointing_at_an_older_year(self, tmp_path):
        # REGRESSIÓ: es renombra l'any més recent, però .last_session
        # apuntava al vell i s'obria la sessió antiga.
        _session(tmp_path, "Mama_2026", 2026)
        _session(tmp_path, "Mama_2027", 2027)
        last = tmp_path / ".last_session"
        last.write_text("Mama_2026", encoding="utf-8")
        migrate_year_suffixed_sessions(tmp_path, last)
        assert last.read_text(encoding="utf-8").strip() == "Mama"

    def test_unreadable_root_does_not_crash(self, tmp_path):
        fitxer = tmp_path / "no_soc_carpeta"
        fitxer.write_text("x", encoding="utf-8")
        assert migrate_year_suffixed_sessions(fitxer) == []


class TestNameInference:
    def test_unicode_digits_do_not_crash(self):
        # «²²²²» passa isdigit() pero int() peta.
        assert infer_section_year_from_session_name("Mama_²²²²", 2026) == (
            "Mama_²²²²", 2026,
        )


class TestGeneratedFilesAreNotSharedBetweenYears:
    """Els fitxers GENERATS que depenen de l'any (dies hàbils, slots del
    calendari i el resultat de treball) es desen amb l'any dins la carpeta
    de sessió: abans el 2026 i el 2027 compartien la mateixa còpia i
    canviar d'any se la trepitjava."""

    PER_YEAR = [
        "data/weekday/day_info.csv",
        "data/weekday/calendar_slots.csv",
        "outputs/schedule_weekday.csv",
        "outputs/metrics_weekday.csv",
    ]

    def _write(self, ws: Path, rel: str, text: str) -> None:
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8-sig")

    def test_each_year_keeps_its_own_copy(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.chdir(ws)
        sess = tmp_path / "Mama"
        last = tmp_path / ".last_session"
        pdfs = tmp_path / "pdfs"

        for rel in self.PER_YEAR:
            self._write(ws, rel, "cap\nsoc del 2026\n")
        save_session_folder(sess, 2026, 1, "Mama", last, pdfs)

        for rel in self.PER_YEAR:
            self._write(ws, rel, "cap\nsoc del 2027\n")
        save_session_folder(sess, 2027, 1, "Mama", last, pdfs)

        # Tornem al 2026: ha de recuperar el SEU contingut.
        for rel in self.PER_YEAR:
            (ws / rel).unlink()
        load_session_folder(sess, 2026, 1, pdfs)
        for rel in self.PER_YEAR:
            assert "2026" in (ws / rel).read_text(encoding="utf-8-sig"), (
                "%s s'ha trepitjat amb les dades de l'altre any" % rel
            )

    def test_old_sessions_without_the_year_still_load(self, tmp_path, monkeypatch):
        # Compatibilitat: les sessions ja desades tenen el nom sense any.
        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.chdir(ws)
        sess = tmp_path / "Mama"
        for rel in self.PER_YEAR:
            self._write(sess, rel, "cap\nformat antic\n")

        load_session_folder(sess, 2026, 1, tmp_path / "pdfs")
        for rel in self.PER_YEAR:
            assert (ws / rel).exists(), "no s'ha llegit el format antic de %s" % rel
