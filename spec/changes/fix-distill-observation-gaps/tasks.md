## Deliverables

```yaml
- path: core/dashboard/data/command_center.py
  kind: modify
- path: core/knowledge.py
  kind: modify
- path: tests/test_command_center_aggregation.py
  kind: modify
- path: tests/test_knowledge_distill_run_artifacts.py
  kind: modify
```

## 1. 聚合剔除豁免

- [ ] 1.1 `core/dashboard/data/command_center.py` `aggregate_org`：剔除条件内联豁免——先取 raw agent_type，`archived_names and raw_lane != "knowledge-distiller" and spec in archived_names` 才剔除；后续 lane 归一复用同一 raw_lane 变量，LANE_ALIASES 归一位置与「其他」分区收集逻辑零变化
- [ ] 1.2 `tests/test_command_center_aggregation.py`：已归档 SPEC 名（归档清单命中，push 触发时代原始名形态 run_id）的 done 蒸馏产物→运营线卡 runs=1/成功率含分母；带日期前缀归档目录名形态（归档触发时代 run_id，如 `knowledge-distiller-2026-11-02-<spec>-<ts>`）的 done 蒸馏产物→同样计数（豁免形态无关性锚点，与 tests/test_run_spec_prefixed_attribution.py::test_aggregate_org_archive_filter_not_hit 同口径互证）；已归档 SPEC 名的 impl- 产物→仍被剔除（非蒸馏 lane 不回归）；LANE_ALIASES 归一 lane（如 dispute-judge）的归档名 run 剔除行为不变

## 2. 批心跳保活

- [ ] 2.1 `core/knowledge.py` `_run_batch`：新增心跳线程（daemon=True、interval=900s、`type: "heartbeat"` 非终态行、Event.wait 可中断、全异常吞掉 fail-open）；批 finally 中先 event.set()+join(timeout=10) 再写终态行（保证终态行为末行）；所有 return/异常路径线程收敛；产物创建 fail-open 失败（run_file=None）时不启动心跳线程；同步更新批产物注释「单 worker 线程逐批消费，单写者无交错」为双写者口径（心跳线程为第二写者，append_run_line 的 O_APPEND 原子追加契约覆盖并发）
- [ ] 2.2 `tests/test_knowledge_distill_run_artifacts.py`：spawn 等待超 stale 阈值的批（替身 spawn 阻塞+时间注入）→产物出现心跳行、读侧判 running 非 stale、retention 可归档判定为 False；批收尾终态行成为末行（classify_run 判 done/error 正确）；产物目录不可写→心跳静默放弃、批行为与无心跳一致；批异常路径线程不留存活

## 3. 回归

- [ ] 3.1 `tests/test_command_center_aggregation.py` 全绿 + 蒸馏族（test_knowledge*.py）全绿 + `python3 -m compileall core/` 通过
- [ ] 3.2 端到端对账：以生产真实形态伪造「归档清单命中 SPEC 名」的蒸馏产物（含心跳行形态）走 aggregate_org 全窗口径，卡片三格与 last_activity 正确（闭环本 SPEC 的两个盲区）
