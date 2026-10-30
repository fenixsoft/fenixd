# fix-codefix-mapping-dotted-file-poison — Design

## Context

回归失败明细 → 定向子集 nodeids 的映射链路：

```
run_regression → parse_junit_xml（regression.py:195 tc_file=_resolve_file(tc)）
  → 快照 failures: [{name, file: 点分兜底, classname, message, ...}]
    → code_fix._ingest_failure_round（首轮）/ 定向轮 round_items 提取
      → _map_junit_failures_to_nodeids(failures, exec_root=wt)
        → classname 主导重构 nodeid → 与 file 属性一致性校验 → 点分≠路径 → ([], False)
```

- `_map_junit_failures_to_nodeids` 的 file 校验设计意图：真 file 属性（go-junit 等）
  参与一致性校验防重构漂移；pytest junitxml 不产 file 属性属预期形态（docstring 明示）。
- 但 `parse_junit_xml` 的 `_resolve_file` 兜底把「无 file 属性」变成了「file=点分
  classname」——上游兜底毒化了下游「缺失才免检」的前提。
- 已验证的规避方式（本仓既有，add-regression-issues-rerun D3）：喂映射前剥离 file 键，
  `map_snapshot_issues_to_nodeids`（daemon issues-rerun 消费侧）已在用，测试有钉子
  （「file=classname 兜底形态可映射成功」）。
- 熔断联动：`_is_regression_anomaly` 对 `failed` 且无明细返回 True；映射恒败使
  每轮真实失败都计数，`REGRESSION_ANOMALY_BREAKER_THRESHOLD=2` 两连即现场即弃
  （第 4 批 failed_batch_maxed 实证，16 条已修复条目被弃置后人工恢复）。

## Goals / Non-Goals

**Goals:**

- 本项目形态（pytest junitxml）下映射恢复成功：定向重试回到「失败用例子集回归」，
  明细可注入定向轮 prompt。
- 熔断口径回归设计意图：只有真零失败面（parse_error / failed 零记录 / timeout
  无明细）计 anomaly，真实测试失败（有明细）清零计数。
- 单一归一入口，两个调用点（首轮 `_ingest_failure_round`、定向轮 round_items
  提取）零漂移。

**Non-Goals:**

- 不改 `parse_junit_xml` / `_resolve_file` 的兜底形态（file 字段对快照展示、
  long_tests、issues-rerun 消费侧有既有语义，动上游波及面大）。
- 不改 `_map_junit_failures_to_nodeids` 对真 file 属性的一致性校验（jest-junit /
  go-junit-report 形态的防漂移语义保留）。
- 不改熔断阈值、预算档位、失败登记/核销/告警契约。
- 不处理「点分 file 归一为路径」的进阶方案（剥离已足够且是已验证范式；归一引入
  双形态歧义，收益为零）。

## Decisions

**D1 剥离入口单一函数，调用点显式经它。** 新增模块级助手
`_snapshot_failures_for_mapping(failures) -> list[dict]`：逐条浅拷贝并 `pop("file")`
（非 dict 条目原样透传，交由 `_map_junit_failures_to_nodeids` 既有 fail-closed 判），
返回新列表（MUST NOT 原地改快照——快照同源供展示/落盘）。`_ingest_failure_round`
与定向轮 round_items 提取两处调用它后再喂映射；`exec_root` 语义不变。

**D2 不在 `_map_junit_failures_to_nodeids` 内部兜底剥离。** 该函数的 file 校验对
「真 file 属性」形态仍有语义（本项目回归快照之外的使用者）；把「剥离」放在喂侧
（对齐 `map_snapshot_issues_to_nodeids` 既有先例与注释），函数契约保持
「file 属性存在即参与校验」。

**D3 验证以既有钉子为模板扩展。** `tests/test_codefix_targeted_retry.py` 已有
「file=classname 兜底形态可映射成功（剥离 file 生效）」用例（issues-rerun 封装侧）；
本 SPEC 在同文件补 code-fix 内部路径的同款钉子（`_ingest_failure_round` 与 round_items
提取点各一），外加端到端一例：注入含点分 file 的快照 → mapped=True →
`subset_nodeids` 非空（子集语义恢复）。

## Risks / Trade-offs

- **真 file 属性形态被剥**：本项目回归快照不存在该形态（pytest junitxml）；若有
  未来非 pytest 回归源写入真 file，剥离后该校验静默失效——可接受（fail-open 方向
  仅损失一项防漂移校验，不产生错误 nodeid；nodeid 仍以 classname 主导重构）。
- **浅拷贝开销**：failures 规模为失败用例数（个位数~几十），可忽略。
- **行为变化面**：定向轮 prompt 从「旧式摘要注入」变「累计失败明细注入」——这是
  add-codefix-targeted-retry 的设计意图恢复，非新行为。
