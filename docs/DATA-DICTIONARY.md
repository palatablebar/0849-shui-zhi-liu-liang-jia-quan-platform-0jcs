# 字段定义

| 字段 | 类型 | 说明 |
|---|---|---|
| `sample_id` | text | 主键 |
| `station_id` | text | 业务字段 |
| `sample_at` | datetime | 业务字段 |
| `concentration` | decimal | 业务字段 |
| `flow_m3s` | decimal | 业务字段 |
| `detection_limit` | decimal_optional | 业务字段 |
| `qualifier` | text | 业务字段 |
| `unit` | text | 业务字段 |

空字符串、`-`、`NA`、`null` 和 `未提供` 按空值处理。金额字段在整理层转为整数分或整数最小单位；日期按 ISO 日期解析；带时间的字段按本地时间解析。标识字段保持为文本，前导零不会被去除。

## 河段登记 `sample_data/reaches.csv`

| 字段 | 类型 | 说明 |
|---|---|---|
| `reach_id` | text | 河段编号，登记内唯一 |
| `upstream_station` | text | 上游站点标识，对应水样 `station_id` |
| `downstream_station` | text | 下游站点标识，对应水样 `station_id` |
| `lag_min_hours` | decimal | 允许的最小传播时差（小时，含边界） |
| `lag_max_hours` | decimal | 允许的最大传播时差（小时，含边界） |

下游与上游采样时间之差落在 `[lag_min_hours, lag_max_hours]` 内才允许配对；时差窗口非法（负值或下界大于上界）、编号重复或上下游同站的登记行会被拒收。

## 河段结论

| 结论 | 原因码 | 含义 |
|---|---|---|
| `INCREASE` | `NET_INCREASE` | 全部最大配对净增负荷均为正，可签发 |
| `DECREASE` | `NET_DECREASE` | 全部最大配对净增负荷均为负，可签发 |
| `REVIEW` | `DIRECTION_AMBIGUOUS` | 最大配对间增减方向不一致，待核 |
| `REVIEW` | `NO_VALID_PAIR` | 时差窗口内没有有效配对，待核 |
