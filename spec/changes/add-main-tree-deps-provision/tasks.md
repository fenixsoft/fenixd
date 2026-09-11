# Tasks: add-main-tree-deps-provision

## Deliverables

```yaml
- path: core/verify_contract.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/worktree_manager.py
  kind: modify
- path: tests/test_main_tree_deps_provision.py
  kind: new
```

## 1. 主树供给入口

- [x] 1.1 在 `core/verify_contract.py` 新增 `ensure_main_tree_deps(project_root, sub_dirs, mode, logger)`：逐子目录预检（package.json 存在 + node_modules 缺失才装）、主树自装一律 prefer-offline（`npm ci --prefer-offline --no-audit --no-fund` 失败回退 `npm install --prefer-offline --no-audit --no-fund`，900s 超时）、成功 INFO/失败 WARNING 留日志、返回已装目录列表、不抛异常。不改造 `provision_worktree_node_modules` 既有语义。

## 2. 三处主树裸跑点接入

- [x] 2.1 `core/pm_engine/verification.py` 纯 cli 场景集主树 prepare 路径（`_ensure_app_reachable` 内 `run_prepare_steps(contract, self._pm.project_root)` 纯 cli 分支）：执行前按 prepare cwd 集合调用 `ensure_main_tree_deps`。
- [x] 2.2 `core/pm_engine/verification.py` 主树作用域路径（同函数 `contract.prepare and not wt_scope` 分支）：执行前同样接入 `ensure_main_tree_deps`。
- [x] 2.3 `core/worktree_manager.py` `_run_dist_build` 契约分支：`run_prepare_steps` 前接入 `ensure_main_tree_deps`（注意该方法无 pm 配置通道，mode 用 `read_config_deps_mode` + `resolve_deps_mode` 同源解析）。

## 3. 测试与收尾

- [x] 3.1 新增 `tests/test_main_tree_deps_provision.py`：覆盖「缺 node_modules 触发安装（mock subprocess）」「已存在跳过零调用」「无 package.json 跳过」「安装失败记 warning 不抛」「三处调用点在 contract.prepare 存在时被调用（patch 断言）」。
- [x] 3.2 全量回归 `pytest tests/test_verify_contract.py tests/test_main_tree_deps_provision.py tests/test_pm_verification.py` 通过，既有供给测试零破坏。
