# main-tree-deps-provision 规范

## ADDED Requirements

### Requirement: 主树 prepare 前依赖预检与预装

验证链路与 merge 后重建在主树执行契约 prepare 前，MUST 对 prepare 步骤涉及的子目录集合（各步骤 `cwd`，缺省 `.`）执行依赖预检：目录含 `package.json` 且缺 `node_modules` 时，按 deps_mode 解析结果预装依赖（主树自装一律走 prefer-offline 安装：`npm ci --prefer-offline --no-audit --no-fund`，失败回退 `npm install --prefer-offline --no-audit --no-fund`）。

#### Scenario: 主树缺 node_modules 时 prepare 前自动安装

- **WHEN** 主树项目根含 package.json 但无 node_modules，且契约 prepare 非空
- **THEN** 执行 prepare 步骤前自动运行依赖安装（prefer-offline 模式）
- **AND** 安装成功后 prepare 正常执行，`tsc: not found` 类 exit 127 环境阻塞不再发生

#### Scenario: 主树已安装时零开销幂等跳过

- **WHEN** 目标子目录 node_modules 已存在
- **THEN** 不运行任何安装命令，直接执行 prepare
- **AND** 预检本身不产生可感知延迟

#### Scenario: 目录无 package.json 时跳过

- **WHEN** prepare 步骤 cwd 指向的子目录不含 package.json
- **THEN** 该目录跳过预装，不报错

#### Scenario: 预装失败不短路交 prepare 报错

- **WHEN** 预装命令失败（如网络故障、npm 不可用）
- **THEN** 记 WARNING 日志后继续执行 prepare
- **AND** prepare 因缺依赖失败时走既有「prepare 失败＝验证环境错误」门禁链路，不新增第二套失败通道

#### Scenario: 供给动作与结果留日志

- **WHEN** 预装执行（无论成功失败）
- **THEN** 记录日志含目标目录与结果（成功 INFO、失败 WARNING 含 stderr 尾部），admin 可从日志定位

### Requirement: 三处主树裸跑点全部接入预装

契约 prepare 在主树执行的全部三处调用点 MUST 在执行前接入依赖预装，覆盖面不留缺口：

#### Scenario: 验证可达性纯 cli 场景集路径

- **WHEN** 场景集为纯 cli（无实例形态），契约 prepare 在主树执行
- **THEN** 执行前完成依赖预装

#### Scenario: 验证可达性主树作用域路径

- **WHEN** `verify.static_scope=main`（默认）且场景集含 web/api 场景，契约 prepare 在主树执行
- **THEN** 执行前完成依赖预装

#### Scenario: merge 后主树 dist 重建路径

- **WHEN** merge-back 后 `_run_dist_build` 按契约 prepare 重建主树产物
- **THEN** 执行前完成依赖预装

#### Scenario: worktree 路径行为不变

- **WHEN** serving worktree / 实现 worktree 路径执行供给
- **THEN** 沿用既有 `provision_worktree_node_modules`（hardlink 源=主树语义不变），本次改动不影响其行为
