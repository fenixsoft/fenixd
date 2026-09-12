# Proposal: add-bug-repair-mode-config

## Why

bug-found 处置的修复方式（原地打回 vs 派生 fix-* 子 SPEC）目前由 SPEC 名称前缀分流（`_is_fix_spec`：`startswith("fix-")`）。该豁免分支本意为让存量 fix 链自然终态，但人工立项的 SPEC 只要取名带 `fix-` 前缀就会被误分类进 legacy 通道继续派生子 fix（fix-fix-daemon-lifecycle-races 事故 2026-09-06）。存量 fix 链即将自然收敛完毕，分流依据应从「命名约定」改为显式配置，消除名称误伤，同时保留派生模式作为可配置选项。

## What Changes

- **新增配置参数 `admin.bug_repair_mode`**：控制验证失败（bug-found）后真实产品缺陷的修复方式。取值 `inplace`（原地打回，默认）或 `derive`（派生 fix-* 子 SPEC）。未配置时缺省 `inplace`。
- **名称前缀分流退役**：`core/pm_engine/family.py` `_do_spec_bug_found` 不再以 `_is_fix_spec`（名称前缀）决定修复方式；inplace 模式下任何 SPEC（含 fix-* 名字）验证失败一律原地打回。
- **derive 模式语义**：配置为 `derive` 时，bug-found 按既有派生逻辑创建/复用 fix-* 子 SPEC（`_resolve_fix_spec_name`、守卫一去重、族谱收敛 governor 全部保留生效）。
- **闭环保留**：「fix-* SPEC 完成 → 父 SPEC 自动重验」闭环（`_on_spec_done`）保留，不随名称分流退役删除——derive 模式下它是活代码；inplace 模式下无新派生，随在飞链终态自然沉寂。
- **存量链兼容**：在飞 fix 链（fix-fix-daemon-lifecycle-races）不受影响，自然终态；配置热切换无特殊处理——切换后下一次 bug-found 按新模式处置。
- **配置全链落地**：config 校验护栏 + `get_admin_config` 缺省值 + 设置读取合并白名单 + Dashboard 系统页签 UI + TS 类型，五处同步（参考 agents.verify_redo_budget 样板，防持久化缺失复发）。

## Capabilities

### New Capabilities

- `bug-repair-mode-config`: `admin.bug_repair_mode` 配置能力——参数定义、取值校验、缺省语义（未配置 = inplace）、Dashboard 系统页签展示与修改、热更新生效。

### Modified Capabilities

- `inplace-bug-repair`: bug-found 处置的修复方式分流依据由「SPEC 名称前缀」改为「`admin.bug_repair_mode` 配置」；原地打回的行为语义（计数器、任务注入、升级闸门）不变；新增 derive 模式分支描述。

## Impact

- **代码**：`core/config.py`（admin 段 validate + `get_admin_config`）、`core/pm_engine/family.py`（`_do_spec_bug_found` 分流改造）、`core/dashboard/static/src/pages/settings/components/SystemPanel.tsx`（系统页签 UI）、`core/dashboard/static/src/services/dashboard.ts`（TS 类型）、设置读取合并白名单
- **行为**：验证失败修复方式可配置；默认行为与现行 inplace 路径一致；fix-* 命名的 SPEC 不再被误派生子 fix
- **风险**：derive 模式复活族谱爆炸（由既有族谱收敛 governor 与守卫一拦截）；模式切换瞬间的在飞链语义（自然终态，无特殊处理）
