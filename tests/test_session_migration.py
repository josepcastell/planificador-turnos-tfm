"""Migració única d'arrels de sessions antigues (Desktop /
dades/sessions → arrel actual). Vegeu session_store.migrate_legacy_session_roots."""

from pathlib import Path

from src.services.session_store import migrate_legacy_session_roots


def _mk_session(root: Path, name: str, payload: str = "x") -> Path:
    d = root / name
    (d / "data").mkdir(parents=True)
    (d / "session.txt").write_text(f"section={name}\n", encoding="utf-8")
    (d / "data" / "professionals.csv").write_text(
        f"professional_id\n{payload}\n", encoding="utf-8"
    )
    return d


class TestMigrateLegacyRoots:
    def test_copies_sessions_when_current_empty(self, tmp_path):
        current = tmp_path / "nou"
        legacy = tmp_path / "antic"
        legacy.mkdir()
        _mk_session(legacy, "Seccio_2026")
        (legacy / ".last_session").write_text("Seccio_2026", encoding="utf-8")
        n = migrate_legacy_session_roots(current, [legacy])
        assert n == 1
        assert (current / "Seccio_2026" / "data" / "professionals.csv").exists()
        assert (current / ".last_session").read_text(encoding="utf-8") == "Seccio_2026"
        # L'original NO s'esborra (còpia de seguretat).
        assert (legacy / "Seccio_2026" / "session.txt").exists()

    def test_noop_when_current_has_sessions(self, tmp_path):
        current = tmp_path / "nou"
        current.mkdir()
        _mk_session(current, "Existent_2026")
        legacy = tmp_path / "antic"
        legacy.mkdir()
        _mk_session(legacy, "Antiga_2026")
        assert migrate_legacy_session_roots(current, [legacy]) == 0
        assert not (current / "Antiga_2026").exists()

    def test_noop_when_no_legacy(self, tmp_path):
        current = tmp_path / "nou"
        assert migrate_legacy_session_roots(
            current, [tmp_path / "inexistent"]
        ) == 0

    def test_ignores_folders_without_manifest(self, tmp_path):
        current = tmp_path / "nou"
        legacy = tmp_path / "antic"
        (legacy / "no_es_sessio").mkdir(parents=True)
        assert migrate_legacy_session_roots(current, [legacy]) == 0

    def test_first_legacy_root_with_sessions_wins(self, tmp_path):
        current = tmp_path / "nou"
        l1 = tmp_path / "antic1"
        l2 = tmp_path / "antic2"
        l1.mkdir(); l2.mkdir()
        _mk_session(l1, "Bona_2026")
        _mk_session(l2, "Altra_2026")
        assert migrate_legacy_session_roots(current, [l1, l2]) == 1
        assert (current / "Bona_2026").exists()
        assert not (current / "Altra_2026").exists()

    def test_same_root_is_skipped(self, tmp_path):
        current = tmp_path / "nou"
        current.mkdir()
        assert migrate_legacy_session_roots(current, [current]) == 0
