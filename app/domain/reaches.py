"""汛期河段净增负荷评估。

规则要点：
- 每份上游/下游水样最多参与一次配对；
- 配对的下游采样时间与上游采样时间之差必须落在河段登记的传播时差窗口内；
- 在所有可行配对中取配对数最多的方案（最大基数匹配）；
- 负荷 = 浓度 × 流量（未检出由整理层按半个检出限代入，单位已统一）；
- 河段净增负荷 = 所有配对下游负荷之和 − 上游负荷之和；
- 若不同的最大配对方案可能得到不同增减方向，或不存在有效配对，则河段待核，
  只有全部最大配对方向一致时才可签发。

实现使用最小费用最大流：先求最大基数 K，再分别在“恰好 K 对”的约束下求
净增负荷的最小值与最大值，用二者符号是否一致判定方向稳健性。费用采用
Decimal 精确运算，最短增广路用 Bellman-Ford（允许反向负费用边）。
"""

from decimal import Decimal

from app.domain.helpers import D
from app.errors import DomainIssue
from app.intake.reader import read_records

REACH_COLUMNS = ["reach_id", "upstream_station", "downstream_station",
                 "lag_min_hours", "lag_max_hours"]

# 河段结论
INCREASE = "INCREASE"                        # 净增（方向一致为正，可签发）
DECREASE = "DECREASE"                        # 净减（方向一致为负，可签发）
REVIEW = "REVIEW"                            # 待核

# 待核/阻断原因码
NO_VALID_PAIR = "NO_VALID_PAIR"              # 没有有效配对
DIRECTION_AMBIGUOUS = "DIRECTION_AMBIGUOUS"  # 最大配对间方向不一致


def load_registry(path):
    """读取并校验河段登记表。"""
    try:
        raw = open(path, "rb").read()
    except OSError:
        raise DomainIssue("REACH_REGISTRY_MISSING")
    parsed = read_records(raw, REACH_COLUMNS, 5000)
    reaches, seen = [], set()
    for record in parsed["records"]:
        if record["blank"] or record["repeated"]:
            continue
        if len(record["cells"]) != len(REACH_COLUMNS):
            raise DomainIssue("REACH_BAD_ROW", detail="河段登记表列数不一致")
        row = dict(zip(REACH_COLUMNS, record["cells"]))
        reach_id = row["reach_id"]
        if not reach_id:
            raise DomainIssue("REACH_BAD_ROW", detail="河段编号为空")
        if reach_id in seen:
            raise DomainIssue("REACH_DUPLICATE", detail=reach_id)
        if not row["upstream_station"] or not row["downstream_station"]:
            raise DomainIssue("REACH_BAD_ROW", detail=reach_id)
        if row["upstream_station"] == row["downstream_station"]:
            raise DomainIssue("REACH_BAD_ROW", detail=reach_id)
        try:
            lag_min = D(row["lag_min_hours"], "REACH_BAD_LAG")
            lag_max = D(row["lag_max_hours"], "REACH_BAD_LAG")
        except ValueError:
            raise DomainIssue("REACH_BAD_LAG", detail=reach_id)
        if lag_min < 0 or lag_max < 0 or lag_min > lag_max:
            raise DomainIssue("REACH_BAD_LAG", detail=reach_id)
        seen.add(reach_id)
        reaches.append({
            "reach_id": reach_id,
            "upstream_station": row["upstream_station"],
            "downstream_station": row["downstream_station"],
            "lag_min_hours": lag_min,
            "lag_max_hours": lag_max,
        })
    if not reaches:
        raise DomainIssue("REACH_REGISTRY_EMPTY")
    return reaches


def _load(item):
    return Decimal(item["concentration"]) * Decimal(item["flow_m3s"])


def _admissible(up, down, reach):
    lag_hours = Decimal(str((down["sample_at"] - up["sample_at"]).total_seconds())) / Decimal("3600")
    return reach["lag_min_hours"] <= lag_hours <= reach["lag_max_hours"]


def _add_edge(edges, tail, head, capacity, cost):
    """加入一条正向边及其反向边，返回正向边下标。"""
    idx = len(edges)
    edges.append({"tail": tail, "head": head, "residual": capacity, "cost": cost, "reverse": idx + 1})
    edges.append({"tail": head, "head": tail, "residual": 0, "cost": -cost, "reverse": idx})
    return idx


def _build_network(ups, downs, admissible, cost_of):
    """构造 源点→上游→下游→汇点 的容量网络。

    返回 (节点数, 边, 源点, 汇点, 配对边[(边下标, u, v)])。
    """
    source, sink = 0, len(ups) + len(downs) + 1
    edges, pair_edges = [], []
    zero = Decimal("0")
    for u in range(len(ups)):
        _add_edge(edges, source, u + 1, 1, zero)
    for u, up in enumerate(ups):
        for v, down in enumerate(downs):
            if admissible[u][v]:
                idx = _add_edge(edges, u + 1, len(ups) + 1 + v, 1, cost_of(up, down))
                pair_edges.append((idx, u, v))
    for v in range(len(downs)):
        _add_edge(edges, len(ups) + 1 + v, sink, 1, zero)
    return sink + 1, edges, source, sink, pair_edges


def _shortest_path(edges, node_count, source, sink):
    """Bellman-Ford 求最短增广路（允许反向负费用边），返回前驱边下标序列或 None。"""
    distance = [None] * node_count
    previous = [None] * node_count
    distance[source] = Decimal("0")
    for _ in range(node_count - 1):
        changed = False
        for idx, edge in enumerate(edges):
            if edge["residual"] <= 0 or distance[edge["tail"]] is None:
                continue
            candidate = distance[edge["tail"]] + edge["cost"]
            if distance[edge["head"]] is None or candidate < distance[edge["head"]]:
                distance[edge["head"]] = candidate
                previous[edge["head"]] = idx
                changed = True
        if not changed:
            break
    if distance[sink] is None:
        return None
    path, node = [], sink
    while node != source:
        idx = previous[node]
        if idx is None:
            return None
        path.append(idx)
        node = edges[idx]["tail"]
    return path


def _augment(edges, path):
    for idx in path:
        edges[idx]["residual"] -= 1
        edges[edges[idx]["reverse"]]["residual"] += 1


def _min_cost_flow(ups, downs, admissible, cost_of, required_flow):
    """在恰好 required_flow 对的约束下返回 (最小总费用, 选中的 (u, v) 列表)。"""
    node_count, edges, source, sink, pair_edges = _build_network(ups, downs, admissible, cost_of)
    total = Decimal("0")
    for _ in range(required_flow):
        path = _shortest_path(edges, node_count, source, sink)
        if path is None:
            raise DomainIssue("REACH_MATCHING_FAILED")
        for idx in path:
            total += edges[idx]["cost"]
        _augment(edges, path)
    chosen = sorted((u, v) for idx, u, v in pair_edges if edges[idx]["residual"] == 0)
    return total, chosen


def _maximum_cardinality(ups, downs, admissible):
    """用零费用最小费用流求最大配对数。"""
    zero_cost = lambda up, down: Decimal("0")  # noqa: E731
    node_count, edges, source, sink, _ = _build_network(ups, downs, admissible, zero_cost)
    flow = 0
    while flow < min(len(ups), len(downs)):
        path = _shortest_path(edges, node_count, source, sink)
        if path is None:
            break
        _augment(edges, path)
        flow += 1
    return flow


def assess_reach(reach, items):
    """评估单个河段，输出结论与对账明细。"""
    ups = sorted((item for item in items if item["station_id"] == reach["upstream_station"]),
                 key=lambda item: (item["sample_at"], item["sample_id"]))
    downs = sorted((item for item in items if item["station_id"] == reach["downstream_station"]),
                   key=lambda item: (item["sample_at"], item["sample_id"]))
    admissible = [[_admissible(up, down, reach) for down in downs] for up in ups]
    pair_count = _maximum_cardinality(ups, downs, admissible) if ups and downs else 0

    result = {
        "reach_id": reach["reach_id"],
        "upstream_station": reach["upstream_station"],
        "downstream_station": reach["downstream_station"],
        "lag_min_hours": reach["lag_min_hours"],
        "lag_max_hours": reach["lag_max_hours"],
        "upstream_samples": len(ups),
        "downstream_samples": len(downs),
        "pair_count": pair_count,
        "pairs": [],
        "net_load": None,
        "net_load_min": None,
        "net_load_max": None,
        "conclusion": REVIEW,
        "signable": False,
        "reason": NO_VALID_PAIR,
    }
    if pair_count == 0:
        return result

    def net_cost(up, down):
        return _load(down) - _load(up)

    net_min, min_pairs = _min_cost_flow(ups, downs, admissible, net_cost, pair_count)
    net_max, _ = _min_cost_flow(ups, downs, admissible,
                                lambda up, down: -net_cost(up, down), pair_count)
    net_max = -net_max

    upstream_load = downstream_load = Decimal("0")
    pairs = []
    for u, v in min_pairs:
        up, down = ups[u], downs[v]
        up_load, down_load = _load(up), _load(down)
        upstream_load += up_load
        downstream_load += down_load
        pairs.append({
            "upstream_sample_id": up["sample_id"],
            "downstream_sample_id": down["sample_id"],
            "upstream_at": up["sample_at"],
            "downstream_at": down["sample_at"],
            "upstream_load": up_load,
            "downstream_load": down_load,
        })
    net_load = downstream_load - upstream_load

    result.update({
        "pairs": pairs,
        "net_load": net_load,
        "net_load_min": net_min,
        "net_load_max": net_max,
    })
    if net_min > 0 and net_max > 0:
        result.update(conclusion=INCREASE, signable=True, reason="NET_INCREASE")
    elif net_min < 0 and net_max < 0:
        result.update(conclusion=DECREASE, signable=True, reason="NET_DECREASE")
    else:
        result.update(conclusion=REVIEW, signable=False, reason=DIRECTION_AMBIGUOUS)
    return result


def assess_reaches(registry, items):
    """评估全部登记河段；本批次没有任何相关水样的河段不参与结论。"""
    stations = {item["station_id"] for item in items}
    results = []
    for reach in registry:
        if reach["upstream_station"] not in stations and reach["downstream_station"] not in stations:
            continue
        results.append(assess_reach(reach, items))
    return results
