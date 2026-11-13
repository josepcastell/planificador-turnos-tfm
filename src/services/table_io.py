import os
import tempfile
from pathlib import Path

import pandas as pd


class TableFormatError(RuntimeError):
    """El CSV existeix però no es pot interpretar amb l'esquema esperat
    (separador/encoding canviats per Excel, fitxer corrupte...). Es llança
    en lloc de sintetitzar columnes buides: si es continués, el primer
    autosave REESCRIURIA el fitxer amb valors buits i es perdria tot."""


def _read_csv_resilient(path: Path) -> pd.DataFrame:
    """pd.read_csv tolerant amb els CSV re-desats per Excel:
    - encoding: utf-8/utf-8-sig primer; si falla (Excel «ANSI»), cp1252.
    - separador: coma; es reintenta amb ';' si la capçalera surt d'una
      sola columna (Excel amb configuració regional catalana/espanyola)."""
    last_err: Exception | None = None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            df = pd.read_csv(path, encoding=enc)
            if df.shape[1] == 1 and ";" in str(df.columns[0]):
                df = pd.read_csv(path, encoding=enc, sep=";")
            return df
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise TableFormatError(
        f"No s'ha pogut llegir «{path}»: codificació no reconeguda. "
        "Si l'has desat amb Excel, torna a desar-lo com a «CSV UTF-8»."
    ) from last_err


def read_table(path: Path, columns: list[str]) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        try:
            df = _read_csv_resilient(path)
        except pd.errors.ParserError as e:
            raise TableFormatError(
                f"El fitxer «{path}» està malmès i no es pot llegir ({e}). "
                "Restaura'l des d'una versió guardada o esborra'l perquè "
                "es torni a crear buit."
            ) from e
        # Si CAP columna esperada apareix a la capçalera real, el fitxer no
        # és el que esperem: MAI sintetitzem totes les columnes buides (el
        # primer autosave esborraria les dades reals en silenci).
        if columns and df.shape[1] > 0 and not any(c in df.columns for c in columns):
            raise TableFormatError(
                f"El fitxer «{path}» no té cap de les columnes esperades "
                f"({', '.join(columns)}). Si l'has desat amb Excel, revisa "
                "que el separador sigui la coma i el format «CSV UTF-8»."
            )
    else:
        df = pd.DataFrame(columns=columns)

    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns].copy()


def save_table(path: Path, df: pd.DataFrame, columns: list[str]) -> None:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = ""
    out = out[columns].copy()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Escriptura ATÒMICA (temporal + os.replace): un tall a mig desat no
    # deixa mai el CSV truncat. utf-8-sig: Excel mostra bé els accents.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as fh:
            out.to_csv(fh, index=False)
        os.replace(tmp_path, path)
    except PermissionError as e:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"No s'ha pogut desar «{path.name}»: el fitxer està en ús. "
            "Si el tens obert a Excel, tanca'l i torna-ho a provar."
        ) from e
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def normalize_bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "si", "sí", "y", "x"}


def normalize_for_comparison(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.reindex(columns=columns).copy().reset_index(drop=True)
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]) or col == "day" or col.endswith("_day"):
            out[col] = pd.to_datetime(out[col], errors="coerce").dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_bool_dtype(out[col]):
            out[col] = out[col].astype(int)
        elif pd.api.types.is_numeric_dtype(out[col]):
            numeric = pd.to_numeric(out[col], errors="coerce")
            out[col] = numeric.map(lambda value: "" if pd.isna(value) else f"{value:g}")
        else:
            out[col] = out[col].map(
                lambda value: int(value)
                if isinstance(value, bool)
                else str(value).strip()
                if not pd.isna(value)
                else ""
            )
    out = out.fillna("")
    if not out.empty:
        out = out.sort_values(list(out.columns), kind="mergesort").reset_index(drop=True)
    return out


def dataframe_changed(left: pd.DataFrame, right: pd.DataFrame, columns: list[str] | None = None) -> bool:
    compare_columns = columns or list(dict.fromkeys(list(left.columns) + list(right.columns)))
    left_cmp = normalize_for_comparison(left, compare_columns)
    right_cmp = normalize_for_comparison(right, compare_columns)
    return not left_cmp.equals(right_cmp)


def ensure_csv_file(path: Path, columns: list[str]) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    save_table(path, pd.DataFrame(columns=columns), columns)
