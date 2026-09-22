## Deliverables

```yaml
- path: core/verify_contract.py
  kind: modify
- path: core/pm_engine/verification/serving_reclaim.py
  kind: new
- path: fenixd.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_verify_contract.py
  kind: modify
- path: tests/test_main_tree_deps_provision.py
  kind: modify
- path: tests/test_dashboard_data.py
  kind: modify
- path: tests/test_system_settings_config.py
  kind: modify
- path: tests/test_characterization_giant_classes.py
  kind: modify
- path: tests/test_verify_serving_reclaim.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

> 说明：`.fenix/verify-serving/`（存量目录实际删除）与 `.fenix/todo.md`（人工
> 清理队列）为运行时文件，属 `reference`/人工步骤，不进本段；交付物守卫不校验
> `core/dashboard/static/dist/index.html`（前端构建产物，`reference`）。

## 1. 依赖供给默认值改版（D6）

- [x] 1.1 `core/verify_contract.py`：`DEFAULT_DEPS_MODE` 由 `"prefer-offline"` 改为 `"hardlink"`；核验 `resolve_deps_mode` 兜底返回该常量、`provision_worktree_node_modules`/`ensure_main_tree_deps` 默认参数随之生效；同步模块文档字符串中「默认」表述
- [x] 1.2 `.fenix/config.template.yaml`：在 `verify` 段（`static_scope` 之后）显式补 `deps_mode: hardlink` 并加注释说明两种模式与降级行为
- [x] 1.3 `core/dashboard/data/config_admin.py`：两处缺省字典（约 300/500 行）`{"verify": {"static_scope": "main", "deps_mode": "prefer-offline"}}` 的 `deps_mode` 同步为 `hardlink`
- [x] 1.4 `VerifyPanel.tsx`：`form.setFieldsValue` 缺省 `deps_mode` 改 `'hardlink'`；「（默认）」标注从 prefer-offline 选项移到 hardlink 选项；`dashboard.ts` 类型注释同步默认模式表述
- [x] 1.5 同步既有测试断言：`tests/test_verify_contract.py`（`resolve_deps_mode(None, None) == DEFAULT_DEPS_MODE` 等）、`tests/test_main_tree_deps_provision.py`、`tests/test_dashboard_data.py`、`tests/test_system_settings_config.py` 中因默认值/缺省字典变化而失配的断言。`tests/test_characterization_giant_classes.py:249/265` 已显式 `patch("core.verify_contract.resolve_deps_mode", return_value="prefer-offline")`，不受默认值变更影响，**无需改动**（若实测失配再同步）

## 2. 清扫器实现（D1/D2/D3/D5）

- [x] 2.1 新建 `core/pm_engine/verification/serving_reclaim.py`：实现 spec 名解析（`{spec}-{10 位时间戳}`，末段须恰 10 位数字；无法解析返回 None）与四类保留判据 helper（spec 存活于 `spec/changes/` 或 `spec/archive/*-<spec>` / `servers.json` 登记 `worktree` 字段——两侧 `Path.resolve()` 后全等，空串登记项不参与匹配 / `/proc` 活进程 argv或cwd 指向目录 / mtime 宽限期），所有 helper 异常时返回「保留」；宽限期用模块常量 `RECLAIM_GRACE_SECONDS = 600`（不新增配置键）
- [x] 2.2 在清扫器中实现目录回收执行：对判据判为无主的目录调用 `git worktree remove --force` + `git worktree prune`，单条目失败记 WARNING 并继续，幂等跳过已不存在目录，MUST NOT 触碰 `servers.json`/`servers.json.lock`/`contract_selfcheck.json`
- [x] 2.3 实现 `<spec>-boot.log` 回收：spec 名由文件名剥离 `-boot.log` 后缀得到（boot.log 名**不含时间戳**，不得复用 2.1 的目录名 `{spec}-{10 位时间戳}` 解析规则），按「spec 不在 changes/archive（`*-<spec>` 后缀匹配）且无在飞 run」判据删除，无法解析归属或属顶层状态文件（`contract_selfcheck.json`、`servers.json` 等）者保留
- [x] 2.4 导出单一入口 `reclaim_verify_serving(project_root, logger, is_spec_in_flight=None) -> dict`（返回 `{"reclaimed": [...], "kept": [...], "boot_logs_reclaimed": [...]}`）并输出含回收数量的日志

## 3. 触发点接线（D4）

- [x] 3.1 `fenixd.py`：新增 `_reclaim_verify_serving_tree(use_in_flight: bool = True)` 方法，构造 `is_spec_in_flight`（复用 `_is_spec_in_flight`）并调用 `reclaim_verify_serving`，try/except 包裹异常记 ERROR
- [x] 3.2 `fenixd.py`：daemon 启动序列中，在 `_sweep_verify_serving_registry(use_in_flight=False)`（约 438 行）之后追加 `self._reclaim_verify_serving_tree(use_in_flight=False)`
- [x] 3.3 `fenixd.py`：600s `orphan_clean_ts` 周期清扫节拍内，在既有 `_sweep_verify_serving_registry()` 之后追加 `self._reclaim_verify_serving_tree()`

## 4. 清扫开关（配置 + 界面）

- [x] 4.1 `core/verify_contract.py` 或 `fenixd.py`：读取 `verify.serving_reclaim.enabled`（缺省 `true`），为 `false` 时跳过清扫（`_reclaim_verify_serving_tree` 内早退），`.fenix/config.template.yaml` 的 `verify` 段补 `serving_reclaim: {enabled: true}` 及注释
- [x] 4.2 `VerifyPanel.tsx`：新增「serving 目录自动回收」开关（Switch，键 `verify.serving_reclaim.enabled`，缺省开）；`dashboard.ts` 类型同步该键；`config_admin.py` MUST 覆盖以下**全部**落点（漏任一处该键会被静默丢弃或读不到）：①缺省字典两处（约 300/500 行）②合并应用分支 `for vk in ("static_scope","deps_mode")`（约 725 行，需显式接 `serving_reclaim` 子键）③`write_config` 前置校验（约 893-911 行，布尔类型校验）④验证页受管键白名单 `_SYNC_PAGE_KEYS["verify"]`（约 1417 行）⑤`_SOURCE_KEYS`（来源标注）
- [x] 4.3 `fenixd.py` 接入开关读取（配置热更新路径按既有 `_maybe_reload_config` 语义生效）

## 5. 测试

- [x] 5.1 新建 `tests/test_verify_serving_reclaim.py`：判据矩阵单元测试——changes 存在保留 / archive 存在保留 / 登记在册保留 / 活进程保留 / 无法解析保留 / 6 位后缀 spec 名正确解析 / 三重皆无则回收
- [x] 5.2 同上文件：回收执行测试——git 命令调用（打桩）验证 `remove --force`+`prune`、单条目失败继续、重复清扫幂等
- [x] 5.3 同上文件：boot.log 回收测试——无主删除 / 存活保留 / 无法解析保留
- [x] 5.4 同上文件：`reclaim_verify_serving` 返回结构含 reclaimed/kept/boot_logs_reclaimed 且计数正确
- [x] 5.5 同上文件：开关为 `false` 时清扫早退（不调用 git、不删文件）

## 6. 收尾

- [x] 6.1 运行有界全量套件 `python3 bin/run_full_suite.py --timeout 3600`，修复因默认值改版/新模块引入的回归
- [x] 6.2 写 `.fenix-run-result.json`（含 `completed_tasks` 与各场景证据），并持久化场景集与结果到 `.fenix/verify-progress/fix-verify-serving-disk-reclaim/`
- [x] 6.3 存量清理留痕（`.fenix/todo.md`，运行时文件、非交付物）：条目须写明「存量主体为 18 个 spec 仍在册（changes/archive）目录的各 1.6G `node_modules`，按 D1 判据 1 不会被自动回收」，清理范围不得只限「spec 双双消失」的目录（现测仅 1 个），并按 fix-verify-cli-cwd-isolation 教训逐条核对后删除、勿用通配批量删
