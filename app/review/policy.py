def approval_allowed(payload):
    if int(payload["summary"].get("REJECT", 0)) != 0:
        return False
    # 汛期河段评估存在待核结论（方向不一致或无有效配对）时不能签发
    reach_summary = payload.get("reach_summary") or {}
    if int(reach_summary.get("REVIEW", 0)) != 0:
        return False
    return True
