# code-fix-lane delta：回归失败明细映射输入归一（点分 file 兜底毒化修复）

## MODIFIED Requirements

### Requirement: 回归失败明细的 nodeid 映射

回归未通过时，code-fix SHALL 从回归快照 `failures` 提取结构化失败明细（nodeid +
summary）用于定向轮注入与子集回归，映射输入 MUST 经剥离归一：快照条目的 `file` 键
（`parse_junit_xml` 对 pytest junitxml 形态为点分 classname 兜底）MUST NOT 进入
`_map_junit_failures_to_nodeids` 的 file 一致性校验。

- 归一 SHALL 经单一函数入口（喂侧剥离，浅拷贝新列表，MUST NOT 原地改快照——快照
  同源供展示/落盘）；首轮全量回归（`_ingest_failure_round`）与定向轮 round_items
  提取两个调用点 MUST 同经该入口，MUST NOT 一处剥离一处不剥。
- 非 dict 条目 SHALL 原样透传，交由 `_map_junit_failures_to_nodeids` 既有
  fail-closed 判整体失败回全量。
- 映射成功（`mapped=True`）时定向重试 SHALL 按失败用例子集回归（既有 2.1 语义），
  MUST NOT 因点分 file 兜底形态退化为恒全量（fail-open 面收窄为本缺陷修复目标）。
- 真实测试失败（`failed`/`timeout` 且明细非空）MUST NOT 计入回归异常熔断计数
  （`_is_regression_anomaly` 既有语义，映射修复后恢复可达）；零失败面
  （parse_error / failed 零记录 / timeout 无明细）计数口径不变。

#### Scenario: 点分 file 兜底形态映射成功（本项目真实形态）

- **给定** 回归快照 failures 含条目
  `{"name": "test_bar", "file": "tests.test_x", "classname": "tests.test_x.TestFoo", "message": "AssertionError: ..."}`
  （pytest junitxml 经 `_resolve_file` 兜底后的真实形态），且 worktree 内存在
  `tests/test_x.py`
- **当** 首轮回归失败经 `_ingest_failure_round` 提取明细
- **则** 映射返回 `([{nodeid: "tests/test_x.py::TestFoo::test_bar", summary: ...}], True)`
  ——`mapped=True`，`fallback_full=False`，failures 明细落盘非空

#### Scenario: 剥离不改快照原对象

- **给定** 同上快照（列表与条目 dict）
- **当** 经归一入口处理
- **则** 原 failures 列表及其条目的 `file` 键原样保留（新列表浅拷贝），同源消费方
  （展示/落盘/快照回写）不受影响

#### Scenario: 真实测试失败不再误计回归异常

- **给定** 一批修复后首轮全量回归 `status="failed"` 且 junit 可解析、失败记录非空、
  classname 全部可映射（本项目形态）
- **当** 进入定向重试循环的异常判定
- **则** `_is_regression_anomaly` 返回 False，`anomaly_streak` 清零——不因「无可用
  明细」触发 `regression_parse_error_breaker` 熔断（第 4 批阻塞形态根因）

#### Scenario: 真 fail-closed 形态口径不变

- **给定** 快照 failures 含非 dict 条目，或 classname 缺失/非 Python 标识符形态
- **当** 经归一入口喂映射
- **则** 整体判 `mapped=False` 回退全量（既有 fail-closed 语义逐字保留），且该轮
  按 `_is_regression_anomaly` 既定口径计数
