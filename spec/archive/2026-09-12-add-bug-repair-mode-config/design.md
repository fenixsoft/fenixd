# Design: add-bug-repair-mode-config

## Context

bug-found 处置入口在 `core/pm_engine/family.py` 的 `_do_spec_bug_found`：开头以 `_is_fix_spec(spec_name)`（`name.startswith("fix-")`）分流——fix-* 名字走 `_do_legacy_fix_spec_bug_found` 派生子 fix，其余走原地打回（`_verify_fail_rounds` 计数 + `## 验证修复` 任务注入 + 轮数 3 冻结升级）。该名称豁免本意为存量 fix 链自然终态，但人工立项的 fix-* 名字 SPEC 会被误分类（fix-fix-daemon-lifecycle-races 事故 2026-09-06）。存量 fix 链仅剩 fix-fix-daemon-lifecycle-races（testing 中）即将自然收敛。

配置侧：`admin.*` 段已有多参数先例（`interval_minutes`、`merge_breaker_threshold`、`self_review.*`），护栏模式为 `core/config.py` validate + `get_admin_config` 缺省填充；配置热更新为既有 30s mtime 机制。前端设置页系统页签为 `core/dashboard/static/src/pages/settings/components/SystemPanel.tsx`，类型定义在 `core/dashboard/static/src/services/dashboard.ts`。新增配置项的五处同步样板为 agents.verify_redo_budget（fix-fix-daemon-lifecycle-races d6148c5：合并白名单 + 读写提取 + TS 类型）。

## Goals / Non-Goals

**Goals**

- 修复方式由 `admin.bug_repair_mode` 显式配置：`inplace`（缺省）/ `derive`
- 名称前缀分流退役：inplace 模式对 fix-* 名字 SPEC 同样原地打回
- 配置全链落地：validate、get_admin_config、设置读取合并白名单、系统页签 UI、TS 类型
- derive 模式完整保留派生闭环（守卫一、族谱 governor、done→重验父）

**Non-Goals**

- 不删除 `_do_legacy_fix_spec_bug_found` / `_on_spec_done` 闭环代码——derive 模式仍需它们；仅退役分流判定
- 不改原地打回的计数器/任务注入/升级闸门语义
- 不做模式切换时在飞链的迁移或清算（自然终态）
- 不引入第三种修复方式

## Decisions

### D1: 参数命名与取值

`admin.bug_repair_mode`，字符串枚举 `inplace` / `derive`，未配置缺省 `inplace`。置于 admin 段（该参数治理的是项目管理引擎的处置行为，与 `merge_breaker_threshold` 等同类）；枚举而非布尔，为未来第三种策略留扩展位。validate 拒绝非法值，报错文案风格与既有 admin 护栏一致。

### D2: 分流改造点单一化

只改 `_do_spec_bug_found` 开头的分支条件：由 `if self._is_fix_spec(spec_name)` 改为按有效配置值分流。每次 bug-found 事件实时读取配置（经 `get_admin_config`），不做实例级缓存——与配置热更新（30s mtime）语义对齐，切换模式后下一次事件即生效。`_is_fix_spec`、`_same_root`、`_resolve_fix_spec_name` 等辅助函数保留（derive 模式命名与去重仍依赖）。

### D3: derive 模式对 fix-* 名字父 SPEC 的派生

沿用 `_resolve_fix_spec_name` 的逐级前缀逻辑：非 fix 名字父 SPEC 失败派生 `fix-<name>`；fix-* 名字父 SPEC 失败继续逐级派生（fix-<name> 失败 → fix-fix-<name>）。与历史行为一致，无特判。

### D4: 模式切换的在飞链语义

不做迁移。derive → inplace 切换后，在飞 fix-* 链自然终态：子 fix 完成仍触发父 SPEC 重验（`_on_spec_done` 闭环保留），父 SPEC 重验再失败时按新配置原地打回。inplace → derive 切换后，下一次 bug-found 开始派生。配置为每次事件实时读取，无需重启。

### D5: 配置读取入口

`FamilyGovernor` 通过 `self._pm` 访问配置门面，读取走 `get_admin_config(config).get("bug_repair_mode", "inplace")` 同源路径（具体门面方法随现状，实现时对齐 PMEngine 既有配置获取方式），避免旁路解析 YAML。

### D6: UI 落点与缺省展示

系统页签（SystemPanel.tsx）新增「验证失败修复方式」选择项：`原地打回（inplace）` / `派生 fix SPEC（derive）`。读取时未配置显示缺省「原地打回」；保存写入 `admin.bug_repair_mode`。TS 类型在 `services/dashboard.ts` 与后端 admin 配置结构同步。

## Risks / Trade-offs

- **derive 模式复活族谱爆炸**：既有族谱收敛 governor（深度/宽度阈值 + 人工放行 waiver）与守卫一（非终态子 fix 去重）不变，仍全程生效。
- **配置读取路径旁路风险**：实现必须走 `get_admin_config` 同源路径；五处（validate/get/白名单/UI/TS）缺一即持久化缺失复发（agents.verify_redo_budget 教训），tasks 按 Deliverables 声明逐项对账。
- **在飞 fix-fix-daemon-lifecycle-races 过渡**：实现合并不影响其 testing 状态；其闭环重验不受本变更干扰。

## Migration Plan

无数据迁移。新参数缺省即现行默认行为（inplace），存量配置文件零改动。

## Open Questions

无。
