# 验证报告 — add-deliverable-declaration-triage

- 验证时间：2026-09-06T03:11:37 (report.json)
- 场景总数：21（16 通过 / 5 失败）
- 裁决结论：**verified**（0 产品 Bug，5 失败均归因测试脚本缺陷）

## 结果总览

| 分类 | 数量 | 状态 |
|---|---|---|
| pass | 16 | 通过 |
| test-defect（测试脚本缺陷） | 5 | failed |
| product-bug / flaky / env | 0 | — |

## 失败场景逐项裁决

### 共同根因（5/5 失败同源）

产品功能本身全部验证正确，失败**全部**源于 CLI `json_output` 断言的 JSON path 语法错误：

- 断言使用裸 `0`（如 `path: "0"`、`path: "0.kind"`）作为路径；
- `evaluate_json_path(data, "0")` 将裸 `0` 解析为 **dict key**（`data.id` 形态），而相关 stdout 是 **JSON 数组**；
- 由于数据是 list 而非 dict，键查找失败 → 返回 `None` → 断言 `actual=null` 失败；
- 数组下标必须用 `[0]` 括号语法（`evaluate_json_path` 支持 `items[0]` 形态）。

通过直接复现确认产品输出正确（见下），故全部归为 **test-defect**。

### 1. lint-modify-missing-rejects（failed）

- 失败断言：`json_output path="0"` expected `在主树不存在`，actual `null`。
- 证据链：
  - 直接复现 `lint_declared` 的 stdout 为合法数组：
    `["[core/verification.py] 在主树不存在——modify 声明路径必须在主树存在（必须存在，指向既有文件），请核对声明路径（新建文件请用 kind: new）"]`
  - `evaluate_json_path(data, "0")` → `None`；正确语法 `"[0]"` → 命中字符串，contains `在主树不存在` 成立。
- 分类：`test-defect`；产品代码正确。

### 2. lint-reference-missing-rejects（failed）

- 失败断言：`json_output path="0"` expected `必须存在`，actual `null`。
- 证据链：直接复现 stdout 为合法数组：
  `["[core/nonexistent.py] 在主树不存在——reference 声明路径必须在主树存在（必须存在，指向既有文件），请核对声明路径（新建文件请用 kind: new）"]`
  `"[0]"` 语法命中，contains 成立。
- 分类：`test-defect`。

### 3. lint-new-unique-basename-rejects（failed）

- 失败断言：`json_output path="0"` expected `唯一 basename 命中`，actual `null`。
- 证据链：直接复现 stdout 为合法数组：
  `["[core/verification.py] 在主树不存在，疑似笔误——仓库内唯一 basename 命中 [core/pm_engine/verification.py]，请修正声明路径或改 kind"]`
  `"[0]"` 语法命中，contains 成立。
- 分类：`test-defect`。

### 4. lint-basename-excludes-dirs（failed）

- 失败断言：`json_output path="0"` expected `唯一 basename 命中`，actual `null`。
- 证据链：直接复现 stdout 为合法数组：
  `["[core/verification.py] 在主树不存在，疑似笔误——仓库内唯一 basename 命中 [core/pm_engine/verification.py]，请修正声明路径或改 kind"]`
  `"[0]"` 语法命中，contains 成立；且 node_modules 等排除目录生效（`node_modules` negate 断言已通过）。
- 分类：`test-defect`。

### 5. dispute-audit-store-roundtrip（failed）

- 失败断言（4 条）：`json_output` `0.kind` / `0.spec` / `0.judge_run_id` / `0.verdicts[0].verdict`，均 actual `null`。
- 证据链：直接复现 `DisputeAuditStore.read_all()` 的 stdout 为合法数组：
  `[{"kind": "dispute-audit", "spec": "verify-fixture-spec", "judge_run_id": "dispute-judge-verify-fixture-1720000000", "verdicts": [{"verdict": "typo"}]}]`
  同文件落盘断言（file_exists / file_content contains `dispute-audit`）已通过。
  正确语法 `"[0].kind"` / `"[0].spec"` / `"[0].judge_run_id"` / `"[0].verdicts[0].verdict"` 均命中。
- 分类：`test-defect`（4 条失败断言逐条同为 path 语法缺陷）。

## 产品 Bug 清单

无。

## 修复建议（测试脚本侧）

将失败 `json_output` 断言的 `path` 从裸 `0` 前缀改为括号数组下标语法：

| 场景 | 现 path | 应改为 |
|---|---|---|
| lint-modify-missing-rejects | `0` | `[0]` |
| lint-reference-missing-rejects | `0` | `[0]` |
| lint-new-unique-basename-rejects | `0` | `[0]` |
| lint-basename-excludes-dirs | `0` | `[0]` |
| dispute-audit-store-roundtrip | `0.kind` / `0.spec` / `0.judge_run_id` / `0.verdicts[0].verdict` | `[0].kind` 等（数组前缀加括号） |

修订后预期 21/21 全绿。

## 本轮场景集变更

当前稳定场景集共 21 个（第 1 轮）。

- 首轮写入 21 个场景

