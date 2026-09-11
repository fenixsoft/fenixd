# spec-verify-preflight-gate

## ADDED Requirements

### Requirement: serve 命令入口存在性预检（spawn 前 fail-fast）

`serve.kind=command` 的验证链路（serving worktree 与主树兜底两条路径）在启动 serve.cmd 进程前，框架 SHALL 机械解析命令中的脚本入口路径并校验其存在性：

- 解析范围：可执行名为 `node`（含 npx/tsx/bun 等脚本型运行时）时，第一个非 flag 参数视为入口路径，按 cmd 的 cwd 解析为绝对路径。
- 入口文件存在 → 放行启动（行为与现状一致）。
- 入口文件不存在 → MUST NOT spawn、MUST NOT 执行任何验证场景；验证链路立即失败，错误信息 MUST 含缺失路径全文与同目录下确定性候选（如同名 `.js` 存在时提示），并产生 `verify_contract_missing` 信号（description 注明「入口存在性预检失败」）呼叫 Administrator。
- 无法解析出入口路径（如管道、`&&` 复合命令、shell 内建）→ 跳过预检放行（保守不拦截，零误杀）。

#### Scenario: 入口指向不存在文件时场景零执行

- **WHEN** 契约 `serve.cmd: node dist/server.js` 且 `dist/server.js` 不存在
- **THEN** 不启动任何进程，验证以「入口存在性预检失败: dist/server.js 不存在（候选: dist/server/index.js 存在）」失败，产生 verify_contract_missing 信号，report.json 不产生、场景执行数为 0

#### Scenario: 入口存在时预检零开销放行

- **WHEN** 契约 serve.cmd 指向的入口文件存在
- **THEN** 预检通过，实例照常启动，验证行为与现状逐字节一致

#### Scenario: 复合命令保守跳过

- **WHEN** serve.cmd 为 `npm run build && node dist/server.js`（`&&` 复合）或无法识别运行时形态
- **THEN** 预检跳过，走既有启动与探活路径，不产生新失败类型

### Requirement: 契约消费期轻量自证（mtime 变化后首验轮）

验证管线消费契约前，框架 SHALL 按 `.fenix/verify.yaml` 的 mtime 判定是否执行轻量自证：契约 mtime 晚于上次自证记录（per-project 持久化于 `.fenix/verify-serving/contract_selfcheck.json`）时执行，否则跳过。轻量自证内容：

- serve 段合法性（kind 枚举、static 模式 root 存在、command 模式 cmd 非空）；
- ready 探针鉴别力自检（复用 `probe_ready` 既有实现）；
- MUST NOT 重复执行 prepare 构建（构建耗时与供给属 `add-main-tree-deps-provision` 职权）。

自证失败 → MUST 按契约错误处理（产生 `verify_contract_missing` 信号 + 验证失败），不得进入场景执行；自证通过 → 记录 mtime 后放行，后续轮次零开销。

#### Scenario: 契约修改后首轮触发自证

- **WHEN** admin 修正 verify.yaml（mtime 更新）后下一轮验证启动
- **THEN** 执行轻量自证，serve/ready 段检查通过后记录新 mtime 并放行

#### Scenario: 契约未变时后续轮次零开销

- **WHEN** 连续多轮验证且 verify.yaml mtime 未变
- **THEN** 仅首轮自证，后续轮跳过（读 selfcheck 记录即放行）

#### Scenario: 自证失败阻断场景执行

- **WHEN** 轻量自证发现 serve.root 指向不存在目录（static 模式）
- **THEN** 产生 verify_contract_missing 信号，验证失败，场景执行数为 0

### Requirement: 兜底 spawn 错误捕获落盘

`_ensure_app_reachable` 的兜底 spawn（commands.start / serve.cmd 主树路径）SHALL 将子进程 stderr 捕获至 `.fenix/verify-serving/<spec>-boot.log`（覆盖写），替代现 `stdout=DEVNULL stderr=DEVNULL`；探活最终失败时，blocked 告警的 error/evidence SHALL 附 boot.log 尾部（≤2KB）——`Cannot find module` 类启动即死错误对 admin 直接可读。

#### Scenario: 启动即死错误进入告警证据

- **WHEN** 兜底 spawn 的命令因模块缺失立即退出，探活 30s 超时
- **THEN** blocked 告警 evidence 含 boot.log 尾部原文（含 Cannot find module 行）

#### Scenario: 正常启动时 boot.log 无消费方影响

- **WHEN** 实例正常启动且验证全绿
- **THEN** boot.log 照常落盘（含服务 stdout/stderr），不影响验证判定
