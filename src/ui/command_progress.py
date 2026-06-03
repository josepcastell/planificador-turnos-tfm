import os
import subprocess

import streamlit as st


def progress_from_line(line: str, current: int, total_steps: int) -> int:
    text = line.strip()
    if "=== Generant planning" in text:
        for month_number in range(1, 13):
            if f"-{month_number:02d}" in text:
                return max(current, month_number)
    if "[1/2]" in text or "[1/3]" in text:
        return max(current, 1)
    if "[2/2]" in text:
        return max(current, total_steps)
    if "[2/3]" in text:
        return max(current, min(total_steps, 2))
    if "[3/3]" in text:
        return max(current, total_steps)
    if "PDFs generats per" in text or "Planning anual" in text:
        return total_steps
    return current


def run_steps_with_progress(steps, action_name: str, total_steps: int = 4, container=None):
    """Executa una llista de comandes (cadascuna en format argv:
    `list[str]`) seqüencialment, fent streaming del stdout al progress
    bar. S'atura a la primera que retorna != 0. Retorna (codi_final,
    stdout_combinat, stderr_combinat).

    No usa shell — `subprocess.Popen` rep directament la llista d'argv,
    cosa que el fa portable a Windows, macOS i Linux sense bash/WSL."""
    ctx = container if container is not None else st
    progress_bar = ctx.progress(0, text=f"{action_name}: iniciant...")
    out_lines: list[str] = []
    err_lines: list[str] = []
    progress_step = 0
    final_code = 0
    if not steps:
        progress_bar.progress(1.0, text=f"{action_name}: completat")
        return 0, "", ""
    for step_cmd in steps:
        proc = subprocess.Popen(
            step_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            # Forcem UTF-8 al subprocés i a la lectura: en Windows el codi
            # del solver pot emetre caracters Unicode (p. ex. el simbol
            # d'infinit) que la codificacio per defecte (cp1252) no sap
            # codificar, i la generacio fallaria.
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        if proc.stdout is not None:
            for line in proc.stdout:
                out_lines.append(line)
                progress_step = progress_from_line(line, progress_step, total_steps)
                progress_value = min(0.95, max(0.05, progress_step / max(1, total_steps)))
                progress_bar.progress(progress_value, text=f"{action_name}: en procés...")
        if proc.stderr is not None:
            err_lines.append(proc.stderr.read())
        code = proc.wait()
        if code != 0:
            final_code = code
            break
    if final_code == 0:
        progress_bar.progress(1.0, text=f"{action_name}: completat")
    else:
        progress_bar.progress(1.0, text=f"{action_name}: ha fallat")
    return final_code, "".join(out_lines), "".join(err_lines)


def run_and_store(action_name, steps, completed_key=None, total_steps: int = 4, container=None):
    """Wrapper que executa els steps i deixa a `st.session_state` el
    resultat (stdout/stderr) perquè la UI els pugui mostrar a posteriori.

    `steps` és una llista d'argv (`list[list[str]]`); si es passa una
    sola comanda (`list[str]`) també s'accepta i es tracta com a una
    única passa."""
    if steps and isinstance(steps[0], str):
        steps = [steps]
    code, out, err = run_steps_with_progress(
        steps, action_name, total_steps=total_steps, container=container
    )
    st.session_state["last_action_name"] = action_name
    st.session_state["last_action_code"] = code
    st.session_state["last_action_stdout"] = out
    st.session_state["last_action_stderr"] = err
    if completed_key is not None and code == 0:
        st.session_state[completed_key] = True
    if code != 0:
        detail = "\n".join(part.strip() for part in [out, err] if part and part.strip())
        if detail:
            tail = "\n".join(detail.splitlines()[-12:])
            err_ctx = container if container is not None else st
            err_ctx.error("L'acció ha fallat. Revisa el detall tècnic.")
            err_ctx.code(tail, language="text")
    return code
