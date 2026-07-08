from __future__ import annotations

import filecmp
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from src.domain.schemas import CSV_HEADERS


@dataclass(frozen=True)
class SessionFileSpec:
    """Single source of truth for a file in the session lifecycle.

    saved_as: "input" copied input/ "generated" copied output / None transient.
    on_new_session: "keep" left alone / "blank" reinit with blank_header / "delete" removed.
    """
    path_template: str
    saved_as: str | None
    cleanup_group: str | None = None
    on_new_session: str = "keep"
    blank_header: str | None = None


_SESSION_FILE_REGISTRY: list[SessionFileSpec] = [
    # Festius i calendari base
    SessionFileSpec(
        "data/derived/public_holidays_{year}.csv",
        saved_as="input", cleanup_group="Festius i calendari base",
        on_new_session="blank",
        blank_header=CSV_HEADERS["data/derived/public_holidays_{year}.csv"],
    ),
    SessionFileSpec(
        "data/base_calendar_overrides_{year}.csv",
        saved_as="input", cleanup_group="Festius i calendari base",
        on_new_session="blank",
        blank_header=CSV_HEADERS["data/base_calendar_overrides_{year}.csv"],
    ),
    SessionFileSpec(
        "data/base_calendar_{year}.csv",
        saved_as="generated", cleanup_group="Festius i calendari base",
        on_new_session="delete",
    ),
    SessionFileSpec(
        "data/weekday/day_info.csv",
        saved_as="generated", cleanup_group="Festius i calendari base",
        on_new_session="delete",
    ),
    # Franges puntuals i calendaris de mòduls
    SessionFileSpec(
        "data/weekday/template_overrides_{year}.csv",
        saved_as="input", cleanup_group="Franges puntuals i calendaris de mòduls",
        on_new_session="delete",
    ),
    SessionFileSpec(
        "data/weekday/calendar_slots.csv",
        saved_as="generated", cleanup_group="Franges puntuals i calendaris de mòduls",
        on_new_session="delete",
    ),
    # Indisponibilitats, guàrdies i reduccions
    SessionFileSpec(
        "data/guards/assignments.csv",
        saved_as="input", cleanup_group="Indisponibilitats, guàrdies i reduccions",
        on_new_session="blank", blank_header=CSV_HEADERS["data/guards/assignments.csv"],
    ),
    SessionFileSpec(
        "data/absences/assignments.csv",
        saved_as="input", cleanup_group="Indisponibilitats, guàrdies i reduccions",
        on_new_session="blank", blank_header=CSV_HEADERS["data/absences/assignments.csv"],
    ),
    SessionFileSpec(
        "data/weekday/unavailability.csv",
        saved_as="input", cleanup_group="Indisponibilitats, guàrdies i reduccions",
        on_new_session="blank", blank_header=CSV_HEADERS["data/weekday/unavailability.csv"],
    ),
    # Assignacions manuals
    SessionFileSpec(
        "data/weekday/preassignments.csv",
        saved_as="input", cleanup_group="Assignacions manuals",
        on_new_session="blank", blank_header=CSV_HEADERS["data/weekday/preassignments.csv"],
    ),
    SessionFileSpec(
        "data/weekday/fixed_machines.csv",
        saved_as="input", cleanup_group="Assignacions manuals",
        on_new_session="blank", blank_header=CSV_HEADERS["data/weekday/fixed_machines.csv"],
    ),
    # Comitès
    SessionFileSpec(
        "data/comite/assignments.csv",
        saved_as="input", cleanup_group="Comitès",
        on_new_session="blank", blank_header=CSV_HEADERS["data/comite/assignments.csv"],
    ),
    # Objectius de mètriques
    # Restriccions derivades
    SessionFileSpec(
        "data/derived/guard_constraints_{year}.csv",
        saved_as="generated", cleanup_group="Restriccions derivades",
        on_new_session="delete",
    ),
    SessionFileSpec(
        "data/derived/unavailability_from_absences_{year}.csv",
        saved_as="generated", cleanup_group="Restriccions derivades",
        on_new_session="delete",
    ),
    SessionFileSpec(
        "data/derived/unavailability_{year}.csv",
        saved_as="generated", cleanup_group="Restriccions derivades",
        on_new_session="delete",
    ),
    SessionFileSpec(
        "data/derived/unavailability_weekday_{year}.csv",
        saved_as="generated", cleanup_group="Restriccions derivades",
        on_new_session="delete",
    ),
    SessionFileSpec(
        "data/derived/preassignments_weekday_{year}.csv",
        saved_as="generated", cleanup_group="Restriccions derivades",
        on_new_session="delete",
    ),
    SessionFileSpec(
        "data/derived/guard_schedule_annotations_{year}.csv",
        saved_as="generated", cleanup_group="Restriccions derivades",
        on_new_session="delete",
    ),
    # Planning i mètriques
    SessionFileSpec(
        "outputs/schedule_weekday.csv",
        saved_as="generated", cleanup_group="Planning i mètriques",
        on_new_session="delete",
    ),
    SessionFileSpec(
        "outputs/metrics_weekday.csv",
        saved_as="generated", cleanup_group="Planning i mètriques",
        on_new_session="delete",
    ),
    SessionFileSpec(
        "outputs/schedule_weekday_before_reajust.csv",
        saved_as=None, cleanup_group="Planning i mètriques",
        on_new_session="delete",
    ),
    # Dades mestres
    SessionFileSpec(
        "data/professionals.csv",
        saved_as="input", cleanup_group="Dades mestres",
    ),
    SessionFileSpec(
        "data/eligibility.csv",
        saved_as="input", cleanup_group="Dades mestres",
    ),
    SessionFileSpec(
        "data/weekday/weekly_slot_templates.csv",
        saved_as="input", cleanup_group="Dades mestres",
        on_new_session="blank",
        blank_header=CSV_HEADERS["data/weekday/weekly_slot_templates.csv"],
    ),
    SessionFileSpec(
        "data/slot_catalog.csv",
        saved_as="input", cleanup_group="Dades mestres",
        on_new_session="blank",
        blank_header=CSV_HEADERS["data/slot_catalog.csv"],
    ),
]


def _spec_path(spec: SessionFileSpec, year: int) -> Path:
    return Path(spec.path_template.format(year=year))


def list_session_folders(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        [p for p in root.iterdir() if p.is_dir()],
        key=lambda p: p.name.lower(),
    )


def read_session_metadata(session_dir: Path) -> dict[str, str]:
    manifest = session_dir / "session.txt"
    if not manifest.exists():
        return {}
    data = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def read_last_session_name(last_session_path: Path, session_root: Path) -> str:
    if not last_session_path.exists():
        return ""
    name = last_session_path.read_text(encoding="utf-8").strip()
    if not name:
        return ""
    return name if (session_root / name).is_dir() else ""


def write_last_session_name(session_dir: Path, last_session_path: Path) -> None:
    last_session_path.parent.mkdir(parents=True, exist_ok=True)
    last_session_path.write_text(session_dir.name, encoding="utf-8")


def infer_section_year_from_session_name(session_name: str, default_year: int) -> tuple[str, int]:
    if "_" in session_name:
        section_part, year_part = session_name.rsplit("_", 1)
        if year_part.isdigit():
            return section_part, int(year_part)
    return "Seccio", default_year


def csv_has_data_rows(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if index > 0 and line.strip().strip(","):
                return True
    except UnicodeDecodeError:
        return path.stat().st_size > 0
    return False


def copy_carry_forward_files_to_session(
    session_dir: Path,
    carry_forward_files: list[Path],
    overwrite_existing: bool = False,
    source_root: Path | None = None,
) -> int:
    copied = 0
    for relative_source in carry_forward_files:
        source = source_root / relative_source if source_root else relative_source
        if not source.exists() or source.stat().st_size == 0:
            continue
        target = session_dir / relative_source
        if target.exists() and not overwrite_existing and csv_has_data_rows(target):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def mark_carry_forward_seeded(session_dir: Path, source_root: Path | None) -> None:
    source_label = str(source_root) if source_root else "workspace"
    (session_dir / ".carry_forward_seeded").write_text(
        f"source={source_label}\nseeded_at={datetime.now().isoformat(timespec='seconds')}\n",
        encoding="utf-8",
    )


def seed_carry_forward_files_if_needed(
    session_dir: Path,
    carry_forward_files: list[Path],
    source_root: Path | None = None,
) -> bool:
    marker = session_dir / ".carry_forward_seeded"
    if marker.exists():
        return False
    copied = copy_carry_forward_files_to_session(
        session_dir,
        carry_forward_files,
        overwrite_existing=False,
        source_root=source_root,
    )
    mark_carry_forward_seeded(session_dir, source_root)
    return copied > 0


def session_input_file_pairs(year: int, month: int) -> list[tuple[Path, Path]]:
    return [
        (_spec_path(s, year), _spec_path(s, year))
        for s in _SESSION_FILE_REGISTRY
        if s.saved_as == "input"
    ]


def session_generated_file_pairs(year: int, month: int) -> list[tuple[Path, Path]]:
    return [
        (_spec_path(s, year), _spec_path(s, year))
        for s in _SESSION_FILE_REGISTRY
        if s.saved_as == "generated"
    ]


def session_file_pairs(year: int, month: int) -> list[tuple[Path, Path]]:
    return session_input_file_pairs(year, month) + session_generated_file_pairs(year, month)


def copy_file_if_needed(source: Path, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        return False
    if target.exists() and source.stat().st_size == target.stat().st_size:
        try:
            if filecmp.cmp(source, target, shallow=False):
                return False
        except OSError:
            pass
    shutil.copy2(source, target)
    return True


def dynamic_session_file_pairs(year: int, pdf_output_dir: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []

    for pattern in [f"schedule_{year}_*.csv", f"metrics_weekday_{year}_*.csv"]:
        for source in Path("outputs").glob(pattern):
            if source.is_file():
                pairs.append((source, Path("outputs") / source.name))

    for pattern in [
        f"general_{year}_*.pdf",
        f"general_calendar_{year}_*.pdf",
        f"metrics_{year}_*.pdf",
        f"metrics_{year}_*.xlsx",
    ]:
        for source in pdf_output_dir.glob(pattern):
            if source.is_file():
                pairs.append((source, Path("exports") / source.name))

    for source_dir in pdf_output_dir.glob(f"individual_calendars_{year}_*"):
        if not source_dir.is_dir():
            continue
        for source in source_dir.rglob("*"):
            if source.is_file():
                relative_export = source.relative_to(pdf_output_dir)
                pairs.append((source, Path("exports") / relative_export))

    return pairs


def session_manifest(year: int, month: int, section_name: str, timestamp_label: str = "saved_at") -> str:
    return (
        f"year={year}\n"
        f"month={month}\n"
        f"section={section_name}\n"
        f"{timestamp_label}={datetime.now().isoformat(timespec='seconds')}\n"
    )


def save_session_folder(
    session_dir: Path,
    year: int,
    month: int,
    section_name: str,
    last_session_path: Path,
    pdf_output_dir: Path,
    include_generated: bool = True,
) -> int:
    session_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    pairs = session_input_file_pairs(year, month)
    if include_generated:
        pairs += session_generated_file_pairs(year, month) + dynamic_session_file_pairs(year, pdf_output_dir)
    for source, relative_target in pairs:
        if source.exists() and source.stat().st_size > 0:
            target = session_dir / relative_target
            if copy_file_if_needed(source, target):
                copied += 1

    (session_dir / "session.txt").write_text(session_manifest(year, month, section_name), encoding="utf-8")
    write_last_session_name(session_dir, last_session_path)
    return copied


def load_session_folder(session_dir: Path, year: int, month: int, pdf_output_dir: Path) -> int:
    copied = 0
    for current_path, session_relative_path in session_file_pairs(year, month):
        source = session_dir / session_relative_path
        if not source.exists():
            alt_source = session_dir / current_path
            source = alt_source if alt_source.exists() else source
        if source.exists() and source.stat().st_size > 0:
            if copy_file_if_needed(source, current_path):
                copied += 1

    session_outputs_dir = session_dir / "outputs"
    if session_outputs_dir.exists():
        for source in session_outputs_dir.glob(f"schedule_{year}_*.csv"):
            target = Path("outputs") / source.name
            if copy_file_if_needed(source, target):
                copied += 1
        for source in session_outputs_dir.glob(f"metrics_weekday_{year}_*.csv"):
            target = Path("outputs") / source.name
            if copy_file_if_needed(source, target):
                copied += 1

    session_exports_dir = session_dir / "exports"
    if session_exports_dir.exists():
        for source in session_exports_dir.glob(f"general_{year}_*.pdf"):
            target = pdf_output_dir / source.name
            if copy_file_if_needed(source, target):
                copied += 1
        for source in session_exports_dir.glob(f"general_calendar_{year}_*.pdf"):
            target = pdf_output_dir / source.name
            if copy_file_if_needed(source, target):
                copied += 1
        for source in session_exports_dir.glob(f"metrics_{year}_*.pdf"):
            target = pdf_output_dir / source.name
            if copy_file_if_needed(source, target):
                copied += 1
        for source in session_exports_dir.glob(f"metrics_{year}_*.xlsx"):
            target = pdf_output_dir / source.name
            if copy_file_if_needed(source, target):
                copied += 1

        for source_dir in session_exports_dir.glob(f"individual_calendars_{year}_*"):
            if not source_dir.is_dir():
                continue
            for source in source_dir.rglob("*"):
                if not source.is_file():
                    continue
                rel = source.relative_to(session_exports_dir)
                target = pdf_output_dir / rel
                if copy_file_if_needed(source, target):
                    copied += 1
    return copied


SNAPSHOTS_DIRNAME = "_snapshots"


def workspace_has_user_data(year: int) -> bool:
    """Return True if any input working file has non-header content. Used to
    detect autosaved state across app restarts."""
    for spec in _SESSION_FILE_REGISTRY:
        if spec.saved_as != "input":
            continue
        if csv_has_data_rows(_spec_path(spec, year)):
            return True
    return False


def _session_live_items(session_dir: Path):
    for item in session_dir.iterdir():
        if item.name == SNAPSHOTS_DIRNAME:
            continue
        yield item


def delete_session_folder(session_dir: Path) -> bool:
    """Elimina completament una sessió guardada i tots els seus snapshots.
    Retorna True si s'ha eliminat la carpeta."""
    if not session_dir.exists():
        return False
    shutil.rmtree(session_dir)
    return True


def create_session_snapshot(session_dir: Path) -> Path | None:
    """Còpia recursiva de session_dir dins session_dir/_snapshots/<ts>/.
    Retorna la ruta de la versió, o None si session_dir no existeix."""
    if not session_dir.exists():
        return None
    snapshots_root = session_dir / SNAPSHOTS_DIRNAME
    snapshots_root.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_path = snapshots_root / base
    suffix = 1
    while snapshot_path.exists():
        snapshot_path = snapshots_root / f"{base}_{suffix}"
        suffix += 1
    snapshot_path.mkdir(parents=True)
    for item in _session_live_items(session_dir):
        target = snapshot_path / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    return snapshot_path


def list_session_snapshots(session_dir: Path) -> list[Path]:
    snapshots_root = session_dir / SNAPSHOTS_DIRNAME
    if not snapshots_root.exists():
        return []
    return sorted(
        [p for p in snapshots_root.iterdir() if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )


def restore_session_snapshot(
    snapshot_dir: Path,
    session_dir: Path,
    year: int,
    month: int,
    pdf_output_dir: Path,
) -> int:
    """Substitueix el contingut viu de session_dir (preservant _snapshots/)
    pel de snapshot_dir, i refresca els fitxers de treball."""
    if not snapshot_dir.exists() or not session_dir.exists():
        return 0
    for item in list(_session_live_items(session_dir)):
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    for item in snapshot_dir.iterdir():
        target = session_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    return load_session_folder(session_dir, year, month, pdf_output_dir)


def session_cleanup_targets(year: int) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for spec in _SESSION_FILE_REGISTRY:
        if spec.cleanup_group is None:
            continue
        out.setdefault(spec.cleanup_group, []).append(_spec_path(spec, year))
    return out


def delete_path_if_exists(path: Path) -> int:
    if path.exists() and path.is_file():
        path.unlink()
        return 1
    if path.exists() and path.is_dir():
        shutil.rmtree(path)
        return 1
    return 0


def delete_current_session_workspace(session_dir: Path, year: int, month: int, pdf_output_dir: Path) -> int:
    paths: list[Path] = []
    paths.extend(path for path, _ in session_file_pairs(year, month))
    paths.extend(path for path, _ in dynamic_session_file_pairs(year, pdf_output_dir))
    for target_group in session_cleanup_targets(year).values():
        paths.extend(target_group)

    deleted = 0
    seen: set[str] = set()
    for relative_path in paths:
        for path in [relative_path, session_dir / relative_path]:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            deleted += delete_path_if_exists(path)

    entre_setmana_dir = pdf_output_dir / "entre_setmana"
    session_exports_dir = session_dir / "exports"
    for pattern in [
        f"general_{year}_*.pdf",
        f"general_calendar_{year}_*.pdf",
        f"by_professional_{year}_*.pdf",
        f"metrics_{year}_*.pdf",
        f"metrics_{year}_*.xlsx",
        f"individual_calendars_{year}_*",
    ]:
        for path in pdf_output_dir.glob(pattern):
            deleted += delete_path_if_exists(path)
        # També al subdirectori `entre_setmana/` on viuen els PDF principals
        # del planning auto-renderitzat des de la pestanya Generar.
        if entre_setmana_dir.exists():
            for path in entre_setmana_dir.glob(pattern):
                deleted += delete_path_if_exists(path)
        if session_exports_dir.exists():
            for path in session_exports_dir.glob(pattern):
                deleted += delete_path_if_exists(path)

    return deleted



def blank_session_files(year: int) -> dict[str, str]:
    return {
        spec.path_template.format(year=year): spec.blank_header
        for spec in _SESSION_FILE_REGISTRY
        if spec.blank_header is not None
    }


def reset_current_workspace_for_new_session(year: int) -> None:
    for relative_path, content in blank_session_files(year).items():
        path = Path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    files_to_remove: list[Path] = [
        _spec_path(spec, year)
        for spec in _SESSION_FILE_REGISTRY
        if spec.on_new_session == "delete"
    ]
    files_to_remove.extend(Path("outputs").glob(f"schedule_{year}_*.csv"))
    files_to_remove.extend(Path("outputs").glob(f"metrics_weekday_{year}_*.csv"))

    for path in files_to_remove:
        if path.exists() and path.is_file():
            path.unlink()


def create_empty_session_folder(
    session_dir: Path,
    year: int,
    section_name: str,
    carry_forward_files: list[Path],
    carry_forward_source: Path | None = None,
) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in blank_session_files(year).items():
        path = session_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    copy_carry_forward_files_to_session(
        session_dir,
        carry_forward_files,
        overwrite_existing=True,
        source_root=carry_forward_source,
    )
    mark_carry_forward_seeded(session_dir, carry_forward_source)

    (session_dir / "session.txt").write_text(
        session_manifest(year, 1, section_name, timestamp_label="created_at"),
        encoding="utf-8",
    )
