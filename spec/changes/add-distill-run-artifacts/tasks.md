## Deliverables

```yaml
- path: core/knowledge.py
  kind: modify
- path: core/agent_runner/run_files.py
  kind: modify
- path: core/dashboard/data/command_center.py
  kind: modify
- path: core/dashboard/static/src/pages/command-center/shared.ts
  kind: modify
- path: core/dashboard/static/src/pages/command-center/OrgGrid.tsx
  kind: modify
- path: tests/test_knowledge_distill_run_artifacts.py
  kind: new
- path: tests/test_knowledge.py
  kind: modify
- path: tests/test_command_center_aggregation.py
  kind: modify
- path: tests/test_run_spec_prefixed_attribution.py
  kind: modify
```

## 1. 写侧：蒸馏批次 run 产物

- [x] 1.1 `core/knowledge.py` `_run_batch` 增加产物包装：批开始（首个 spawn 前）在 `.fenix/runs/` 创建 `knowledge-distiller-<首归档名>-<int(time.time())>.jsonl` 并写入带 `timestamp` 与 `archived` 全名单的开始事件行；`try/finally` 收口——`finally` 按 `result["ok"]` 写终态行（ok→`type=result`，否则 `type=error` 附 reason 摘要），四个 return 路径统一覆盖；文件创建与全部行追加均 try/except OSError 吞掉（fail-open，与 runner.py `run_file.touch` 防御口径一致）；行追加复用 `run_files.append_run_line` / `append_run_error` 既有原语（O_APPEND 单行原子性与 `\udXXX` UTF-8 预清洗防御同口径），MUST NOT 手写 `open("a")` 文本追加
- [x] 1.2 `tests/test_knowledge_distill_run_artifacts.py`（new）：批成功→产物末行 `type=result`；spawn 失败 give_up→末行 `type=error` 带 reason；多修正轮→同产物追加行数递增且终态判定不变；产物目录不可写（OSError 注入）→蒸馏 result/台账行为与无产物形态完全一致且无异常外泄；一批多归档→run_id 中段为首归档名、开始行 `archived` 含全名单

## 2. 前缀真源与消费面边界

- [x] 2.1 `core/agent_runner/run_files.py` `RUN_ID_AGENT_PREFIXES` 收录 `("knowledge-distiller-", "knowledge-distiller")`（位置避开子串前缀歧义，附消费方核对注记：admin_monitor 不收录同 evo-/review- 口径）
- [x] 2.2 `tests/test_run_spec_prefixed_attribution.py`：`infer_run_agent_type("knowledge-distiller-<名>-<ts>")` 归属 knowledge-distiller；`run_spec_part` 剥前缀+时间戳后段=归档名；`admin_monitor._RUN_PREFIXES` 不含该前缀（失败不还原活跃 spec 断言）；pm_engine 归属判定对 `knowledge-distiller-<归档名>-<ts>` 不命中任何活跃 spec（伪造活跃 spec 与蒸馏 run_id 同名单侧）；aggregate_org 归档剔除不命中——伪造 STATE.archive.md 清单含首归档 SPEC 原始名 + done 终态蒸馏产物，断言运营线蒸馏卡 runs≥1（锁定「run spec 段=带日期前缀归档目录名 vs 清单键=原始名」的形态错位耦合：run_id 中段若改用原始 SPEC 名，归档剔除将静默吞掉全部蒸馏 run，此测试即红）

## 3. 指挥中心花名册收编

- [x] 3.1 `core/dashboard/data/command_center.py` ROSTER 运营线追加 `"knowledge-distiller"`（附 2026-11-01 收编注记，注明数据源=本轮新增蒸馏 run 产物）
- [x] 3.2 `core/dashboard/static/src/pages/command-center/shared.ts` LANE_LABELS 补 `'knowledge-distiller': '知识蒸馏'`；`OrgGrid.tsx` LANE_ICONS 补 `knowledge-distiller: BookOutlined`（花名册内车道不落 FileUnknownOutlined 兜底）
- [x] 3.3 `tests/test_command_center_aggregation.py`：伪造 done 终态 knowledge-distiller 产物→`aggregate_org` 运营线出卡（lane/zone/runs/success_rate 正确）；零 run→编制内出空卡（runs=0、working=false）；无 usage 产物→成本/tokens 按 None 透传不伪显 0；「今日/7 日/全量」三窗口口径一致

## 4. 回归与端到端验证

- [x] 4.1 既有套件回归：`tests/test_knowledge.py` 补批生命周期产物断言（如有批级测试夹具）并全量跑蒸馏族（test_knowledge*.py）零回归；`test_command_center_aggregation.py` 全绿
- [x] 4.2 端到端冒烟：本地构造一条 done 终态蒸馏产物落 `.fenix/runs/`，调 `aggregate_org`（today 窗口）断言运营线「知识蒸馏」卡出现且三格（runs/成功率/成本缺失）形态正确；`python3 -m compileall core/` 通过
