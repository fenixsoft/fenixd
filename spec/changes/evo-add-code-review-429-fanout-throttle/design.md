# Design: code-review-429-fanout-throttle

## 现状与落点

并发上限是文本契约：agents/code-review.md:39 占位符 repo_concurrency，取值链为 core/config.py:4791-4793 get_repo_code_review_concurrency（缺省 4）→ core/agent_runner/maintenance_runs.py:3049-3063 run_code_review 注入段 → 提示词。code-fix 同构：agents/code-fix.md:57-58 wave_cap 分档（分档函数 core/code_fix.py:2466，经 prompt_builder 注入）。框架不校验在飞数——run 主体（claude -p）经 Task 工具自行派发，框架只见 parent 进程终态，因此 run 内约束只能落在提示词契约层。

## 改动设计

1. **静态降档**：core/config.py 读器缺省 4→2；.fenix/config.template.yaml 模板值同步（模板注释明文要求示例值=缺省值，否则模板派生配置恒为显式旧值、缺省调整失效）。
2. **跨 run 记忆折减**：在 maintenance_runs.py 注入段生成 repo_concurrency 前，定位最近一份同车道 run 归档 jsonl（runs/archive 下按修改时间），扫尾部窗口（先例：_salvage_terminal_conclusion_rows :3951、尾部 64KiB 读法 :3731），匹配 429 终态签名（「429」「1302」「rate_limit」）的子代理 task 失败记录；命中则折减至 1。任何扫描异常按原配置值放行（fail-open，不阻塞派发）。
3. **run 内记忆条款**：agents/code-review.md 与 agents/code-fix.md 各追加一段——429 子代理死亡后波内上限不得回升、重派间隔 ≥60s、同 run 第二次 429 后 ≥180s，沿 code-review.md:39 既有「违反 = run 判失败」语义执行。纯文本约束是当前架构下唯一可行层（框架无子代理派发强制点），11-24 晚 run 主体自发降档证明该层可被遵守。
4. **收尾告警**：在 maintenance_runs.py 终态归因段（:3611-3648，已有 claude_error / claude_result_text 上下文）扫描本 run jsonl 统计 429 死亡数；≥3 时经 core/admin_store.py:948 append_if_absent 直写（不入处置链防自环，先例 lane_preflight.py:365 ensure_lane_env_alert）。signal_type=review_subagent_ratelimit，dedup_key 含 run id。

## 与在途 SPEC 的边界

evo-quota-reset-dispatch-freeze（在途）：provider_circuit 层，解析 429 报文重置时刻并冻结 run 级派发。本 SPEC 不触 provider_circuit、不改 run 级冷却、不做 per-provider 429 时点持久化——两层正交：它管「该不该派这个 run」，本 SPEC 管「run 内派多少子代理」。若两者先后落地互不冲突。

## 风险

- 上限降为 2 会拉长全仓审查时长（波次变多）。09-24 与 11-24 两次事故证明 4 并发在账户限流面前是伪吞吐（秒死重派 + parent 接管的隐性成本更高），接受该代价；显式配置仍可调回。
- 尾部窗口扫描可能漏掉超大 run 中部的死亡记录——告警计数与记忆折减均允许低估（宁可少报不误报），不做全量扫描以控制收尾开销。
