# Planificador de turnos hospitalarios (TFM)

Prototipo de **sistema de apoyo a la decisión** para la planificación de turnos de
trabajo de entre semana en una sección hospitalaria con actividad continuada.
Forma parte del **Trabajo Final del Máster en Bioinformática y Bioestadística (UOC)**.

El problema se formula como un modelo de **optimización con restricciones** y se
resuelve con **Google OR-Tools (CP-SAT)**, mediante una **jerarquía lexicográfica
por tramos** (cobertura presencial → cobertura no presencial → equidad de
presencialidad → equidad de la carga ordinaria). La interfaz es **Streamlit**.

## ⚠️ Sin datos precargados

Por **confidencialidad**, este repositorio se entrega **sin datos reales del
servicio**: los ficheros CSV de `data/` contienen únicamente sus cabeceras. La
persona usuaria introduce su propia configuración (facultativos, actividades,
franjas, festivos, ausencias, guardias…) desde la interfaz antes de generar un
calendario.

## Requisitos e instalación

Requiere **Python 3.11 o superior** (probado con Python 3.13). El entorno virtual
(`.venv`) no forma parte del repositorio: cada persona crea el suyo con los
comandos siguientes.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecución

```bash
streamlit run app.py
```

Se abre en el navegador. En `deploy/` se incluye `build_portable_windows.ps1`, el
script que **construye** un empaquetado portable para Windows (ejecutable sin
instalación ni permisos de administrador) a partir del código.

### Descargar el portable ya construido (doble clic)

Si no quieres instalar nada, descarga el empaquetado portable desde la pestaña
[**Releases**](https://github.com/josepcastell/planificador-turnos-tfm/releases):
descomprime `Planner_portable.zip` y haz doble clic en `run.bat`. Se entrega sin
datos; la configuración se introduce desde la propia interfaz.

## Estructura del código

| Carpeta | Responsabilidad |
|---|---|
| `app.py` | Punto de entrada (Streamlit). |
| `src/ui/` | Interfaz: edición de entradas, generación, métricas. |
| `src/services/` | Persistencia de sesiones, edición, preparación de datos, exportación. |
| `src/core/`, `src/domain/` | Lectura de datos, constantes, esquemas y reglas. |
| `src/modules/`, `src/solver/` | Generación del calendario y modelo CP-SAT. |
| `src/tools/` | Calendario base, capas de indisponibilidad, exportación a PDF/Excel. |
| `tests/` | Prueba de humo de extremo a extremo. |
| `deploy/` | Script para construir el empaquetado portable para Windows. |

## Prueba rápida

```bash
python tests/smoke_generation.py --year 2026 --month 6
```

(requiere haber introducido datos de configuración).

---

Trabajo Final de Máster · Bioinformática y Bioestadística · UOC.
