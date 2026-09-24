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

- `timeout_sec` 是 **provider 级持久化配置键**——`ocr config set custom_providers.<name>.timeout_sec <n>` 实测生效（非法值报 `must be an integer`）。→ 可经 run 级 `ocrcfg/.opencodereview/config.json` **确定性注入**。（说明：`ocr config set` 对存在但未注册的 provider 会先报 `provider "<n>" is not configured`，须按 url→api_key→model→timeout_sec→protocol→provider 顺序设置；run 级配置由框架**直接写 config.json**，不经过 `config set` 入口，且该路径已被既有实现与测试证明可用。）
- `--concurrency` 是**纯 CLI flag**——`ocr config set concurrency 2` 实测报 `unknown config key: concurrency`（ocr 的已知键清单含 `effort` 而无 `concurrency`）。→ 无 env/配置通道，只能经**提示词命令示例**承载。
- `--effort` **兼具 CLI flag 与同名持久化键**——实测 `ocr config set effort low` 生效并落盘 `{"effort": "low"}`；`ocr review --help` 自陈 `--effort string  review effort preset: low | medium | high ("" = configured or default medium)`，即实参优先、留空时取配置。本 SPEC 仍将其与 `--concurrency` 同走提示词（见 D6）。

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

**理由**：参数性质决定落点（见 Context）。`timeout_sec` 是持久化键 → 注入即确定性生效；`concurrency` 无配置键 → 只能提示词；`effort` 虽可持久化，但单通道优先（D6）。

**取舍（明确记录）**：提示词承载 = **软约束**，实现者不照抄命令示例即失效。缓解：命令示例给完整串 + 单测断言串内容。这是既有架构的既有限制（`--effort` 本就是 flag），本 SPEC 不引入新机制。

### D3：缺省 `effort = low`

**决策**：缺省从 ocr 官方的 `medium` 下调为 `low`。

**理由**：用户决策。低力度更快更省；`add-code-review-agent-and-quality-tab` 那轮审查在结束时带的 `--effort low` 下 22 个文件跑出 **13 completed / 9 failed（全部 timeout）**——**注：该轮 9 个文件失败与 effort 取值无关**（凭 `retry_report` 中 `error_class: timeout, failure_phase: context` 的整 300.0s 形态判定，见 D4）。低力度是否实际减少失败文件数**尚未经 A/B 对照实测**，不同时长的 run 亦不可直接比较（`evo-spec-concurrency-flight-guard` 的收尾审查发生在本轮并发/超时注入之前）；但该轮 13 个 completed 文件产出的 2 条 findings 可用，说明 `low` 并非零产出。ocr README 自陈「Recall 低于通用 agent，是 precision 优先的刻意取舍」，低力度会进一步压低 recall，属已知取舍，用户可上调。

### D4：并发缺省 2

**决策**：`concurrency` 缺省 2（ocr 缺省 8）。

**理由**：8 路并发同时打同一 provider 网关是首字节延迟飙至 300s 的合理放大器。降到 2 以吞吐换稳定。**注意**：这是**基于证据的推断**——300.0s 整的超时形态与"8 路排队"一致，但未做 8 vs 2 的 A/B 实测。设计上不依赖该推断成立：超时从 300→600 单独也能缓解。

**补充（监督空闲杀护栏）**：并发降到 2 会使同一 run 内零新事件的静默窗口变长（22 文件 / 并发 8 的历史 run 墙钟即 916.9s）。`agents.timeout_supervision.enabled` 为 true 时，`config.template.yaml` 记录的第 3 条判定为「judge_window 秒内零 run 事件 → 跳过 LLM、直接判停滞终止」。**风险假设（未实测）**：若该「run 事件」口径与 agent 输出流绑定，则并发降到 2 会把长静默窗口推得更长，理论上提高被误判停滞的概率。本变更**不放宽**任何超时阈值（不碰 `agents.run_timeout_seconds` / `timeout_supervision.*`）——单次审查墙钟远小于 `absolute_max_seconds = 16200`，且终止路径留有取证；但在实现收尾的实测中 MUST 顺带观察一次收尾审查是否被监督终止（进程被 kill / 结果含 `stagnant`）。若实测出现停滞误判，属独立治理项，须另开 SPEC 处理，MUST NOT 在本变更内顺手调监督阈值。

### D5：复用既有的 `unavailable` 降级，不新增失败通道

**决策**：三参数非法/缺失一律回退缺省，MUST NOT 使审查失败或阻塞派发。

**理由**：与 `add-impl-code-review-gate` D7（环境缺失 fail-open 放行）同构——环境类/配置类缺口不得被当交付物缺口重派。

### D6：`concurrency` / `effort` 保持单一注入通道（提示词）

**决策**：`--effort` 虽有同名持久化键（`ocr config set effort low` 实测生效），仍与 `--concurrency` 一样只经提示词命令示例注入，**不**额外写入 run 级 `ocrcfg/.opencodereview/config.json`。

**理由**：① 双通道会在"提示词带实参、配置文件带旧值"时产生遮蔽歧义（实参优先），排障时难以判定生效值来源；② `concurrency` 无论如何都只能走提示词，保留同一段命令示例可让两个参数在配置→提示词链路上同型；③ 若实现者改写命令形态（提示词本就允许按改动规模自选 `--from/--to`、`--commit`、工作区模式），`effort` 这一项会因为持久化而仍然生效，反而**部分补偿**软约束失效风险。

**升级路径（记入残余缺口）**：若后续实测提示词软约束频繁失效，可把 `effort` 改走 D2 的配置注入通道使其确定性生效——该改动局限在 `_write_run_ocr_config` + 本段文档内，不改变本 SPEC 的其余决策。

## Risks / Trade-offs

- **[提示词软约束失效]** 实现者可能不照抄 `--concurrency` / `--effort`。→ 缓解：命令示例给完整串 + 单测断言；`timeout_sec` 不受此风险（确定性注入）；`--effort` 另有同名持久化键兜底（D6，实参优先）。
- **[并发降到 2 使单次审查更慢]** 22 文件在并发 8 下 15m17s；并发 2 理论上更慢。→ 取舍：宁慢勿废（超时的 9 个文件是**零产出**的纯浪费）。若实测过慢，用户可上调该键。
- **[缺省 low 漏问题]** 低力度可能漏真问题。→ 用户可配 `medium` / `high`；这是用户明示的取值。
- **[`--max-tokens-budget` 仍可被实现者自选]** 本 SPEC 只在提示词里禁止，未在 `bin/ocr_review.py` 硬拦。→ 记录为已知残余缺口；若要机械级保险需包装器拦截（会连带禁掉有意的预算控制，需另行决策）。

## 上游依赖与证据文件

- 实测报告：`.fenix/verify-progress/add-code-review-agent-and-quality-tab/code-review-raw.json`（`manifest.coverage.failed` 9 条 timeout；`manifest.execution.configured_concurrency = 8`；`manifest.elapsed_ms = 916894`；`retry_report` 三条失败请求 `duration_to_headers_ms` = 300038 / 300041 / 78928）。
- 本 SPEC 评审期的**独立复现实验**（探针，非交付物）：把 ocr 指向一个只接受 TCP 连接、永不回包的本地端点（`127.0.0.1:59999`），可稳定复现 `failure_phase: "context"` 的 `duration_to_headers_ms`：未配 `timeout_sec` → **300000**（默认 300s，`manifest.elapsed_ms = 300099`）；配 `timeout_sec: 20` → **20016**；配 `timeout_sec: 25` → **25023**。据此确认 `timeout_sec` **确定性生效**（手工直写 `.opencodereview/config.json` 亦然）。另实测：`timeout_sec` 为字符串 → ocr 报 `json: cannot unmarshal string into Go struct field ... of type int`；超大整数 → `timeout_sec ... overflows time.Duration (max 9223372036)`（故读取器只需保证正整数，上界由 ocr 兜底）。
- ocr 版本：证据报告记录为 `v1.12.6`（`code-review-raw.json` 的 `manifest.execution.ocr_version`）；评审期实测本机已升级至 `v1.12.7`（`ocr --version`）。`timeout_sec` / `--concurrency` / `--effort` 三者在两个版本上语义一致（本评审的探针实验在 v1.12.7 上复现了三条结论），故不改变设计。
- 相关提交：`cccca881`（提示词禁 `--max-tokens-budget`）、`de3acff8`（键名别名容错）。
