## Why

`.fenix/verify-serving/` 目录实测占用 **30G**（19 个 serving worktree × 每个 1.6G），
磁盘 `/` 已用 183G/231G（84%）。两个独立成因叠加：

1. **默认依赖供给模式选了最占空间的一种**：`verify.deps_mode` 代码默认
   `prefer-offline`，每建一个 serving worktree 就 `npm ci` 实装一份
   `core/dashboard/static/node_modules`（1.6G）。实测每个 worktree 的
   `node_modules` inode 互不相同、link count=1，即**真拷贝而非硬链接**；
   剥离 `node_modules` 后 19 个 worktree 合计仅 461M（24M/个）。既有的
   `hardlink` 模式（`os.link` 秒级共享 inode，不占双倍空间）未被默认启用。

2. **serving worktree 目录没有生命周期回收**：现有回收入口
   `_evict_spec_serving`（`core/pm_engine/verification/serving.py`）只在
   **spec 转 done 事件**触发，且依赖**仅存内存**的 `_contract_static_servers`
   缓存取 `wt_path`。daemon 重启后缓存清空、或 spec 未经 done（archive/手动
   清理/状态回退），`wt_path` 线索即丢失 —— 目录永久残留。实测 19 个中 15 个
   对应 spec 已从 `spec/changes` 与 `spec/archive` **双双消失**，确定无主。
   `serving_registry.sweep` 只收割**进程与登记项**，不触碰目录本身。

两条成因可独立治理：默认值改 `hardlink` 把单份占用从 1.6G 降到 ~24M，
生命周期清扫负责回收已被放弃的 worktree 与 boot.log。

## What Changes

- **`verify.deps_mode` 代码默认值 `prefer-offline` → `hardlink`**（含
  `DEFAULT_DEPS_MODE` 常量、`config.template.yaml` 模板补该键、Dashboard
  `VerifyPanel` 默认选中项与「默认」标注、`config_admin.py` 缺省字典、
  `dashboard.ts` 类型注释、相关测试断言同步）。**BREAKING**（对依赖默认
  `prefer-offline` 语义的外部预期；主树无 `node_modules` 时仍自动降级）。
- **新增 verify-serving 目录生命周期清扫**：新增保留集判定与清扫执行器，
  对 `.fenix/verify-serving/` 下每个 `<spec>-<ts>` 目录判定是否保留：
  - 保留：目录名解析出的 spec 存在于 `spec/changes/` 或 `spec/archive/`；
  - 保留：目录路径出现在 `servers.json` 登记的 `worktree` 字段中；
  - 保留：目录内有活进程（扫描进程表 argv/cwd 指向该目录）；
  - 三者皆不满足 → `git worktree remove --force` + `git worktree prune`。
- **清扫触发点**：daemon 启动时一次性 reconcile（覆盖 daemon 死机期间累积
  的孤儿）+ 复用既有 600s 周期 orphan 清扫节拍（覆盖长期运行中的孤儿）。
- **boot.log 回收**：按与目录相同的「无主」判据回收到期 `<spec>-boot.log`
  （对应 spec 已不在 changes/archive 且无在飞 run）。
- **人工清理存量**：当前 30G 存量不写成任务（工作树隔离、主树只读），
  登记 `.fenix/todo.md` 由人工执行一次。

## Capabilities

### New Capabilities

- `verify-serving-reclaim`: `.fenix/verify-serving/` 目录与 `<spec>-boot.log`
  的生命周期回收 —— 保留集判定（spec 存活 / servers.json 登记 / 活进程）、
  清扫执行语义、触发点与幂等性。
- `verify-deps-provision-default`: 验证 worktree 依赖供给的默认模式语义
  —— 代码默认 `hardlink`、降级行为、配置解析优先级与界面默认标注一致性。

### Modified Capabilities

<!-- 无：verify-process-lifecycle（进程与本目录登记收割）已归档，本次新增目录
     维度的清扫能力，不修改其 Requirement。 -->

## Impact

- **代码**：`core/verify_contract.py`（默认值常量）、`core/pm_engine/
  verification/serving.py`（新增清扫执行器）、`fenixd.py`（启动 reconcile +
  周期清扫接线）、`core/serving_registry.py`（如复用登记读取）、
  `core/dashboard/data/config_admin.py`（缺省字典）。
- **前端**：`core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx`
  （默认选中项与标注）、`core/dashboard/static/src/services/dashboard.ts`
  （类型注释）。
- **配置**：`.fenix/config.template.yaml`（补 `verify.deps_mode: hardlink`）。
- **测试**：`tests/test_verify_contract.py`、`tests/test_main_tree_deps_provision.py`、
  `tests/test_dashboard_data.py`、`tests/test_system_settings_config.py`、
  `tests/test_characterization_giant_classes.py`（断言同步）。
- **运行时**：`.fenix/verify-serving/`（gitignored，非仓库交付物）；存量 30G
  由人工在主树清理一次。
- **风险**：清扫为破坏性删除，误删在飞 worktree 会当场毁掉正在跑的验证。
  必须 fail-safe：判定证据不足一律保留。
