from decimal import Decimal

import pytest

from app.config import REACH_REGISTRY
from app.domain.prepare import prepare_rows
from app.domain.reaches import (DECREASE, INCREASE, REVIEW, DIRECTION_AMBIGUOUS,
                                NO_VALID_PAIR, assess_reach, assess_reaches,
                                load_registry)
from app.errors import DomainIssue
from app.intake.service import load

REGISTRY = load_registry(REACH_REGISTRY)


def flood_items():
    prepared, issues = prepare_rows(load("flood")["rows"])
    assert issues == []
    return prepared


def by_id(results, reach_id):
    return next(item for item in results if item["reach_id"] == reach_id)


def test_registry_is_registered():
    assert {item["reach_id"] for item in REGISTRY} == {"R1", "R2", "R3", "R4"}
    r1 = next(item for item in REGISTRY if item["reach_id"] == "R1")
    assert r1["upstream_station"] == "R1UP"
    assert r1["lag_min_hours"] == Decimal("2")
    assert r1["lag_max_hours"] == Decimal("6")


def test_r1_clear_increase_is_signable():
    r1 = by_id(assess_reaches(REGISTRY, flood_items()), "R1")
    assert r1["conclusion"] == INCREASE
    assert r1["signable"] is True
    assert r1["reason"] == "NET_INCREASE"
    # 最大配对数：3 个上游、2 个下游，最多 2 对
    assert r1["pair_count"] == 2
    assert r1["net_load_min"] > 0 and r1["net_load_max"] > 0
    assert r1["net_load_min"] <= r1["net_load"] <= r1["net_load_max"]


def test_each_sample_used_at_most_once():
    for result in assess_reaches(REGISTRY, flood_items()):
        upstream_used = [pair["upstream_sample_id"] for pair in result["pairs"]]
        downstream_used = [pair["downstream_sample_id"] for pair in result["pairs"]]
        assert len(upstream_used) == len(set(upstream_used))
        assert len(downstream_used) == len(set(downstream_used))


def test_r2_ambiguous_direction_is_held():
    r2 = by_id(assess_reaches(REGISTRY, flood_items()), "R2")
    assert r2["conclusion"] == REVIEW
    assert r2["signable"] is False
    assert r2["reason"] == DIRECTION_AMBIGUOUS
    # 两种最大配对分别给出 -4 与 +4
    assert r2["pair_count"] == 1
    assert r2["net_load_min"] == Decimal("-4")
    assert r2["net_load_max"] == Decimal("4")


def test_r3_without_valid_pair_is_held():
    r3 = by_id(assess_reaches(REGISTRY, flood_items()), "R3")
    assert r3["conclusion"] == REVIEW
    assert r3["signable"] is False
    assert r3["reason"] == NO_VALID_PAIR
    assert r3["pair_count"] == 0
    assert r3["pairs"] == []
    assert r3["net_load"] is None


def test_r4_clear_decrease_is_signable():
    r4 = by_id(assess_reaches(REGISTRY, flood_items()), "R4")
    assert r4["conclusion"] == DECREASE
    assert r4["signable"] is True
    assert r4["reason"] == "NET_DECREASE"
    assert r4["net_load"] == Decimal("-5")
    assert r4["net_load_min"] == r4["net_load_max"] == Decimal("-5")


def test_net_load_is_downstream_minus_upstream():
    r4 = by_id(assess_reaches(REGISTRY, flood_items()), "R4")
    upstream_sum = sum((pair["upstream_load"] for pair in r4["pairs"]), Decimal("0"))
    downstream_sum = sum((pair["downstream_load"] for pair in r4["pairs"]), Decimal("0"))
    assert r4["net_load"] == downstream_sum - upstream_sum


def test_nd_sample_keeps_half_detection_limit():
    # F012 为 ND：浓度 = 0.2 / 2 = 0.1 mg/L，流量 2 → 负荷 0.2
    items = flood_items()
    f012 = next(item for item in items if item["sample_id"] == "F012")
    assert f012["concentration"] == Decimal("0.1")
    assert f012["concentration"] * f012["flow_m3s"] == Decimal("0.2")


def test_unit_conversion_feeds_load_in_mg_per_l():
    # F005 为 2000 ug/L → 2 mg/L，流量 2 → 负荷 4
    r1 = by_id(assess_reaches(REGISTRY, flood_items()), "R1")
    f005 = next(pair for pair in r1["pairs"] if pair["downstream_sample_id"] == "F005")
    assert f005["downstream_load"] == Decimal("4")


def test_pairs_stay_inside_lag_window():
    for result in assess_reaches(REGISTRY, flood_items()):
        reach = next(item for item in REGISTRY if item["reach_id"] == result["reach_id"])
        for pair in result["pairs"]:
            lag = (pair["downstream_at"] - pair["upstream_at"]).total_seconds() / 3600
            assert float(reach["lag_min_hours"]) <= lag <= float(reach["lag_max_hours"])


def _sample(sample_id, station, stamp, concentration="1", flow="1", qualifier="", unit="mg/L", limit="0.1"):
    return {"sample_id": sample_id, "station_id": station, "sample_at": stamp,
            "concentration": concentration, "flow_m3s": flow, "detection_limit": limit,
            "qualifier": qualifier, "unit": unit}


def _reach(reach_id="RX", lag_min="1", lag_max="3", up="UP", down="DN"):
    return {"reach_id": reach_id, "upstream_station": up, "downstream_station": down,
            "lag_min_hours": Decimal(lag_min), "lag_max_hours": Decimal(lag_max)}


def test_lag_boundaries_are_inclusive():
    reach = _reach(lag_min="2", lag_max="4")
    items, _ = prepare_rows([
        _sample("U1", "UP", "2026-08-01 08:00"),
        _sample("D1", "DN", "2026-08-01 10:00"),   # 恰好 2 小时，下界
        _sample("D2", "DN", "2026-08-01 12:00"),   # 恰好 4 小时，上界
        _sample("D3", "DN", "2026-08-01 13:00"),   # 5 小时，窗口外
    ])
    result = assess_reach(reach, items)
    assert result["pair_count"] == 1
    assert {pair["downstream_sample_id"] for pair in result["pairs"]} <= {"D1", "D2"}


def test_zero_lag_window_requires_same_timestamp():
    reach = _reach(lag_min="0", lag_max="0")
    items, _ = prepare_rows([
        _sample("U1", "UP", "2026-08-01 08:00"),
        _sample("D1", "DN", "2026-08-01 08:00"),
        _sample("D2", "DN", "2026-08-01 08:01"),
    ])
    result = assess_reach(reach, items)
    assert result["pair_count"] == 1
    assert result["pairs"][0]["downstream_sample_id"] == "D1"


def test_maximum_cardinality_beats_greedy_choice():
    # 贪心若先把 U1 配给 D1 会只剩 1 对；最优应为 2 对
    reach = _reach(lag_min="0", lag_max="10")
    items, _ = prepare_rows([
        _sample("U1", "UP", "2026-08-01 08:00"),
        _sample("U2", "UP", "2026-08-01 08:00"),
        _sample("D1", "DN", "2026-08-01 09:00"),
        _sample("D2", "DN", "2026-08-01 10:00", concentration="2"),
    ])
    # 手动收窄边：通过时差让 U1 只能配 D1（U1 08:00，窗口 1h），U2 可配两者
    reach["lag_max_hours"] = Decimal("2")
    result = assess_reach(reach, items)
    assert result["pair_count"] == 2


def test_zero_net_load_is_not_signable():
    # 两种最大配对一正一负且可恰好为 0 时方向不一致 → 待核
    reach = _reach(lag_min="0", lag_max="10")
    items, _ = prepare_rows([
        _sample("U1", "UP", "2026-08-01 08:00", concentration="5"),
        _sample("D1", "DN", "2026-08-01 09:00", concentration="1"),
        _sample("D2", "DN", "2026-08-01 09:00", concentration="9"),
    ])
    result = assess_reach(reach, items)
    assert result["pair_count"] == 1
    assert result["conclusion"] == REVIEW
    assert result["net_load_min"] < 0 < result["net_load_max"]


def test_reach_without_any_samples_is_skipped():
    reach = _reach(reach_id="EMPTY", up="GHOST-UP", down="GHOST-DN")
    assert assess_reaches([reach], flood_items()) == []


def test_bad_registry_rows_are_rejected(tmp_path):
    path = tmp_path / "bad_reaches.csv"
    header = ",".join(["reach_id", "upstream_station", "downstream_station",
                       "lag_min_hours", "lag_max_hours"])

    def write(body):
        path.write_text(header + "\n" + body + "\n", encoding="utf-8")
        with pytest.raises(DomainIssue):
            load_registry(path)

    write("RX,UP,DN,3,2")          # 下界大于上界
    write("RX,UP,UP,1,3")          # 上下游同站
    write("RX,UP,DN,x,3")          # 时差不是数字
    write(",UP,DN,1,3")            # 河段编号为空


def test_duplicate_reach_id_is_rejected(tmp_path):
    path = tmp_path / "dup_reaches.csv"
    header = ",".join(["reach_id", "upstream_station", "downstream_station",
                       "lag_min_hours", "lag_max_hours"])
    path.write_text(header + "\nRX,UP1,DN1,1,3\nRX,UP2,DN2,1,3\n", encoding="utf-8")
    with pytest.raises(DomainIssue) as exc:
        load_registry(path)
    assert exc.value.code == "REACH_DUPLICATE"


def test_missing_registry_is_rejected(tmp_path):
    with pytest.raises(DomainIssue) as exc:
        load_registry(tmp_path / "nope.csv")
    assert exc.value.code == "REACH_REGISTRY_MISSING"


def test_assessment_is_deterministic():
    first = assess_reaches(REGISTRY, flood_items())
    second = assess_reaches(REGISTRY, list(reversed(flood_items())))
    assert [(r["reach_id"], r["conclusion"], r["net_load"], r["pairs"]) for r in first] == \
           [(r["reach_id"], r["conclusion"], r["net_load"], r["pairs"]) for r in second]
