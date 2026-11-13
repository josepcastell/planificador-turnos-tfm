# Planificador de turnos hospitalarios (TFM)

Sistema de apoyo a la decisión para planificar los turnos de entre semana de una
sección hospitalaria. El calendario se resuelve como un modelo de optimización con
restricciones (**Google OR-Tools, CP-SAT**), por tramos de prioridad: primero la
cobertura y después la equidad. Interfaz en **Streamlit**.

Trabajo Final del Máster en Bioinformática y Bioestadística (UOC).

> **Sin datos.** Por confidencialidad, los CSV de `data/` solo contienen las
> cabeceras: la configuración (facultativos, actividades, franjas, ausencias…) se
> introduce desde la interfaz.

## Uso

**Portable para Windows**, sin instalar nada:
[descargar Planner_portable.zip](https://github.com/josepcastell/planificador-turnos-tfm/releases/latest/download/Planner_portable.zip).
Descomprímelo y haz doble clic en `run.bat`. El botón **Actualizar** de la barra
lateral instala las versiones nuevas.

**Desde el código** (Python 3.11 o superior):

```bash
python -m venv .venv
.venv\Scripts\activate             # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

`deploy/build_portable_windows.ps1` construye el portable a partir del código.

## Código

| Carpeta | Contenido |
|---|---|
| `app.py`, `src/ui/` | Interfaz. |
| `src/services/`, `src/core/`, `src/domain/` | Datos, sesiones y reglas. |
| `src/solver/`, `src/modules/` | Modelo CP-SAT y generación del calendario. |
| `src/tools/` | Calendario base y exportación a PDF/Excel. |
| `tests/` | Pruebas (`python -m pytest tests`). |
