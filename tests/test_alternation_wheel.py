"""Alternança setmanal de franges (1 de cada N) + roda d'assignació."""

import pandas as pd

from src.services.wheel_assignments import (
    expand_wheel_preassignments, load_wheel, save_wheel,
)
from src.tools.build_weekday_calendar_from_templates import (
    build_weekday_calendar_from_templates,
)

# Gener 2026: dilluns 5, 12, 19, 26 → setmanes ISO 2, 3, 4, 5.
MONDAYS = ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]


def _write_inputs(tmp_path, week_interval, week_offset):
    base = tmp_path / "base_calendar.csv"
    pd.DataFrame({
        "day": MONDAYS, "is_working_day": [1] * 4,
    }).to_csv(base, index=False)
    tpl = tmp_path / "templates.csv"
    pd.DataFrame([{
        "weekday_name": "MONDAY", "franja": "MATI", "slot_id": "A",
        "presentiality": "PRESENCIAL", "work_mode": "NORMAL",
        "required_staff": 1, "is_active": 1, "doubled": 0, "linked_to": "",
        "week_interval": week_interval, "week_offset": week_offset,
    }]).to_csv(tpl, index=False)
    out = tmp_path / "calendar_slots.csv"
    return base, tpl, out


class TestWeeklyAlternation:
    def _days(self, tmp_path, interval, offset):
        base, tpl, out = _write_inputs(tmp_path, interval, offset)
        overrides = tmp_path / "overrides.csv"
        overrides.write_text(
            "day,franja,slot_id,presentiality,work_mode,action,required_staff,notes\n",
            encoding="utf-8",
        )
        build_weekday_calendar_from_templates(
            str(base), str(tpl), str(overrides), str(out),
            slot_catalog_csv=None, professionals_csv=None,
        )
        cal = pd.read_csv(out)
        return sorted(cal["day"].unique())

    def test_every_week_default(self, tmp_path):
        assert self._days(tmp_path, 1, 0) == MONDAYS

    def test_alternate_weeks(self, tmp_path):
        # Setmanes ISO parells (2 i 4): 5 i 19 de gener.
        assert self._days(tmp_path, 2, 0) == ["2026-01-05", "2026-01-19"]
        # Setmanes ISO senars (3 i 5): 12 i 26 de gener.
        assert self._days(tmp_path, 2, 1) == ["2026-01-12", "2026-01-26"]

    def test_one_in_three(self, tmp_path):
        # ISO % 3 == 0 → setmana 3 → 12 de gener.
        assert self._days(tmp_path, 3, 0) == ["2026-01-12"]


def _month_cal():
    rows = []
    for d in MONDAYS:
        rows.append({
            "day": d, "franja": "MATI", "slot_id": "RODA_X",
            "presentiality": "PRESENCIAL", "work_mode": "NORMAL",
        })
    return pd.DataFrame(rows)


def _profs():
    return pd.DataFrame({
        "professional_id": ["P1", "P2", "P3"],
        "fallback": [0, 0, 0],
    })


class TestWheel:
    def test_rotation_order_and_continuity(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "weekday").mkdir(parents=True)
        save_wheel(pd.DataFrame([{"slot_id": "RODA_X", "professionals": "P1;P2;P3"}]))
        _month_cal().to_csv("data/weekday/calendar_slots.csv", index=False)
        rows = expand_wheel_preassignments(_month_cal(), _profs())
        got = {r["day"]: r["professional_id"] for _, r in rows.iterrows()}
        # 4 dilluns, ordre P1, P2, P3, P1.
        assert got == {
            MONDAYS[0]: "P1", MONDAYS[1]: "P2",
            MONDAYS[2]: "P3", MONDAYS[3]: "P1",
        }
        assert set(rows["source"]) == {"wheel"}
        assert set(rows["fixed"]) == {1}

    def test_blocked_person_loses_turn(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "weekday").mkdir(parents=True)
        save_wheel(pd.DataFrame([{"slot_id": "RODA_X", "professionals": "P1;P2;P3"}]))
        _month_cal().to_csv("data/weekday/calendar_slots.csv", index=False)
        rows = expand_wheel_preassignments(
            _month_cal(), _profs(), full_blocked={("P2", MONDAYS[1])},
        )
        got = {r["day"]: r["professional_id"] for _, r in rows.iterrows()}
        # El segon dilluns tocava P2 (absent) → passa a P3; la resta segueix
        # l'ancoratge per ocurrència (P3 al tercer, P1 al quart).
        assert got[MONDAYS[1]] == "P3"
        assert got[MONDAYS[2]] == "P3"
        assert got[MONDAYS[3]] == "P1"

    def test_empty_participants_uses_all_regulars(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "weekday").mkdir(parents=True)
        save_wheel(pd.DataFrame([{"slot_id": "RODA_X", "professionals": ""}]))
        _month_cal().to_csv("data/weekday/calendar_slots.csv", index=False)
        rows = expand_wheel_preassignments(_month_cal(), _profs())
        assert len(rows) == 4
        assert set(rows["professional_id"]) <= {"P1", "P2", "P3"}

    def test_wheel_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "weekday").mkdir(parents=True)
        save_wheel(pd.DataFrame([{"slot_id": "a", "professionals": "P1;P2"}]))
        w = load_wheel()
        assert w.iloc[0]["slot_id"] == "A"
        assert w.iloc[0]["professionals"] == "P1;P2"


class TestUiRoundtripPreservesAlternation:
    def test_save_and_read_table_keep_interval(self, tmp_path):
        """Regressio auditoria: el desat de la UI (save_weekly_slot_templates)
        i la carrega (read_table + WEEKDAY_TEMPLATE_COLUMNS) han de conservar
        week_interval/week_offset — abans es perdien en silenci."""
        from src.services.input_tables import save_weekly_slot_templates
        from src.services.planner_inputs import WEEKDAY_TEMPLATE_COLUMNS
        from src.services.slot_templates import add_work_slot_template
        from src.services.table_io import read_table

        empty = pd.DataFrame(columns=WEEKDAY_TEMPLATE_COLUMNS)
        df = add_work_slot_template(
            empty, "MONDAY", "MATI", "A", "PRESENCIAL", "NORMAL",
            week_interval=2, week_offset=1,
        )
        p = tmp_path / "tpl.csv"
        save_weekly_slot_templates(df, p)
        back = read_table(p, WEEKDAY_TEMPLATE_COLUMNS)
        assert int(back.iloc[0]["week_interval"]) == 2
        assert int(back.iloc[0]["week_offset"]) == 1
