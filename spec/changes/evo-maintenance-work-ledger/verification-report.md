# 验证报告：evo-maintenance-work-ledger

> ⚠️ 本报告由框架于 2026-10-07T20:01:10Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-07T20:01:09.487212+00:00+run-result@mtime1791403269518307446

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.11M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| mwl-ledger-append-creates-and-roundtrip | R1 正向：append_maintenance_entry 在台账文件不存在时创建文件（含 .fenix 目录），条目字段 ts/scope/actor/evidence/note/run_id 齐全（run_id 缺省写 None、ts 由写侧生成），list_maintenance_entries 逐字还原（出处 core/maintenance_ledger.py:34-52） | pass | 0/7 | - |
| mwl-ledger-empty-states | R1 空状态：台账文件不存在时 list_maintenance_entries 与 list_entries_for_run 返回空列表不抛异常；空文件同样返回空列表（出处 core/maintenance_ledger.py:55-64） | pass | 0/4 | - |
| mwl-ledger-bad-lines-tolerated | R1 异常容错：坏行（非法 JSON、JSON 数组顶层、裸字符串、空行）被读取侧跳过不中断全量读取，好条目按落账顺序完整返回（出处 core/maintenance_ledger.py:55-76） | pass | 0/4 | - |
| mwl-ledger-append-order-and-preserve | R1 交互/回归：连续多次追加不覆盖既有条目，台账文件逐行累积，读取保持落账顺序（旧→新）（出处 core/maintenance_ledger.py:34-76） | pass | 0/4 | - |
| mwl-ledger-oversized-line-atomic | R1 边界：单行超 _ATOMIC_APPEND_LINE_BYTES=4096 时走二进制单次 os.write 原子路径（沿用 run_files 原子追加约定，先例 item 29df176ff441），整行落盘仍可完整读回（出处 core/maintenance_ledger.py:18-23、core/agent_runner/run_files.py:93-119） | pass | 0/4 | - |
| mwl-ledger-concurrent-append-no-tear | design 风险节并发契约：8 个独立进程并发向同一台账追加（执行者进程与 daemon 并存并发的真实形态），O_APPEND 下由内核串行化，读侧全量 8 条、零半行 JSON 撕裂（出处 core/maintenance_ledger.py:18-23、spec design.md 风险节） | pass | 0/5 | - |
| mwl-prefix-true-source-table | R2.1 正向：真源表 RUN_ID_AGENT_PREFIXES 含 ("maintenance-", "maintenance") 映射，infer_run_agent_type 把 maintenance-<scope>-<ts> 归属 maintenance 而非泛型 agent，未识别前缀仍兜底泛型 agent，run_spec_part 剥前缀与时间戳还原 scope 段（出处 core/agent_runner/run_files.py:32-66、75-86、163-183） | pass | 0/6 | - |
| mwl-prefix-admin-monitor-sync | R2.2 正向+回归边界：admin_monitor._RUN_PREFIXES 同步收录 maintenance-（登记型 run 在告警归因/盘点识别为有名主体），_spec_from_run_id 从 maintenance-<scope>-<ts> 还原 scope、无时间戳尾段不强行归属；裸 planner-/test- 仍不计入失败计数子集（design 1 拆分约束回归守卫）（出处 core/admin_monitor.py:570-592、6703） | pass | 0/7 | - |
| mwl-runid-make-and-associate | R3 正向：make_maintenance_run_id 生成 maintenance-<scope>-<epoch 秒> 形态且 epoch 新鲜；台账条目携带 run_id 落账后 list_entries_for_run 精确反查（2 条命中、run_id 逐字一致），未命中 run 返回空列表，全量读取含无关联条目共 3 条（出处 core/maintenance_ledger.py:79-93） | pass | 0/7 | - |
| mwl-runid-cross-module-chain | R3×R2 交互链：make_maintenance_run_id 生成的 run id 经真源表归属 maintenance、经 admin_monitor._spec_from_run_id 还原 scope、再经 list_entries_for_run 反查到登记条目——告警归因→台账复盘引用的关联闭环（出处 core/maintenance_ledger.py:79-93、core/agent_runner/run_files.py:75-86、core/admin_monitor.py:6703） | pass | 0/5 | - |
| mwl-pytest-ledger-suite | 验收回归：tests/test_maintenance_ledger.py 全量通过——R1 追加/读取/空文件创建/坏行容错/超长行 + R3 run_id 关联共 7 例（-v 逐例 PASSED、汇总 7 passed）（出处 tests/test_maintenance_ledger.py） | pass | 0/4 | - |
| mwl-pytest-admin-prefix-suite | 验收回归：tests/test_admin.py::TestFailurePrefixSubset 全量通过——maintenance- 两处前缀表识别（真源表成员 + _RUN_PREFIXES 成员与 scope 还原）与裸 planner-/test- 排除边界共 4 例（出处 tests/test_admin.py:1356-1386） | pass | 0/4 | - |
