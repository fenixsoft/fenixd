# verify-process-lifecycle 增量规格

## ADDED Requirements

### Requirement: 终态收割义务

agent run 进入任意终态（成功、失败、取消、frozen 早退、chain_exhausted、
日限 raise、未预期异常）时，runner MUST 对本 run 使用过且未被有意交接
（fast-track keep / repair 延迟 / keep_for_reuse）的每个 worktree 执行收割：
停止其 dev-server 注册条目并扫杀该 worktree 的游离进程。收割 MUST 幂等。

#### Scenario: frozen 早退收割
- **WHEN** run 在 frozen 早退路径退出且其 worktree 无 hand-off
- **THEN** 该 worktree 的 dev-server 注册条目被停止、游离进程被清扫

#### Scenario: 异常路径收割
- **WHEN** `_execute_agent` 内部抛出未预期异常穿出
- **THEN** finally 收割仍执行，无注册条目残留

#### Scenario: hand-off 豁免
- **WHEN** fast-track/keep 分支有意保留 worktree 供下轮复用
- **THEN** 终态收割不停止其 dev-server（由后续轮次接养或复用认领路径处理）

#### Scenario: 重复收割幂等
- **WHEN** 同一 worktree 的收割被执行两次（如 dispatch 层与 runner 层都触发）
- **THEN** 第二次为无害空操作，无异常

### Requirement: 进程组杀树

dev-server spawn MUST 使用 `start_new_session=True`（独立进程组）；停止
MUST 按 SIGTERM 进程组 → 等待 → SIGKILL 进程组 → 单进程兜底的顺序终止
整棵进程树，MUST NOT 只杀直接子进程。

#### Scenario: 孙进程一并终止
- **WHEN** dev-server 进程产生了自己的子进程（shell/npm 包装形态）
- **THEN** 停止后进程组内全部进程终止，无孙进程存活

#### Scenario: 不误伤 daemon
- **WHEN** 对 dev-server 执行 killpg
- **THEN** daemon 自身与其他 agent 进程（不同进程组）不受影响

### Requirement: 父子绑定自杀

dev-server 入口脚本（tests/v2/dev-server.mjs）MUST 周期轮询父进程存活
（`process.ppid === 1` 判定孤儿）并在成为孤儿后自行退出；MUST NOT 使用
PDEATHSIG（daemon 从 per-dispatch 线程 spawn，父线程死亡会误杀存活服务）。

#### Scenario: 父死后自灭
- **WHEN** daemon（父进程）被 kill -9，dev-server 存活
- **THEN** dev-server 在轮询间隔内自行退出，不依赖外部清扫

### Requirement: 周期清扫与豁免规则

daemon 主循环 MUST 以 ≤10 分钟间隔周期执行 dev-server 孤儿清扫（对齐启动
清扫逻辑）。清扫对"归属存活 attempt"的豁免判定 MUST 校验引用进程为 claude
进程（marker 锚定）；同 worktree 的两个孤儿 dev-server 互相引用 MUST NOT
构成有效豁免。

#### Scenario: 孤儿一个周期内回收
- **WHEN** dev-server 父进程已死且无存活 claude 引用
- **THEN** 下一个清扫周期内被回收，泄漏可见窗口 ≤ 一个周期

#### Scenario: 存活 claude 豁免
- **WHEN** worktree 存在存活的 claude 进程引用（在飞 run）
- **THEN** 该 worktree 的 dev-server 不被清扫

#### Scenario: 双孤儿互引不豁免（事故回归）
- **WHEN** 同 worktree 两个孤儿 dev-server 互为"存活引用"且无 claude 进程
- **THEN** 均被清扫（互引不构成豁免）

### Requirement: 端口分配与耗尽兜底

端口探测 MUST 在 bind 前设置 `SO_REUSEADDR`（TIME_WAIT 不再判占用）。
端口段耗尽时 MUST NOT 抛异常终止验证流程，MUST NOT 静默回退主树 8787
常驻实例——MUST 回退分配系统临时端口并留 WARNING 级留痕。

#### Scenario: TIME_WAIT 不假性占用
- **WHEN** 端口处于 TIME_WAIT 状态（无活动 listener）
- **THEN** 探测判定可用，立即 rebind 成功

#### Scenario: 耗尽回退临时端口
- **WHEN** 19000-19019 全被真实 listener 占用
- **THEN** 分配系统临时端口 + WARNING 留痕，验证照常在专用实例上进行

#### Scenario: 耗尽不静默回退主树
- **WHEN** 端口分配失败
- **THEN** 不出现"回退 8787 主树实例"的路径（污染形态封死）

### Requirement: 被测实例登记制

command 型被测实例（verify.yaml serve.kind=command 与 `_ensure_app_reachable`
兜底 spawn）MUST 在创建时向 `.fenix/verify-serving/servers.json` 登记
（pid/port/spec/worktree），stop 时移除。spec 推进 done/verified 时 MUST
同步 stop 登记服务、驱逐缓存条目并移除 serving worktree。daemon 启动与
周期清扫 MUST 按 /proc liveness 收割"无在飞 spec 但进程仍存活"的登记项。

#### Scenario: spec 终局驱逐
- **WHEN** spec 推进到 done/verified
- **THEN** 其登记的 command 服务被 stop、servers.json 条目移除、serving
  worktree 移除

#### Scenario: 启动收割登记孤儿
- **WHEN** daemon 启动发现 servers.json 中进程仍存活但属主 spec 不在飞
- **THEN** 收割进程并移除登记

### Requirement: repair 轮服务保障

`_v2_launch_for_worktree` MUST 具备幂等 ensure 语义：worktree 无存活注册
条目时 MUST 补启 dev-server。repair 复用载体轮 MUST 拥有可用 dev-server 与
BASE_URL 注入，MUST NOT 以空 env / 主树 8787 作为测试目标。

#### Scenario: repair 复用轮补启
- **WHEN** repair 轮复用载体 worktree 且注册表无该 worktree 条目
- **THEN** 自动补启 dev-server 并正常注入 BASE_URL

#### Scenario: repair 轮不打主树
- **WHEN** repair 轮执行 UI 验证
- **THEN** 请求落在该轮专属 dev-server 实例上，无任何请求落主树 8787

### Requirement: 游离进程清扫能力升级

worktree 游离进程清扫 MUST 在 cmdline 匹配外增加 `/proc/<pid>/cwd` 归属
匹配（覆盖 argv 不含 worktree 路径的进程），并 MUST 在 SIGTERM 宽限期后
对无响应进程补 SIGKILL。

#### Scenario: cwd 盲区覆盖
- **WHEN** 进程 cwd 位于 worktree 内但 argv 不含 worktree 路径（如 agent 经
  Bash 起的 npm run dev）
- **THEN** 该进程被识别并清扫

#### Scenario: SIGTERM 无视者兜底
- **WHEN** 游离进程忽略 SIGTERM
- **THEN** 宽限期后被 SIGKILL 终止，不残留
