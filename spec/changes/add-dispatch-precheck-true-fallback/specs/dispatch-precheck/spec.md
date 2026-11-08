# dispatch-precheck 规范

## ADDED Requirements

### Requirement: 派发前置 harness 可达性自检

系统 SHALL 在车道派发 spawn 前探测 harness binary 可达性（按 `agent.harness` 选型解析可执行名，`shutil.which` 探测），且在 daemon 启动序列完成一次全角色自检；不可达时 MUST NOT 让 run 以裸 `FileNotFoundError` 形态失败后进入通用重试循环，而 SHALL 以显式归因短路该次派发。

#### Scenario: CLI 不在 PATH 时派发被短路并归因

- **WHEN** harness=claude 且 daemon 进程 PATH 中无 `claude` 可执行文件，车道发起派发
- **THEN** 派发被前置自检短路，不产生 spawn 进程；run/信号归因带 `harness-cli-unavailable` 标记，文案含可执行名与「检查 PATH / systemd EnvironmentFile」指引

#### Scenario: CLI 可达时自检零开销放行

- **WHEN** harness binary 可达（`shutil.which` 命中）
- **THEN** 派发流程与自检引入前完全一致，无额外日志噪音（启动自检通过态不重复播报）

#### Scenario: daemon 启动自检发现不可达发一条告警

- **WHEN** daemon 启动序列自检发现当前 harness binary 不可达
- **THEN** 发一条 actionable 告警（含可执行名、当前 PATH 摘要、修复指引），进程内去重；告警不阻塞 daemon 其余职能（周期扫描、监控等照常）

### Requirement: harness 不可达失败归因标记

harness binary 缺失导致的失败 SHALL 携带显式归因标记 `[harness-cli-unavailable]`（与既有 `[model-chain-unavailable]` 同层同形），且该类失败 MUST NOT 计入「秒挂」「重复失败」等按模型链语义设计的升级信号——归因不同，升级路径不同。

#### Scenario: 归因标记与升级信号豁免

- **WHEN** 派发因 harness binary 不可达失败
- **THEN** 失败证据含 `[harness-cli-unavailable]` 标记与修复指引；该失败不计入 instant-fail-storm / repeated-failures 计数，不触发对应告警

### Requirement: PATH 缺陷自愈闭环

daemon 启动自检发现 harness binary 在已知安装目录（如 `~/.local/bin/<name>`）存在而 PATH 缺该目录时，SHALL 自动把缺失目录追加至 `.fenix/systemd.env` 的 PATH 行并落 `restart_request` 信号，由 supervisor 消费重启后生效；目录下未找到 binary 时 MUST NOT 盲写 env。

#### Scenario: 自愈补目录并请求重启

- **WHEN** 启动自检发现 `~/.local/bin/claude` 存在、进程 PATH 不含 `~/.local/bin`、`.fenix/systemd.env` 在场
- **THEN** env 文件 PATH 行追加该目录（幂等，重复启动不重复追加），落 `restart_request`（JSON：reason/origin/date），日志留痕；supervisor 重启后 daemon PATH 含该目录、自检通过

#### Scenario: binary 不存在时不盲写

- **WHEN** 全常见安装目录均未找到 harness binary
- **THEN** 不修改 `.fenix/systemd.env`，仅发 actionable 告警（含安装指引）
