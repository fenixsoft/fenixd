# Tasks: add-bug-repair-mode-config

## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/pm_engine/family.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/SystemPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: tests/test_config.py
  kind: modify
- path: tests/test_family_governor.py
  kind: modify
```

## 1. 配置后端（admin.bug_repair_mode）

- [ ] 1.1 `core/config.py`：admin 段 validate 新增 `bug_repair_mode` 护栏——允许缺省（None）或字符串枚举 `inplace`/`derive`，非法值报错文案对齐既有 admin 护栏风格
- [ ] 1.2 `core/config.py`：`get_admin_config` 返回值新增 `bug_repair_mode`，未配置缺省 `"inplace"`
- [ ] 1.3 `tests/test_config.py`：新增校验场景——未配置缺省 inplace、合法 inplace/derive 通过、非法取值（如 "always"/非字符串）被拒

## 2. 引擎分流改造

- [ ] 2.1 `core/pm_engine/family.py`：`_do_spec_bug_found` 分流条件由 `_is_fix_spec(spec_name)` 改为读取 `admin.bug_repair_mode` 有效值（经 get_admin_config 同源路径，实时读取不缓存）；inplace（含未配置缺省）→ 原地打回（对任何 SPEC 生效，含 fix-* 名字）；derive → `_do_legacy_fix_spec_bug_found` 派生路径
- [ ] 2.2 `core/pm_engine/family.py`：derive 分支保留守卫一（非终态子 fix 去重）、族谱收敛 governor、`_resolve_fix_spec_name` 逐级命名；`_on_spec_done` 的 fix-* 完成 → 父 SPEC 重验闭环保持不动
- [ ] 2.3 `tests/test_family_governor.py`：新增分流场景——未配置默认对 fix-* 名字 SPEC 原地打回（不派生 fix-fix-*）、显式 derive 对非 fix 名字 SPEC 派生子 fix 并在子 fix 完成后闭环重验、模式实时生效（配置切换后下一次 bug-found 按新值分流）

## 3. 设置读取与合并白名单

- [ ] 3.1 `core/dashboard/data.py`：设置读取/合并链路纳入 `admin.bug_repair_mode`（对齐 agents.verify_redo_budget 样板：管理键、项目层级来源标注、有效配置合并缺省 inplace）
- [ ] 3.2 `tests/test_system_settings_config.py`（或既有设置合并测试落点）：未配置显示缺省 inplace、配置 derive 后读取链路返回 derive 且持久化

## 4. Dashboard 系统页签 UI

- [ ] 4.1 `core/dashboard/static/src/services/dashboard.ts`：admin 配置 TS 类型新增 `bug_repair_mode`（与后端结构同步）
- [ ] 4.2 `core/dashboard/static/src/pages/settings/components/SystemPanel.tsx`：新增「验证失败修复方式」选择项（原地打回 / 派生 fix SPEC），未配置显示缺省「原地打回」，保存写入 `admin.bug_repair_mode`
- [ ] 4.3 前端构建通过（tsc/vite 零错误），不提交 dist 产物

## 5. 收尾验证

- [ ] 5.1 全量相关测试通过（test_config / test_family_governor / test_system_settings_config 及既有回归不破）
- [ ] 5.2 对照 specs 场景清单逐条自检：默认原地打回、fix-* 名字 SPEC 原地打回、二次失败递增、derive 派生+闭环、三轮冻结升级、页面缺省展示、修改持久化、热切换生效
