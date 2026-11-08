# 派发前置 harness 可达性自检

<!-- knowledge: capability=dispatch-precheck rev=1
     sources=spec/changes/add-dispatch-precheck-true-fallback -->

车道派发的前置自检门：spawn 前探测 harness binary 可达性，不可达以显式归因短路该次派发并走 PATH 自愈闭环——不让确定性环境缺陷以裸 `FileNotFoundError` 形态进通用重试循环。

## 规则

- **派发前置自检**：车道派发装配段在 spawn 前按 `agent.harness` 选型解析可执行名，`shutil.which` 探测可达性（探测单源 `precheck_harness_executable`，派发短路与 daemon 启动自检共用）；不可达短路该次派发——不建 worktree、不起进程、不消耗 attempt 预算；可达零日志零噪音放行（which 为微秒级文件系统探测）。探测先于 adapter `check_health` 执行。
- **归因标记与升级信号豁免**：harness binary 缺失导致的失败携带显式归因标记 `[harness-cli-unavailable]`（协议层单源常量，与 `[model-chain-unavailable]` 同层同形；派发短路文案与 `DshAdapter.check_health`「未装」路径共用同一标记与文案，双口径合一）。该类失败 MUST NOT 计入 instant-fail-storm / repeated-failures 等按模型链语义设计的升级信号——归因不同，升级路径不同：CLI 缺失重试无意义、修复环境才有意义，升级路径为单条 actionable 告警 + 进程内去重。
- **daemon 启动自检**：启动序列对当前 harness 选型探测一次；不可达发单条 actionable 告警（含可执行名、当前 PATH 摘要、修复指引；binary 全基线目录未找到时附安装指引），run-once 旗标进程内去重；告警不阻塞 daemon 其余职能（周期扫描、监控照常）。可达时不播报。自检自身故障仅降级 WARNING，不击穿启动序列。
- **PATH 缺陷自愈闭环**：启动自检发现 binary 在基线安装目录（如 `~/.local/bin/<name>`）在场而进程 PATH 缺该目录、且 `.fenix/systemd.env` 在场时，自动把缺失目录幂等追加至 env 文件 PATH 行（原子写，重复启动不重复追加）并落 `restart_request`（JSON：reason/origin/date；已存在不重复写、不刷 mtime——supervisor 只判存在性），supervisor 消费重启后生效；binary 全基线目录未找到或 env 文件缺席时 MUST NOT 盲写 env，仅发告警（盲写门）。

## 关键行为

不可达失败链：派发装配段探测命中 → 派发短路（无 spawn 进程）→ 失败证据带 `[harness-cli-unavailable]` 标记与「检查 PATH / systemd EnvironmentFile」指引 → 豁免秒挂/重复失败升级计数；启动自检告警在位（描述 agent 车道不可用直至 PATH 修复）；自愈触发时 env 追加 + restart_request 落盘，supervisor 重启后 PATH 追加生效、自检通过。基线目录判定与 systemd env 捕获侧共用单源（见 [systemd env 捕获 PATH 卫生](../daemon-runtime/systemd-env-path-hygiene.md)）。

## 代码锚点

- 主实现：`fenixd.py`（启动自检与 PATH 自愈、restart_request 落盘）、`core/agent_runner/runner.py`（派发装配段前置自检短路）
- 单源符号：`core/agent_runner/harness/__init__.py:precheck_harness_executable`、`core/agent_runner/harness/__init__.py:harness_unavailable_message`、`core/agent_runner/harness/protocol.py:HARNESS_CLI_UNAVAILABLE_MARKER`
- 消费方：`core/agent_runner/harness/dsh_adapter.py`（check_health 不可达路径同口径归因）、`core/admin_monitor.py`（秒挂/重复失败升级信号按标记豁免）
- 守卫测试：`tests/test_dispatch_precheck.py`（短路归因、可达零噪音、启动告警去重、升级豁免不计数、自愈幂等与盲写门）

## 溯源

- 2026-11-08 add-dispatch-precheck-true-fallback（spec/changes/add-dispatch-precheck-true-fallback/） — 新建本能力：派发前置可达性自检短路、`[harness-cli-unavailable]` 归因标记与升级信号豁免（归因不同升级路径不同）、daemon 启动自检告警（进程内去重不阻塞）、PATH 缺陷自愈闭环（幂等追加 + restart_request、盲写门）
