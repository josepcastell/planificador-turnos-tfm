"""Tests del parser del solver_log.txt."""

from src.services.solver_log_parser import (
    collect_target_violations,
    parse_solver_log,
)


_SAMPLE_LOG = """
============================================================
SOLVER tier-by-tier breakdown
============================================================

[Tram 1: presencial]  status=OPTIMAL  obj=6000000.0
  · total_eligibility_penalty = 0  (pes 10,000,000)
  · total_no_pres_weekday_violation = 0  (pes 6,000,000)
  · total_weekly_presential_shortfall = 2  (pes 3,000,000)
  · total_weekly_presential_overage = 0  (pes 3,000,000)

[Tram 2: no_presencial]  status=FEASIBLE  obj=2500000.0
  · total_weekly_np_ord_shortfall = 0  (pes 500,000)
  · total_weekly_np_ord_overage = 5  (pes 500,000)
  · total_peonada_shortfall = 0  (pes 200,000)
"""


def test_parse_two_tiers(tmp_path):
    p = tmp_path / "log.txt"
    p.write_text(_SAMPLE_LOG, encoding="utf-8")
    result = parse_solver_log(p)
    assert len(result["tiers"]) == 2
    t1 = result["tiers"][0]
    assert t1["name"] == "presencial"
    assert t1["status"] == "OPTIMAL"
    assert t1["obj"] == 6000000.0
    assert t1["terms"]["total_weekly_presential_shortfall"] == 2
    assert t1["terms"]["total_weekly_presential_overage"] == 0
    t2 = result["tiers"][1]
    assert t2["name"] == "no_presencial"
    assert t2["status"] == "FEASIBLE"
    assert t2["terms"]["total_weekly_np_ord_overage"] == 5


def test_collect_target_violations(tmp_path):
    p = tmp_path / "log.txt"
    p.write_text(_SAMPLE_LOG, encoding="utf-8")
    summary = parse_solver_log(p)
    v = collect_target_violations(summary)
    assert v == {
        "pres_shortfall": 2,
        "pres_overage": 0,
        "np_shortfall": 0,
        "np_overage": 5,
    }


def test_no_log_file(tmp_path):
    p = tmp_path / "nonexistent.txt"
    result = parse_solver_log(p)
    assert result == {"tiers": []}
    v = collect_target_violations(result)
    assert v == {
        "pres_shortfall": 0, "pres_overage": 0,
        "np_shortfall": 0, "np_overage": 0,
    }


def test_empty_log(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("", encoding="utf-8")
    assert parse_solver_log(p) == {"tiers": []}


def test_obj_n_a(tmp_path):
    p = tmp_path / "log.txt"
    p.write_text(
        "[Tram 1: presencial]  status=INFEASIBLE  obj=N/A\n",
        encoding="utf-8",
    )
    result = parse_solver_log(p)
    assert result["tiers"][0]["obj"] is None
    assert result["tiers"][0]["status"] == "INFEASIBLE"
