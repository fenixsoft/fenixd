# Proposal: supervision-timeout-config-consistency

## Why

implementer 生效超时（agents.run_timeout_seconds=15000s）与 supervision absolute_max_seconds（14400s）配置不一致，监督上限兜底到 18600s（5h10m），监督无法先于墙钟终止长 run。fenixd.log 已现 5 条同文案 ERROR（09-15 两条 + 09-16 三条，如 2026-09-16T08:32:50Z）。现状兜底（config.py:1241 effective_supervision_absolute_max_seconds）只做「告警 + 返回兜底值」，不做「对齐」，且 liveness.py 兜底口径与 config.py 口径不一（22200 vs 18600），配置漂移可长期存活；与 42 美元单 run、900 轮 turn 耗尽无硬截停直接相关。

## What Changes

- 统一下限口径：supervision absolute_max 下限 = 生效超时 + max_extensions × extension_seconds（单一实现，config.py 与 liveness.py 两处调用同一函数）。
- 启动/热更新一致性校验：不一致时给出明确 ERROR + 修正建议（抬高 absolute_max 或下调 run_timeout），可选自动对齐（抬升并持久化）。
- 启动一致性校验不一致即阻断（fail-fast）而非静默兜底，杜绝漂移长期存活。

## 非目标

- 不改变监督运行时决策矩阵（续期/终止语义不变）。
- 不强制调低 run_timeout（由配置方按任务面决定）。
- 不改 42 美元类历史 run 的追责/统计。