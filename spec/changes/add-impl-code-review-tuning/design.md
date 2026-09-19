# Design: add-impl-code-review-tuning

## Context

`add-impl-code-review-gate` 让实现者在收尾阶段调 `bin/ocr_review.py` 审查本次改动，产物落 `.fenix/verify-progress/<spec>/code-review.json`，由 `result_gate._check_impl_code_review_artifact` 硬门对账。该能力落地后，两个真实 run 的收尾审查都出现**大面积文件级超时**：

- `add-code-review-agent-and-quality-tab`：22 个待审文件，`status: partial`，**9 failed / 13 completed**，9 条失败**全部** `classification: "timeout"`（`reason: "file review exceeded its time limit"`）。
- `retry_report`（同一份报告）三次失败请求：`error_class: "timeout"`、`failure_phase: "context"`、`duration_to_headers_ms` = **300038 / 300041**（另一个 78928 为整轮中止截断）——**恰好 300.0s 整**，是在等上游首字节时被掐断。

三个直接成因：

| 成因 | 现状 | 证据 |
|---|---|---|
| 并发过高 | ocr `--concurrency` 缺省 **8** | `ocr review --help`；同一网关 8 路并发排队放大首字节延迟 |
| 单请求超时短 | provider `timeout_sec` **未配置 → 走 300s 默认** | 实测 `ocr config set custom_providers.<n>.timeout_sec` 是合法键；日志 300.0s 整 |
| 力度不可调 | ocr `--effort low\|medium\|high`（缺省 medium）**框架未暴露** | 实现者只能即兴选（该 run 先试 `--max-tokens-budget 20000/60000` 连废两轮，才改用 `--effort low`） |

**参数性质差异（决定落点）**：

- `timeout_sec` 是 **provider 级持久化配置键**——`ocr config set custom_providers.<name>.timeout_sec <n>` 实测生效（非法值报 `must be an integer`）。→ 可经 run 级 `ocrcfg/.opencodereview/config.json` **确定性注入**。
- `--concurrency` / `--effort` 是 **CLI flag**——ocr 的 `unset supports provider, max_tokens, effort, custom_providers.<name>, mcp_servers.<name>` 未列出 `concurrency`；`effort` 虽是持久化键但按 run 变化更合理。→ 只能经**提示词命令示例**承载。

## Goals / Non-Goals

**Goals：**

1. 三个参数（超时秒数 / 并发数 / 审查力度）可由用户配置，用户级默认 + 项目级覆盖。
2. `timeout_sec` 确定性注入 run 级 ocr 配置；`concurrency` / `effort` 经提示词承载。
3. Dashboard「质量」页签提供三项可视化编辑（新增配置项必须同时具备界面能力）。
4. 缺省值取「更省更快」侧：`600` / `2` / `low`。

**Non-Goals：**

- 不改变审查**范围**（ocr `review` 本就是 diff-based：`ocr --help` 原文 "Start a diff-based code review"；实测 payload 为 unified diff 片段，非整文件）。全量审是另一个命令 `ocr scan`。
- 不修改既有硬门语义、降级通道（`unavailable` + 非空 `reason`）、触发时机。
- 不引入 ocr 之外的审查引擎；不把审查结果从"绿门"升级为"质量门"。

## Decisions

### D1：三个平行配置键，合并为子节

**决策**：新增 `verify.impl_code_review_timeout_sec` / `_concurrency` / `_effort` 三个平级键。

**理由**：与既有 `verify.impl_code_review`（bool）同前缀，读侧零迁移；若把 bool 改成 dict 子节，需改既有读侧与存量配置，破坏面大。三个读取器独立回退，互不牵连。

### D2：`timeout_sec` 走配置注入，`concurrency` / `effort` 走提示词

**决策**：`_write_run_ocr_config` 落盘 `timeout_sec`；`_impl_code_review_section` 命令示例写 `--concurrency <n> --effort <v>`。

**理由**：参数性质决定落点（见 Context）。`timeout_sec` 是持久化键 → 注入即确定性生效；`concurrency` 非持久化键 → 无 env/配置通道，只能提示词。

**取舍（明确记录）**：提示词承载 = **软约束**，实现者不照抄命令示例即失效。缓解：命令示例给完整串 + 单测断言串内容。这是既有架构的既有限制（`--effort` 本就是 flag），本 SPEC 不引入新机制。

### D3：缺省 `effort = low`

**决策**：缺省从 ocr 官方的 `medium` 下调为 `low`。

**理由**：用户决策。低力度更快更省；`add-code-review-agent-and-quality-tab` 那轮 `--effort low` 在 22 文件上跑出 13 completed / 2 findings，可用。ocr README 自陈「Recall 低于通用 agent，是 precision 优先的刻意取舍」，低力度会进一步压低 recall，属已知取舍，用户可上调。

### D4：并发缺省 2

**决策**：`concurrency` 缺省 2（ocr 缺省 8）。

**理由**：8 路并发同时打同一 provider 网关是首字节延迟飙至 300s 的合理放大器。降到 2 以吞吐换稳定。**注意**：这是**基于证据的推断**——300.0s 整的超时形态与"8 路排队"一致，但未做 8 vs 2 的 A/B 实测。设计上不依赖该推断成立：超时从 300→600 单独也能缓解。

### D5：复用既有的 `unavailable` 降级，不新增失败通道

**决策**：三参数非法/缺失一律回退缺省，MUST NOT 使审查失败或阻塞派发。

**理由**：与 `add-impl-code-review-gate` D7（环境缺失 fail-open 放行）同构——环境类/配置类缺口不得被当交付物缺口重派。

## Risks / Trade-offs

- **[提示词软约束失效]** 实现者可能不照抄 `--concurrency` / `--effort`。→ 缓解：命令示例给完整串 + 单测断言；`timeout_sec` 不受此风险（确定性注入）。
- **[并发降到 2 使单次审查更慢]** 22 文件在并发 8 下 15m17s；并发 2 理论上更慢。→ 取舍：宁慢勿废（超时的 9 个文件是**零产出**的纯浪费）。若实测过慢，用户可上调该键。
- **[缺省 low 漏问题]** 低力度可能漏真问题。→ 用户可配 `medium` / `high`；这是用户明示的取值。
- **[`--max-tokens-budget` 仍可被实现者自选]** 本 SPEC 只在提示词里禁止，未在 `bin/ocr_review.py` 硬拦。→ 记录为已知残余缺口；若要机械级保险需包装器拦截（会连带禁掉有意的预算控制，需另行决策）。

## 上游依赖与证据文件

- 实测报告：`.fenix/verify-progress/add-code-review-agent-and-quality-tab/code-review-raw.json`（`manifest.coverage.failed` 9 条 timeout；`retry_report` 300.0s 整）。
- ocr 版本：`v1.12.6`（`ocr --version`）。
- 相关提交：`cccca881`（提示词禁 `--max-tokens-budget`）、`de3acff8`（键名别名容错）。
