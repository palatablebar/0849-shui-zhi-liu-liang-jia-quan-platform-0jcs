from app.service import pipeline


def test_flood_profile_runs_full_pipeline():
    payload = pipeline("flood")
    assert payload["profile"] == "flood"
    assert payload["counts"]["accepted"] == 14
    assert payload["counts"]["computed"] == 8


def test_pipeline_carries_reach_conclusions():
    payload = pipeline("flood")
    conclusions = {item["reach_id"]: item["conclusion"] for item in payload["reaches"]}
    assert conclusions == {"R1": "INCREASE", "R2": "REVIEW", "R3": "REVIEW", "R4": "DECREASE"}
    assert payload["reach_summary"] == {"INCREASE": 1, "DECREASE": 1, "REVIEW": 2}


def test_ledger_flags_pending_reaches():
    payload = pipeline("flood")
    check = next(item for item in payload["ledger"]["checks"] if item["id"] == "reach_direction")
    assert check["ok"] is False
    assert set(payload["ledger"]["reach_pending"]) == {"R2", "R3"}


def test_clean_profile_has_no_pending_reach():
    payload = pipeline("clean")
    # clean 样例不含任何登记河段的站点，河段不参与评估
    assert payload["reaches"] == []
    assert payload["reach_summary"] == {"INCREASE": 0, "DECREASE": 0, "REVIEW": 0}
    assert payload["ledger"]["reach_pending"] == []


def test_reaches_are_omitted_before_reconcile_stage():
    payload = pipeline("flood", upto="加权评价")
    assert payload["reaches"] == []


def test_flood_run_key_is_stable():
    assert pipeline("flood")["run_key"] == pipeline("flood")["run_key"]
