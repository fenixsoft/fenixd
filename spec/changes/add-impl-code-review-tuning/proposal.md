## Why

`add-impl-code-review-gate` 落地的收尾代码质量审查（`verify.impl_code_review`）在真实使用中暴露三个调优缺口，导致审查**覆盖残缺或整轮跑废**：

1. **并发过高打满网关**。ocr 默认 `--concurrency 8`，8 路同时请求同一 provider 网关，首字节延迟被放大到撞穿单请求超时线。
2. **单请求超时过短**。ocr LLM 请求默认超时 300s（provider 级 `timeout_sec` 未配置时走默认）。实测 `evo-spec-concurrency-flight-guard` / `add-code-review-agent-and-quality-tab` 的审查均出现**恰好 300.0s 整**的 `error_class: timeout, failure_phase: context`——连响应头都没等到。
3. **审查力度不可调**。ocr 的 `--effort low|medium|high`（缺省 medium）是控制单文件审查深度的旋钮，但框架从未暴露给用户。

实证：`add-code-review-agent-and-quality-tab` 的收尾审查（22 个待审文件）产出 `status: partial`，**9/22 文件失败，全部 `classification: timeout`**，`retry_report` 三次失败请求的 `duration_to_headers_ms` 分别为 300038 / 300041 / 78928(截断)——全是超时，与 token 预算无关。三个参数目前都只能靠实现者自己在命令行即兴选择（该 run 先试 `--max-tokens-budget 20000/60000` 连废两轮，才改用 `--effort low`），既不可复现也不可运维。

## What Changes

- **新增三个可配置参数**（用户级默认 + 项目级覆盖，与既有配置键同机制）：

  | 配置键 | 语义 | 缺省 | 落点 |
  |---|---|---|---|
  | `verify.impl_code_review_timeout_sec` | ocr LLM 单请求超时（秒） | `600` | run 级 `ocrcfg/.opencodereview/config.json` 的 `custom_providers.fenix-impl.timeout_sec` |
  | `verify.impl_code_review_concurrency` | ocr 并发子任务上限 | `2` | 提示词命令 `--concurrency <n>` |
  | `verify.impl_code_review_effort` | ocr 审查力度 `low\|medium\|high` | `low` | 提示词命令 `--effort <v>` |

- **`ConfigLoader` 新增三个读取器**，与既有 `get_impl_code_review_enabled` 同型（缺省回退、非法值回退、脏值不中断派发）。
- **`runner._write_run_ocr_config` 注入 `timeout_sec`**，写入 run 级 ocr provider 配置。
- **`prompt_builder._impl_code_review_section` 命令示例注入 `--concurrency` / `--effort`**（并发与 effort 是 CLI flag，非持久化配置键，只能经提示词承载）。
- **Dashboard「质量」页签新增三个编辑项**（复用 `QualityPanel.tsx`，与既有 `impl_code_review` 开关同卡）。
- **`config.template.yaml` / 设置页受管键清单 / 文档同步**（新增配置项必须同时具备界面能力——见下方 Impact 的规范约束）。

**非目标**：不改变审查范围（ocr `review` 本就是 diff-based，只审本次改动）；不替换 `verify.impl_code_review` 的硬门与降级语义；不引入 ocr 之外的审查引擎。

## Capabilities

### New Capabilities

- `impl-code-review-tuning`: 收尾代码质量审查的三个运行参数（超时 / 并发 / 力度）的配置读取、run 级注入、提示词承载与 Dashboard 编辑能力。

### Modified Capabilities

<!-- 现有 impl-code-review-gate capability 的 spec 级行为（触发时机/审查范围/硬门/降级）不变，
     本变更只新增运行参数。若实现中发现需修订其 Requirement 文本，在此追加 delta。 -->
（无——本变更不修改既有 capability 的 Requirements，仅新增调优参数。）

## Impact

**配置层**
- `core/config.py`：新增 3 个读取器（`get_impl_code_review_timeout_sec` / `_concurrency` / `_effort`）。
- `.fenix/config.template.yaml`：`verify` 段新增 3 键（带注释与缺省值）。

**运行层**
- `core/agent_runner/runner.py`：`_write_run_ocr_config` 写入 `timeout_sec`。
- `core/agent_runner/prompt_builder.py`：`_impl_code_review_section` 命令示例注入 `--concurrency` / `--effort`。

**界面层（规范约束：新增配置项必须同步 Dashboard 编辑能力）**
- `core/dashboard/data/config_admin.py`：3 键登记为受管键 + sources 标注 + 读取合并回显。
- `core/dashboard/static/src/pages/settings/components/QualityPanel.tsx`：3 个编辑控件（数字输入 / 数字输入 / 下拉）。
- `core/dashboard/static/src/services/dashboard.ts`：类型定义补 3 键。
- `docs/help/08-dashboard.md` / `docs/help/09-config.md`：文档化。

**外部依赖**：无新增；仍依赖环境已安装 `ocr`（缺失时按既有 `unavailable` 降级）。

**风险与取舍**：
- `--concurrency` / `--effort` 是 CLI flag 而非持久化配置键（ocr `config` 不认这两个键），故只能经提示词承载——**参数对实现者仍是"建议"而非强制**。若实现者不照抄命令示例即失效；本 SPEC 以提示词固化 + 单测断言命令串来压低该风险。
- `timeout_sec` 是 provider 级真实配置键（实测 `ocr config set custom_providers.<name>.timeout_sec` 生效），注入后**确定性生效**。
- 缺省 effort 从 ocr 官方的 `medium` 下调为 `low`：更快更省，但按 ocr README 的取舍（precision 优先、recall 偏低）可能漏掉部分问题。用户可随时上调。
