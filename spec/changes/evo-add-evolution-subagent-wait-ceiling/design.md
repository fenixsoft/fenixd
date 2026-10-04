# add-evolution-subagent-wait-ceiling 设计

## Context

自进化复核（agents/evolution.md）强制「逐条子代理」核查（:25、:212）。Claude Code CLI 对未显式指定的 Task 子代理默认转后台；主 run 结束回合后，CLI 等待后台任务至多 600 秒（CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS，ms），超时强杀。evo-1791048570 因此产物零落盘（run_metrics 中 tool_uses 无 Write），整任务重跑双倍消耗；重跑 evo-1791049605 的子代理恰在时限内完成（killed.system=0）而侥幸成功。

## Goals / Non-Goals

- Goals：evolution 车道子代理核查不受 600 秒上限击杀；提示词层双保险；上限击杀发生时失败归因自解释。
- Non-Goals：不改水位探测/重派机制；不改其他车道 env；不做 run 内断点续跑的通用框架（提示词层的「分片即时落盘」已由本 run 工作流自身满足，见契约分片写入步骤）。

## Decisions

### D1：车道级注入，不动全局
注入点选 core/agent_runner/maintenance_runs.py:964 附近 run_evolution 的 env_overrides 组装处（该 dict 恒传入 _run_claude，runner.py:5036-5043 会 update 进 env），与既有车道内注入先例同型（CLAUDE_CODE_ENABLE_TODO_TOOLS=1 在 runner.py:5063 为全局硬注入，provider.env 为配置驱动）。不放 runner.py:5063 全局位的原因：其他车道若残留后台任务，等待上限归零会让 run 永不主动退出、烧满 run_timeout。

### D2：同构车道评估而非盲改
评估范围澄清（评审实测核对 2026-10-05）：run_code_review 属「派子代理等汇总」型（agents/code-review.md:28-36 明确派子代理并行审查，且已另有「禁 async 等待收工」守卫与「谁审谁写」分片直写纪律兜底）；run_self_review 的模板（agents/self-review.md）未含子代理派发，列作评估对照项而非同型车道。评估以证据为准（模板是否含派发、既有转录有无后台派发与「Background tasks still running」stderr 签名），不要求新派真实 run；「注入/不注入」的决策与理由以注释留痕；默认不注入，避免改变未发生问题的车道行为。

### D3：归因嗅探挂在契约缺失分支
CLI 侧退出码为 0（terminal_reason=completed），失败走 read_contract 的 ContractError 路径（core/evolution.py:2036-2038 抛出、maintenance_runs.py:1022-1031 置 success=False），而非 _run_claude 异常路径——嗅探必须挂在 maintenance_runs.py 收尾段：置失败前读本 run 转录（.fenix/runs/ 下 `{run_id}.jsonl`，与 runner.py:3734 的转录定位同款）的全部 `type: stderr` 行（该行格式为 `{"type": "stderr", "line": ...}`，整 run 稀疏——evo-1791134863 实测仅 1 条，全扫成本可忽略），匹配「Background tasks still running after 600s」则把「CLI 后台等待 600 秒上限击杀（CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS），子代理半成品随 run 作废」追加进 reason；该 reason 经现有 _evolution_warn/ERROR 日志路径（fenixd.py:4337-4340）直出，无需改 fenixd.py。转录不可读时静默跳过嗅探，不影响原失败路径。嗅探 MUST 只扫 `type: stderr` 行、MUST NOT 全文件 grep：签名文本会以引用形态大量出现在 assistant/user 记录里（evo-1791134863 复核含 600s 条目的 todo 时实测 19 处引用 vs 真 stderr 行 1 条），全文件 grep 会把引用误判为击杀。嗅探实现为模块级辅助函数（与 `_salvage_evolution_out` 同型），供任务 4.2 不经完整 run_evolution 装配直接单测。

### D4：提示词约束措辞
agents/evolution.md「执行模式」节（:23-35 区域）追加：子代理 MUST 前台派发（等待结论返回后再继续）；收齐全部结论前 MUST NOT 结束回合；每条分片写完立即并入（与现行分片写入步骤一致）。此为 env 失效时的兜底，与 D1 互为冗余。

## Risks / Trade-offs

- 无限等待 + 子代理真挂死：run 将由既有 run_timeout 兜底杀死，与现状（600 秒击杀后重跑）相比仍是净收益（重跑同样烧 run_timeout 预算且双倍消耗）。
- CLI 变量改名/移除：D3 归因签名随 stderr 文案漂移失效——签名匹配做大小写不敏感的子串匹配即可，失效时退回现状文案，无副作用。

## Migration Plan

单 commit 落地三处（env 注入、模板约束、归因嗅探）+ 测试；无需数据迁移，重启 daemon 后生效。

## Open Questions

- 无。