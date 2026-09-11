# Proposal: add-main-tree-deps-provision

## Why

2026-09-10 fenix-server `add-ssh-foundation` 验证 prepare 失败（`tsc: not found`，exit 127），16 场景全部 connection_failed，spec 阻塞第 1 轮，需 admin 手动 `npm ci`（154 packages）后重验，浪费 1 轮验证 + 1 次 admin 处置。

根因（框架覆盖面缺口）：依赖供给机制 `provision_worktree_node_modules`（verify_contract.py:703，deps_mode 双模式）只覆盖两条 **worktree 路径**（实现 worktree 创建 `worktree_manager.py:271-289`、serving worktree `verification.py:438`），而 `verify.static_scope=main`（**默认值**）的主树路径在 `verification.py:745` / `verification.py:699` 裸跑 `run_prepare_steps(contract, project_root)`——零供给、零预检。被管项目主树只被 merge-back 写入、无人手工 `npm install`，node_modules 永不存在 → 首次验证必踩。`worktree_manager.py:2420` `_run_dist_build`（merge 后主树重建 dist）是同根因第二受害点。

## What Changes

主树路径执行契约 prepare 前，对 prepare 步骤涉及的子目录（cwd 集合，缺省 `.`）复用既有供给逻辑：检测「有 package.json 且缺 node_modules」→ 按 deps_mode（prefer-offline/hardlink，`resolve_deps_mode` 同源解析）预装依赖，再执行 prepare。覆盖三处主树裸跑点：

1. `core/pm_engine/verification.py` `_ensure_app_reachable` 纯 cli 场景集主树 prepare（L699 附近）
2. `core/pm_engine/verification.py` `_ensure_app_reachable` 主树作用域 prepare（L745 附近，本次事故路径）
3. `core/worktree_manager.py` `_run_dist_build` 主树重建前的 prepare

## Capabilities

- main-tree-deps-provision：主树 prepare 前依赖预检与预装（复用 deps_mode 供给，best-effort 不阻塞派发）

## Impact

- 代码：`core/pm_engine/verification.py`（2 处）、`core/worktree_manager.py`（1 处）、`core/verify_contract.py`（新增主树供给入口，纯增不改既有函数语义）
- 测试：`tests/test_verify_contract.py`（或新增 `tests/test_main_tree_deps_provision.py`）
- 无 UI 变更、无配置迁移（deps_mode/static_scope 配置既有，不动）
- 行为影响：主树缺 node_modules 时验证/重建前自动多一次 npm 安装（秒级，走用户级缓存）；已安装时零开销（目录存在即跳过）
