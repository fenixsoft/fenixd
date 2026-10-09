# fix-codefix-mapping-dotted-file-poison

## Why

code-fix 定向重试链路的回归失败明细映射在本项目**恒失败**：`core/regression.py` 的
`parse_junit_xml` 给每条 failure 填 `file = tc.get("file") or tc.get("classname")`
（`_resolve_file` 兜底），而 pytest junitxml 不产 file 属性，所以快照 failures 的
`file` 恒为**点分 classname 形态**（如 `tests.test_x`）。`core/code_fix.py` 的
`_ingest_failure_round` 与定向轮 round_items 提取点把这份 failures **原样**喂给
`_map_junit_failures_to_nodeids`，该函数用 classname 重构出 `tests/test_x.py` 后做
file 一致性校验，点分 ≠ 路径 → 整体判 `mapped=False` → fallback_full「无可用明细」。

实测：2026-10-08 全天 12 个 `fix-reg-failures-*.json` 全部 `items: 0 / fallback_full: true`，
映射一次都没成功过。该缺陷在 add-regression-issues-rerun design D3 中已被记录
（「该缺陷同时存在于既有 targeted-retry 路径，本 SPEC 不修其调用点」——当时只在新封装
`map_snapshot_issues_to_nodeids` 内剥离规避）。

后果已从「定向重试恒回全量（浪费）」升格为「批级阻塞」：2026-10-08 落地的回归异常
熔断/异常重派预算机制把「failed 无可用明细」计为 anomaly（连续 2 次即熔断现场即弃），
映射缺陷把**每轮真实失败都伪装成异常**——第 4 批两连 anomaly 触发熔断，16 条已修复
条目被弃置（failed_batch_maxed，需人工），车道事实死锁（实证复盘见
`fix-failed.json` / run 转录 code-fix-1791494817）。

## What Changes

- `core/code_fix.py` 新增单一归一入口：喂给 `_map_junit_failures_to_nodeids` 前
  把快照 failures 条目的 `file` 键**剥离**（对齐 `map_snapshot_issues_to_nodeids`
  已验证的规避方式——file 属性缺失本就是 pytest 预期形态，剥离零信息损失；
  真 file 属性形态本就不存在于本项目回归快照，非 Python 标识符 classname 仍走
  既有 fail-closed）。
- `_ingest_failure_round` 与定向轮 round_items 提取两个调用点经该入口喂映射，
  使 mapped=True 时定向重试恢复**子集回归**语义、失败明细可注入定向轮 prompt。
- 熔断计数口径不变：映射修复后，真实测试失败（有明细）按既有语义清零计数，
  只有真正的零失败面（parse_error / failed 零记录 / timeout 无明细）才计 anomaly。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `code-fix-lane`: 回归失败明细的 nodeid 映射输入归一——快照 file 点分兜底形态
  MUST NOT 毒化 file 一致性校验；定向重试在本项目（pytest junitxml）恢复子集语义。

## Impact

- 受影响代码：`core/code_fix.py`（1 个归一函数 + 2 个调用点）。
- 受影响行为：code-fix 首轮回归失败后的定向重试从「恒回全量」恢复「子集回归」；
  anomaly 熔断只对真零失败面触发。
- 不触及：回归执行原语（core/regression.py）、熔断阈值、预算档位、台账/告警契约。
