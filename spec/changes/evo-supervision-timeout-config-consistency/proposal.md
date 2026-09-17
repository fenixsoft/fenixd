# Proposal: supervision-timeout-config-consistency

## Why

implementer 生效超时（agents.run_timeout_seconds=15000s）与 supervision absolute_max_seconds（14400s）配置不一致：操作者显式配置的 14400s 硬上限被静默抬升到 18600s（+1h10m 墙钟），总墙钟上限与配置意图脱钩（实测该长 run 由抬升后的 18600s 封顶终止，见 .fenix/logs/fenixd.log:15054「absolute_max_seconds cap reached (18600s, extensions_used=2)」——事故点是「上限被静默改写」而非「无硬截停」）。

fenixd.log 已现 5 条同文案 ERROR（09-15 两条 + 09-16 三条，行 13181/13218/14985/15018/15051，如 2026-09-16T08:32:50Z），且全部来自 liveness 运行时兜底：

> supervision absolute_max_seconds(14400s) 低于 生效超时 15000s + 续期总额 2×1800s = 18600s，按 18600s 兜底生效（agent_type=implementer）

现状两处口径并存、互不感知：

- config.py:1241 `effective_supervision_absolute_max_seconds`：用硬编码 `SUPERVISION_EXTENSION_SECONDS = 7200`（config.py:29，= 4×1800）⇒ 下限 15000 + 7200 = **22200s**；只做「告警 + 返回兜底值」，不做「对齐」（config.yaml:22=15000 / :27=14400 未对齐）。
- liveness.py:777-789：另手写 `run_timeout + max_extensions × extension_seconds` ⇒ 基础档 **18600s**（fast-track higher 档 `max_extensions += 2` ⇒ 22200s）。

配置漂移因此可长期存活：文件不改、ERROR 反复；且操作者把 run_timeout 提到 15000 后，file 里的 14400 硬上限在运行时永远无效。

## What Changes

- 统一下限口径：新增单一派生函数（config 校验层与 liveness 兜底层共用同一实现，删除两处手写常数）。运行时下限 = 生效 run_timeout（含 per-agent 覆盖）+ 实际续期预算 × extension_seconds（基础档 2×1800 ⇒ 18600s；fast-track higher 档 4×1800 ⇒ 22200s，保持现状数值不变）；配置校验层下限 MUST 取全部署最大可达值 = max(全局 run_timeout, 全部 timeout_overrides) + (max_extensions + 2) × extension_seconds = 15000 + 4×1800 = **22200s**（与既有 config.py:29 常量 7200、.fenix/config.template.yaml:108/258 的 16200 = 9000 + 4×1800 同口径，MUST NOT 下调该保守性）。
- 启动/热更新一致性校验：不一致时给出明确 ERROR + 修正建议（抬升 absolute_max，或下调 run_timeout 以保住 14400s 级硬上限）；默认自动对齐（内存生效 + 经既有配置写路径持久化）。
- 自动对齐被显式关闭时，不一致即 fail-fast 阻断（启动失败 / 热更新拒绝并保留旧值），杜绝漂移长期存活。

## 非目标

- 不改变监督运行时决策矩阵（续期/终止语义不变），不改变 liveness 各档位现行下限数值（18600s / 22200s）。
- 不强制调低 run_timeout（由配置方按任务面决定）。
- 不改 42 美元类历史 run 的追责/统计。
