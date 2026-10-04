# add-evolution-subagent-wait-ceiling

## Why

2026-10-03 自进化复核 run evo-1791048570 把每条条目的核查派给 3 个后台子代理后结束回合，Claude Code CLI 按 600 秒后台等待上限（CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS，缺省 600000ms）强杀仍在跑的子代理：主 run 以中期文案充当终局（CLI 侧 completed、退出码 0），产物 json 与 .parts 分片零落盘，既有抢救路径 _salvage_evolution_out 无从合并，框架「水位不推进」兜底只能整任务重跑（evo-1791049605），单次事件双倍消耗一个完整分析。重跑成功（subagent_stats started_in_background=3、completed=3、killed.system=0）纯属子代理恰在 600 秒内完成——条目量或核查时长再超 600 秒必复发。

## What Changes

1. evolution 车道注入 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0（无限等待后台任务）：在 core/agent_runner/maintenance_runs.py 的 run_evolution env_overrides 处按车道注入，不改 runner 全局默认（避免其他车道残留后台任务的 run 永不退出、烧满 run_timeout）。
2. agents/evolution.md 进化提示词加兜底约束：子代理 MUST 前台派发；收齐全部子代理结论前 MUST NOT 结束回合——env 注入失效或 CLI 行为变化时防全灭。
3. 失败归因增强：evolution 收尾契约缺失分支嗅探本 run 转录尾部的「Background tasks still running after 600s」stderr 行，命中则把该上限写进失败 reason，下轮诊断零成本。

## Impact

- Affected specs: 无（新增能力 evolution-subagent-wait-ceiling）
- Affected code:
  - core/agent_runner/maintenance_runs.py（env 注入 + 归因嗅探）
  - agents/evolution.md（提示词约束）
  - tests/test_evolution_bg_wait_ceiling.py（新增测试）

不改变水位探测与重派机制本身（evo-1791048570 的兜底行为正确）；不改变其他维护车道的 env 行为。