# Design: add-turn-limit-anchor-c

## Context

2026-09-10 fenix-server 三起 implementer `Max turns (400) reached` 强杀（exit -9，无 result 终态）暴露 turn-limit 死法三不管：未提交现场不保全（builtin a1 零提交 84min 工作滞留 worktree）、健康推进被无差别腰斩（ssh a1 第 378 轮仍在正常勾选任务）、成本按零记账（`_extract_usage_info(None)` 全零，对照 a2 实测 $4.80/$18.52 证明假设「早夭消耗小」为假）。

现状代码锚点：

- 轮询环 turn-limit 判定：`runner.py:2852-2854`——`turn_count[0] >= max_turns` 即 `proc.kill()` + `turn_limit_error`，无活性判定、无 WIP 保全。
- 收口分支：`runner.py:2926-2931`——`turn_limit_error` 直接 `append_run_error` + `raise RuntimeError`，异常不携带 stderr_lines（注释明示防误判瞬断，保持）。
- 超时路径先例：`_supervision_deadline_action`（runner.py:3798，委托 `_liveness`）返回 `{"action": "extend"/kill, extension_index, extension_seconds, reason, evidence}`，extend 时 `timeout_extension` 事件落 run 文件 + `note_run_extension` 通知 STATE——本 SPEC 的轮次续期与其同构。
- WIP 锚点：`wip_checkpoint.py` 已有锚点 A（drain-preserve）/ B（transient-backoff），共用 `commit_wip_checkpoint(wt_path, spec, anchor, logger)` helper + `collapse_wip_commits` merge-back 塌缩——锚点 C 只需新增常量并在收口点调用 helper。
- usage 兜底：`session.py:72 _extract_usage_info(None)` 返回全零 dict；attempt 循环 catch 分支（runner.py:2222-2226）DEBUG 写「tokens counted as 0 (add-cost-observability)」。

约束：daemon 是长进程，改轮询环/attempt 循环必须保持既有终态事件次序不变（error 行是文件最后一行——`finally` 块既有注释钉点）；锚点 C 的调用点必须在「可证明 agent 不再写盘」之后（proc 终止 + 读线程 join 后），与锚点 A/B 同前提。

## Goals / Non-Goals

**Goals**

1. turn-limit 强杀前按封闭矩阵判定续期（有活性 extend、无活性 kill、封顶终止），每次续期留痕。
2. turn-limit 收口点接入 WIP 保全（锚点 C），零提交型 run 现场不丢。
3. 强杀路径消耗记账区分 unobserved 与 zero，日志不再写「counted as 0」。

**Non-Goals**

- 不改 `agents.max_turns` 默认值（400 维持）。
- 不改超时路径 D3 矩阵行为（两套续期计数相互独立）。
- 不做 prompt 注入轮次预算感知（agent 无法自数外部计数，弱模型遵循度差，评估无增量收益）。
- 不做消息级 usage 逐轮累加（inferaiapi 网关消息级 usage 全零，无可聚合数据源；本 SPEC 只修语义口径）。
- 不动 attempt 重试预算与瞬断判定（turn-limit 异常继续不携带 stderr_lines，防止误判 provider-transient——既有注释钉点保持）。

## Decisions

### D1: 锚点 C 调用点——finally 收口后、异常 raise 前，与超时路径共用判定

`turn_limit_error` 收口分支（runner.py:2926）在 `append_run_error` 之前插入：proc 已在轮询环 kill、读线程已 join（finally 语义保证）——此刻 worktree 静默可证明，调用 `self._wip_checkpoint_before_backoff(spec_name, wt_path)` 复用既有方法（其内部已处理载体有效性检查与失败降级，仅 anchor 参数固定为 `transient-backoff`——需将该 helper 的 anchor 参数化或新增 `ANCHOR_TURN_LIMIT` 变体调用 `commit_wip_checkpoint` 直接调用，取后者：helper 方法不动，收口分支直接调 `commit_wip_checkpoint(wt_path, spec, ANCHOR_TURN_LIMIT, logger)`，失败降级语义 helper 内建）。

备选：在轮询环 kill 前提交——否决：agent 尚在写盘（第 12 提交与 SIGKILL 同秒证明），违反锚点「静默可证明」前提，可能提交半写文件。

超时路径（`timeout_error`）同样接入锚点 C：两路径共用「强杀收口」事实，`_wip_checkpoint` 调用提取为私有方法 `_wip_checkpoint_on_forced_kill(spec_name, wt_path, anchor=ANCHOR_TURN_LIMIT)` 供两处复用。

### D2: 轮次续期矩阵——复用 D3 结构、独立计数、保守参数

新增 `_turn_limit_action(run_file, spec_name, run_id, turn_extensions_used, agent_type)` 判定方法，结构对齐 `_supervision_deadline_action`：

- **活性证据**（任一命中即 extend）：
  a) 分支活性——`git -C wt rev-list --count <baseline>..branch` 较上次判定有增量（首次以 run 起点为 baseline）；
  b) 流量活性——run 文件尾部窗口（如最近 60s）内有新 `tool_result` 事件（复用 latency 采样的 timestamp 解析）。
- **续期参数**：每次 extend 步长 = `max_turns` 的 25%（400→+100 轮）；封顶 = 2 次（即理论最大 600 轮）；配置常量落 `runner.py` 模块级（`TURN_EXTENSION_STEP_FRACTION = 0.25`、`TURN_EXTENSION_MAX = 2`），不进 config.yaml（框架生命周期内部治理参数，参照 AGENT_TERMINATE_GRACE_SECONDS 先例；后续有需求再暴露配置）。
- **留痕**：extend 时 run 文件追加 `{"type": "turn_extension", "extension": N, "turn_step": 100, "evidence": "<活性证据摘要 ≤400 字符>", "new_turn_cap": M}`；STATE 侧 `note_run_extension` 不复用（那是超时语义），turn 续期仅 run 文件留痕 + INFO 日志——避免 STATE 字段语义混淆。
- **判定时机**：轮询环把 `turn_count[0] >= current_turn_cap` 作为触发点（`current_turn_cap` 初始 = max_turns，extend 后累加步长），替换现 runner.py:2852 的硬条件。

备选：活性只看提交不看流量——否决：builtin 型任务验证期长时间无提交但 tool_result 持续产出（a1 的 38 次 sleep+探测就是活性），只看提交会误杀；只看流量不看提交——否决：卡死重试循环也有 tool_result（同错误反复），双证据合一才判活。

### D3: 续期计数与超时计数隔离

`extensions_used`（超时 D3）与新增 `turn_extensions_used` 是两个独立局部变量，各自封顶、互不读写。轮询环内两判定顺序保持：取消旗标 → 超时矩阵 → 轮次矩阵 → poll。`turn_extension` 与 `timeout_extension` 事件 type 不同，读侧（dashboard runEvents）天然分流，无需改前端（未知事件 type 既有容错）。

### D4: usage 口径——unobserved 标识而非改返回形状

`_extract_usage_info(None)` 的返回形状不变（全零 dict，调用方 12 处不动），新增 key `"unobserved": True`（result 为 None 时置位）。attempt 循环 catch 分支的 DEBUG 文案改写：

- 现状：`ended in error — tokens counted as 0 (add-cost-observability)`
- 改为：`ended in error — usage unobserved (no result terminal event; real consumption likely non-zero, add-cost-observability)`

STATE 累计侧 `_accumulate_token_usage` 收到 unobserved dict 时跳过累计（全零本就不增），但将 unobserved run 计入新的 DEBUG 计数留痕（供成本审计时区分「零消耗」与「未观测」）；不新增 STATE 字段（展示层不伪造原则：无可展示的真实数字就不展示）。

备选：返回 None 强制调用方分支——否决：12 处调用点全要改，收益仅为语义洁癖；加 key 向后兼容。

### D5: 锚点 C 与 terminal-nocommit-gate 的边界

`_check_terminal_no_commit_gate` 只在 exit 0 正常终态路径生效（runner.py:2391 处调用点），本 SPEC 的锚点 C 在异常收口路径（turn-limit/timeout 强杀），两路径互斥不重叠，gate 逻辑不动。锚点 C 产生的 `fenix(wip):` 提交进入分支后，若后续 attempt 成功收尾，既有 `collapse_wip_commits` 在 merge-back 前自动塌缩——零新增塌缩逻辑。

## Risks / Trade-offs

- [续期放大卡死 run 的墙钟] → 双活性证据 + 封顶 2 次 + 单次步长 25%，理论最大延长 = 200 轮；且无活性 run 一次都续不到。最坏墙钟增幅可控（400 轮 ≈ 51-84min 实测，200 轮 ≈ +26-42min，仅对真活性 run 发生）。
- [锚点 C 提交了 agent 正在写的半成品文件] → 调用点钉在 proc 终止 + 读线程 join 后（finally 语义），与锚点 A/B 同前提；即便纳入半写文件，后续 attempt resume 会重写该文件，WIP 语义本就是「保全优先于整洁」。
- [轮询环新增 git 子进程调用拖慢 1s 轮询周期] → rev-list 只在触发判定时执行（命中上限才跑），不在常规周期路径。
- [unobserved key 泄入展示层] → `_accumulate_token_usage` 只读固定四键（input/output/cache_*/cost），多余 key 自然忽略；展示层读同四键——无泄漏面。

## Migration Plan

单 commit 落地（fast-track）：新增常量 + 判定方法 + 两处收口点插入 + 文案修改 + 单测。回滚 = revert 单 commit，无状态迁移、无配置变更、无 run 文件格式破坏性变更（`turn_extension` 为新增事件 type，旧读侧容错）。

daemon 合并后须重启（内存旧码陷阱——fenixd-daemon-stale-code）。

## Open Questions

无——三起事故取证已闭合全部设计输入；续期步长/封顶取保守值（25%/2 次），后续按实测可调常量。
