def test_catalog_advertises_flood_profile(client):
    catalog = client.get("/api/catalog").get_json()
    assert "flood" in catalog["samples"]


def test_reaches_endpoint_lists_conclusions(client):
    response = client.get("/api/reaches?profile=flood")
    assert response.status_code == 200
    data = response.get_json()
    assert data["profile"] == "flood"
    assert {item["reach_id"] for item in data["registry"]} == {"R1", "R2", "R3", "R4"}
    conclusions = {item["reach_id"]: item["conclusion"] for item in data["reaches"]}
    assert conclusions == {"R1": "INCREASE", "R2": "REVIEW", "R3": "REVIEW", "R4": "DECREASE"}
    assert data["reach_summary"] == {"INCREASE": 1, "DECREASE": 1, "REVIEW": 2}


def test_reaches_endpoint_defaults_to_flood(client):
    assert client.get("/api/reaches").get_json()["profile"] == "flood"


def test_reaches_endpoint_rejects_unknown_profile(client):
    response = client.get("/api/reaches?profile=nope")
    assert response.status_code == 400
    assert response.get_json()["code"] == "SAMPLE_UNKNOWN"


def test_flood_run_is_blocked_from_approval(client):
    run = client.post("/api/runs", json={"profile": "flood"}).get_json()
    response = client.post(f"/api/runs/{run['run_id']}/review",
                           json={"decision": "APPROVED", "comment": "尝试签发", "expected_revision": 0})
    assert response.status_code == 409
    assert response.get_json()["code"] == "GATE_BLOCKED"


def test_flood_run_can_be_held(client):
    run = client.post("/api/runs", json={"profile": "flood"}).get_json()
    response = client.post(f"/api/runs/{run['run_id']}/review",
                           json={"decision": "HELD", "comment": "河段待核", "expected_revision": 0})
    assert response.status_code == 200
    assert response.get_json()["status"] == "HELD"


def test_same_retry_does_not_create_new_evaluation(client):
    first = client.post("/api/runs", json={"profile": "flood"}).get_json()
    second = client.post("/api/runs", json={"profile": "flood"}).get_json()
    # 同次签发重试不新增评估：批次与河段结论完全一致
    assert first["run_id"] == second["run_id"]
    assert first["reaches"] == second["reaches"]
    assert first["reach_summary"] == second["reach_summary"]


def test_flood_evidence_is_blocked_while_held(client):
    run = client.post("/api/runs", json={"profile": "flood"}).get_json()
    client.post(f"/api/runs/{run['run_id']}/review",
                json={"decision": "HELD", "comment": "待核", "expected_revision": 0})
    response = client.get(f"/api/runs/{run['run_id']}/evidence")
    assert response.status_code == 409


def test_flood_example_is_downloadable(client):
    response = client.get("/api/examples/flood")
    assert response.status_code == 200
    assert b"R1UP" in response.data


def test_reaches_visible_on_run_payload(client):
    run = client.post("/api/runs", json={"profile": "flood"}).get_json()
    r2 = next(item for item in run["reaches"] if item["reach_id"] == "R2")
    assert r2["signable"] is False
    assert r2["reason"] == "DIRECTION_AMBIGUOUS"
    # 配对明细可在工作台对账
    pair = r2["pairs"][0]
    assert set(pair) >= {"upstream_sample_id", "downstream_sample_id", "upstream_load", "downstream_load"}
