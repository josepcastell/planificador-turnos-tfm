"""Construeix Planner_portable v1.2.0 fent SWAP sobre el zip publicat:
- substitueix {prefix}app/src/**, app.py, VERSION
- substitueix els llançadors (run.bat, Planificador.vbs, _stop.bat)
- conserva python/ i app/data (ja verificats nets al zip previ)
- stream-copy preservant compress_type (STORED no es recomprimeix)
"""
import sys
import zipfile
from pathlib import Path

SRC_ZIP = Path("/home/josep/_relbuild/Planner_portable.zip")
OUT_ZIP = Path("/home/josep/_relbuild/Planner_portable_new.zip")
EXPORT = Path(sys.argv[1])          # export net del codi (app.py, VERSION, src/)
LAUNCHERS = Path("/mnt/c/Users/jca19/Desktop/Planner_portable/Planner_portable")

zin = zipfile.ZipFile(SRC_ZIP)
names = zin.namelist()
app_py = next(n for n in names if n.endswith("app/app.py"))
prefix = app_py[: -len("app/app.py")]
print("prefix del zip:", repr(prefix))

drop_prefixes = (f"{prefix}app/src/",)
drop_exact = {
    f"{prefix}app/app.py", f"{prefix}app/VERSION",
    f"{prefix}run.bat", f"{prefix}Planificador.vbs", f"{prefix}_stop.bat",
}
dropped = kept = 0
with zipfile.ZipFile(OUT_ZIP, "w") as zout:
    for info in zin.infolist():
        n = info.filename
        if n in drop_exact or n.startswith(drop_prefixes):
            dropped += 1
            continue
        zout.writestr(info, zin.read(n), compress_type=info.compress_type)
        kept += 1
    # Codi nou
    added = 0
    for f in sorted(EXPORT.rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(EXPORT).as_posix()
        if rel == "app.py" or rel == "VERSION" or rel.startswith("src/"):
            zout.write(f, f"{prefix}app/{rel}", zipfile.ZIP_DEFLATED)
            added += 1
    # Llançadors nous (des del portable del Desktop, ja actualitzats)
    for name in ("run.bat", "Planificador.vbs", "_stop.bat"):
        zout.write(LAUNCHERS / name, f"{prefix}{name}", zipfile.ZIP_DEFLATED)
        added += 1
    # Carpeta de PDFs autocontinguda (entrada de directori)
    if not any(n.startswith(f"{prefix}dades/") for n in names):
        zout.writestr(zipfile.ZipInfo(f"{prefix}dades/PDFs/"), b"")
        added += 1

print(f"copiades {kept}, substituides/eliminades {dropped}, afegides {added}")

# Verificacions del zip resultant
zr = zipfile.ZipFile(OUT_ZIP)
version = zr.read(f"{prefix}app/VERSION").decode().strip()
assert version == "1.2.0", version
leaky = []
for n in zr.namelist():
    if n.startswith(f"{prefix}app/data/") and n.endswith(".csv"):
        lines = zr.read(n).decode("utf-8", "replace").strip().splitlines()
        if len(lines) > 1:
            leaky.append((n, len(lines)))
assert not leaky, leaky
assert not any("Sessions_planificador" in n or ".git" in n for n in zr.namelist())
runbat = zr.read(f"{prefix}run.bat").decode("utf-8", "replace")
assert "127.0.0.1" in runbat
print(f"VERIFICAT: VERSION={version}, data/ nomes capçaleres, launcher 127.0.0.1")
print("mida (MB):", round(OUT_ZIP.stat().st_size / 1e6, 1))
