# Design: fix-verdict-read-failclosed

## Context

事故链（2026-09-08，全部已取证到代码行）：

```
judge 判 bug-found（正确）
  └─ 写结果文件：相对路径 → 落 worktree（写端分叉）
       └─ runner 硬门（runner.py:1903）：查主树路径 → 验到上一轮旧合法文件 → 放行
            （拷回在 runner.py:2115-2133，晚于门检；门不查 mtime）
       └─ 拷回把非法 JSON（裸换行，line 25 col 402）落到主树
            └─ pm_engine 读侧（verification.py:2715）：JSONDecodeError → None
                 └─ 三阶段 else 分支（verification.py:1593）：None ≠ "bug-found"
                      → verified → done → auto-push（14 秒全程）
```

fail-open 语义当前被两处注释「load-bearing」地引用：`_read_verifier_result` docstring（「返回 None …视为 verified」）与 `_all_green_fast_path` 注释（「写回失败不阻断——…本就按 verified 兜底」）。语义反转时必须同步清账，否则下一个改代码的人会按旧注释把 fail-open「修」回来。

日志同族证据：08-27 起 `Failed to read verifier result`（×3，含 2 次 control character）与 `Unknown verifier status: 'success'/'blocked-env'/'scenario-repaired', treating as verified`（×5）——fail-open 不是理论风险，是复发 6+ 次的既有 wounds。其中 `verifier_status == "scenario-repaired"` 在白名单内但**当时**（09-06 修复前）被 else 吞掉属已修历史，不在本 SPEC 范围。

## Goals

1. 不可读裁决（缺失/非法 JSON/白名单外 status）在任何路径都**不得**等价于 verified。
2. 硬门验的就是本轮产出——陈旧残留文件无法替本轮放行。
3. fail-closed 后有确定出口：三阶段=重试一次→blocked+告警；legacy=blocked+告警；均不走「verified 无出口」死锁。

## Decisions

### D1 拷回前置，而非门检双路径探测

把 `_copyback_verify_progress(wt_path, spec_name)` 与根 result 拷贝移到门检**之前**（成功路径内、`_run_claude` 返回后立即执行），门检继续只查主树路径。备选「门检同时探测 worktree 路径」被否：两个事实源必然漂移（本次事故正是主树/工作树双落点分叉所致）；拷回幂等（mtime 守卫已有），前置无副作用。挪动后原「成功时拷回」代码块整体上移，勿留双份。

### D2 新鲜度用 mtime 下界，不引指纹

`_check_agent_result_artifact` 增参 `run_started_at: float`（attempt 启动时刻，attempt 循环已有 `attempt_started_at` 同类值），校验 `path.stat().st_mtime >= run_started_at`。备选内容指纹/会话 id 绑定被否：成本高且 judge 无稳定 run 级标识可写入文件。mtime 粒度（秒级）远大于门检窗口（毫秒级），足够。

### D3 白名单单一来源

`planner_result_status_whitelist = ("verified", "bug-found", "plan-ready", "scenario-repaired")` 定义一处（建议 `core/agent_runner/prompt_builder.py` 紧邻 `planner_result_path`，或 `core/pm_engine/verification.py` 顶部——实现时选被双方 import 更自然的一方），runner 门检与 pm_engine 读侧共用。`_read_verifier_result` 现有内联白名单改为引用该常量，行为不变。

### D4 三阶段 retry-then-block 复用既有模板

裁决采纳处（`verification.py:1497` 读后）：不可读 → 复用 `_verify_verdict_evidence` 的重试形态（`run_planner(spec_name, "judge")` 一次 → 复读）；二次仍不可读 → `update_spec(status="blocked", error=…)` + `_send_human_escalation_alert(signal_type="verdict_result_unreadable", severity="critical", …)`，与 verdict_evidence_invalid 分支同构（同款出口语义，无新机制）。重试轮同样受 D6 入口状态判据约束（非 testing 丢弃）。

不可读的判定与错误原文捕获：`_read_verifier_result` 返回值从 `str | None` 升级为结构化（如 `(status, error)` 二元组或小 dataclass），调用方三态分支：`ok(status)` / `unreadable(reason, detail)`；`_read_planner_result` 的 fallback spec-stamp 拦截（他 spec 残留）归入 `unreadable`（原因=foreign残留）。engine.py:2438-2442 委托签名同步。**缺失文件与解析失败不再合并为 None**——但处置相同（fail-closed），仅告警 reason 字段区分。

### D5 legacy 直接 blocked，不重试

legacy 是降级通道（三阶段两连败才进）；结果不可读说明结构性异常而非偶发，自动重派整轮 verifier 只会烧钱（一次 legacy verifier ≈ 完整验证链）。处置：blocked + 告警（同 D4 信号），交人工。

### D6 语义反转清账（防回归性「修回」）

- `_read_verifier_result` docstring：删除「视为 verified」，改述三态与 fail-closed 处置。
- `_all_green_fast_path` 注释：写回失败不再「不阻断按 verified 兜底」——快道写回失败时该轮按不可读处理（快道产物是机械合成，写回失败极罕见，退化为常规 judge 或 blocked 均可，以实现简为准，但**不得**静默 verified）。
- 全库 grep `视为 verified` / `按 verified 兜底` / `treating as verified`，命中注释/文档一并更新。
- 日志文案：`Unknown verifier status: '…', treating as verified` 改为 fail-closed 表述（该 WARNING 是运维排查的关键字面，本次取证即靠它定位）。

### D7 prompt 契约加固一行级

`agents/planner-judge.md` 步骤 6（写 {result_path}）追加：结果文件必须为**合法 JSON**（字符串内换行/引号/控制字符须转义，建议以代码 `json.dump` 生成而非手工拼接文本）。prompt_builder 动态契约段若复述该契约则同步一句。按 prompt 文件双落点约定（记忆：prompt 文件化后契约段落点）确认 merge 后无契约段漂移。

## Risks / Trade-offs

- **[行为变化] 全绿快道写回失败从静默放行变 fail-closed** → 影响面=0 失败 0 警告且写回失败的罕见组合；接受（宁可 blocked 也不可伪 verified）。
- **[成本] 三阶段多一轮 judge 重试** → 仅不可读场景触发（历史上 6+ 次/月量级），且 runner 硬门白名单/新鲜度前置拦截后，到达读侧的不可读会更少；用户已确认接受。
- **[出口] blocked 无自动出口** → 与 verdict_evidence_invalid 同语义，人工裁决是设计内出口；escalation 告警含错误原文与文件路径，人工可判定「修复文件后重置」或「重跑验证」。
- **[并发] 重试 judge 轮与在飞状态判据** → 重试前复用 D6 入口检查（非 testing 丢弃），与既有 stale-result 防护同构，不新增竞态面。

## Migration Plan

纯框架内行为变更，无数据迁移。存量 `blocked` spec 处置流程不变。上线即对在飞验证生效（daemon 常驻，合并后须重启——既有约定）。

## Open Questions

无（模式/处置/时机已与用户确认：full / 重试一次再阻断 / 立即执行）。
