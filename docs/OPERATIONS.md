# 运行说明

## 启动

```bash
docker compose up --build
```

## 测试

```bash
docker compose exec -T app pytest -q
```

## 样例

- `dirty`：包含编码、列数、空值或冲突重复，适合检查隔离区。
- `clean`：可通过当前规则并完成签发。
- `flood`：汛期河段净增负荷评估，覆盖净增（R1）、方向不一致待核（R2）、无有效配对待核（R3）与净减（R4）。河段与传播时差登记在 `sample_data/reaches.csv`，结论见工作台「汛期河段净增负荷」面板或 `GET /api/reaches`。

## 重置

```bash
docker compose down -v
docker compose up --build
```

历史批次保存在 SQLite 卷中。重置会清除本地批次与签发记录。
