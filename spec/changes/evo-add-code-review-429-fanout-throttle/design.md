# Design: code-review-429-fanout-throttle

## 现状与落点

并发上限是文本契约：agents/code-review.md:39 占位符 repo_concurrency，取值链为 core/config.py:4969-4971 get_repo_code_review_concurrency（缺省 4）→ core/agent_runner/maintenance_runs.py:3049-3063 run_code_review 注入段 → 提示词。code-fix 同构：agents/code-fix.md:57-58 wave_cap 分档（分档函数 core/code_fix.py:2466，经 prompt_builder 注入）。框架不校验在飞数——run 主体（claude -p）经 Task 工具自行派发，框架只见 parent 进程终态，因此 run 内约束只能落在提示词契约层。

## 改动设计

1. **静态降档**：core/config.py 读器缺省 4→2（实测 :4969-4971）；.fenix/config.template.yaml 模板值同步（模板注释明文要求示例值=缺省值，否则模板派生配置恒为显式旧值、缺省调整失效；注释内「正整数，缺省 4」文案同步改 2）。缺省同源面另有两处 MUST 一致降档：① core/agent_runner/prompt_builder.py 注入段 fail-open 回退——detail 缺失/脏值时回读读器（自动跟随），但 ConfigLoader 导入失败分支硬编码 `repo_concurrency = 4`（实测 :2466 附近），只改读器则该异常路径仍注入 4、降档被绕过；② core/dashboard/static/src/pages/settings/components/QualityPanel.tsx:56 `REPO_REVIEW_DEFAULT_CONCURRENCY = 4`（注释明示与 ConfigLoader 缺省同源，:161 空值回显、:727 描述文案消费），不同步则设置页回显 4 与后端生效 2 漂移。**一键两用声明**：该键同时是 `ocr scan --concurrency` 缺省并行度（config.py:4970 docstring 与模板注释均明示），降档对两通道同时生效，属 proposal 声明的接受面。
2. **跨 run 记忆折减**：在 maintenance_runs.py 注入段生成 repo_concurrency 前，定位最近一份同车道 run 归档 jsonl（runs/archive 下按修改时间），扫尾部窗口（先例：_salvage_terminal_conclusion_rows :3951、尾部 64KiB 读法 :3731），匹配 429 终态签名（「429」「1302」「rate_limit」）的子代理 task 失败记录；命中则折减至 1。任何扫描异常按原配置值放行（fail-open，不阻塞派发）。
3. **run 内记忆条款**：agents/code-review.md 与 agents/code-fix.md 各追加一段——429 子代理死亡后波内上限不得回升、重派间隔 ≥60s、同 run 第二次 429 后 ≥180s，沿 code-review.md:39 既有「违反 = run 判失败」语义执行。纯文本约束是当前架构下唯一可行层（框架无子代理派发强制点），11-24 晚 run 主体自发降档证明该层可被遵守。
4. **收尾告警**：在 maintenance_runs.py 终态归因段（:3611-3648，已有 claude_error / claude_result_text 上下文）扫描本 run jsonl 统计 429 死亡数；≥3 时经 core/admin_store.py:985 append_if_absent 直写（不入处置链防自环，先例 lane_preflight.py:365 ensure_lane_env_alert）。signal_type=review_subagent_ratelimit，dedup_key 含 run id。

## 与在途 SPEC 的边界

evo-quota-reset-dispatch-freeze（在途）：provider_circuit 层，解析 429 报文重置时刻并冻结 run 级派发。本 SPEC 不触 provider_circuit、不改 run 级冷却、不做 per-provider 429 时点持久化——两层正交：它管「该不该派这个 run」，本 SPEC 管「run 内派多少子代理」。若两者先后落地互不冲突。

evo-code-review-subagent-429-throttle（同题在途，2026-11-27 与本 SPEC 同日并行评审）：对本问题（11-24/11-25 两晚 429 事故）的第二次立项。重叠面：config.py 读器缺省 4→2、agents/code-review.md:39 处 429 处置条款追加。互补面：本 SPEC 独有跨 run 记忆折减（扫归档 jsonl）与 code-fix 车道记忆条款；该 SPEC 独有指数退避（60/120/240s）、连续秒死停派转自审、完成统计行标记解析告警。**实现协调规则**（后落地方实现前 MUST 执行）：

1. 缺省降档三处同源面（读器 / prompt_builder 回退值 / QualityPanel 常量）以先落地者为准，后落地者幂等跳过已达标项。
2. agents/code-review.md 的 429 处置退避规则 MUST 单段存在——本 SPEC 固定间隔（≥60s / 第二次后 ≥180s）与该 SPEC 指数退避（60/120/240s）语义互斥，MUST NOT 两段并存（run 主体将无所适从）；后落地者实现前须把先落地条款收编为单一段落（保留其一、吸收另一方的差异点进同段）。
3. 告警通道 MUST 二选一：本 SPEC 收尾 jsonl 扫描直写（AdminStore.append_if_absent）与该 SPEC 统计行标记解析消费（CodeReviewResult 字段 + admin_monitor getattr）并存会对同一事件产生双告警；先落地者通道保留，后落地者放弃自己的通道并在其文档登记放弃原因。

## 风险

- 上限降为 2 会拉长全仓审查时长（波次变多）。09-24 与 11-24 两次事故证明 4 并发在账户限流面前是伪吞吐（秒死重派 + parent 接管的隐性成本更高），接受该代价；显式配置仍可调回。
- 尾部窗口扫描可能漏掉超大 run 中部的死亡记录——告警计数与记忆折减均允许低估（宁可少报不误报），不做全量扫描以控制收尾开销。
