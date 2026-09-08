# Tasks: add-draft-promotion-gate

## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/pm_engine/promotion.py
  kind: new
- path: core/pm_engine/engine.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/ApprovalModePanel.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: bin/fenix_cli.py
  kind: new
- path: docs/help/08-config.md
  kind: modify
- path: docs/help/06-governance.md
  kind: modify
- path: tests/test_config.py
  kind: modify
- path: tests/test_pm_promotion_gate.py
  kind: new
- path: tests/test_dashboard_api.py
  kind: modify
```

## 1. 配置键与晋升闸口

- [x] 1.1 core/config.py：新增 `gates.promote_mode` 校验（非枚举值加载报错，合法取值 auto/manual，值语义对齐 approve_mode）与 getter `get_promote_mode`（缺省 auto，命名对齐 `get_approve_mode`）；确认 gates 段未知键容忍性，如有严格白名单同步放开该枚举键
- [x] 1.2 core/pm_engine/promotion.py：新建共享晋升函数 `promote_drafted(project_root, spec_name, *, state_machine, logger) -> dict`——晋升前软化（soften_unsatisfiable_declarations + DisputeAuditStore `promotion-soften` 审计，软化编排异常降级 warning）→ 晋升 lint（lint_declared + lint_tasks_parseable）→ 违规合并写入 STATE error 并返回 `{"ok": False, "violations": [...]}`；目标不存在或状态非 drafted 时拒绝并返回明确原因，STATE 不变更；不内含 transition 与派发（由调用方收尾）
- [x] 1.3 core/pm_engine/engine.py：`_on_spec_drafted` 入口加闸口（`get_promote_mode` 为 manual → info 日志含 spec 名与「等待人工放行」语义后直接 return，不软化、不 lint、不写 error、不派发）；方法主体重构为调用 `promote_drafted`，ok 则 `transition ready` + 直调 `_on_spec_ready`（auto 态行为与重构前一致，含四条触发路径全覆盖）
- [x] 1.4 tests/test_pm_promotion_gate.py：闸口与共享函数测试——manual 时 spec_drafted 事件/start_after 到期/full_scan re-trigger 三路径均停留 drafted 且无 error 写入；auto 时晋升链行为与现行为一致；切回 auto 后 full_scan recovery 恢复自动晋升；共享函数对 lint 违规拦截（停留 drafted + error 格式与既有晋升 lint 失败一致）、非 drafted 拒绝、不存在拒绝
- [x] 1.5 tests/test_config.py：`promote_mode` 校验（非枚举拒绝）与缺省 auto（patch 双常量隔离用户级配置，防 home 敏感）

## 2. Dashboard API 与设置页单选

- [x] 2.1 core/dashboard/data.py：新增 `promote_spec(project_root, spec)` 构造 StateMachine/Logger 调共享晋升函数，结果含 ok/reason/violations；受管键白名单扩展 `gates.promote_mode`（读侧 sources 标注与写侧提取两处，data.py 配置读写段）
- [x] 2.2 core/dashboard/server.py：`POST /api/spec-promote?project=<name>&spec=<name>` 路由——project/spec 不存在 404（对齐 unfreeze 模式）；非 drafted 拒绝与 lint 违规返回 200 + ok:false + reason/violations；成功 200 + ok:true
- [x] 2.3 core/dashboard/static/src/services/dashboard.ts：新增 `promoteSpec(project, spec)` API client（对齐 freezeSpec/unfreezeSpec 模式）
- [x] 2.4 core/dashboard/static/src/pages/settings/components/ApprovalModePanel.tsx：「草稿晋升模式」Radio.Group 单选（manual/auto，与 approve_mode 单选同构）置于 approve_mode 设置项上方，反映当前配置含缺省 auto；保存载荷同时提交 `gates.promote_mode` 与既有 `approve_mode`（防整段覆盖丢失审批模式）；附说明文字（manual 停留草稿态供人工阅读，经 /fenix-ready、项目页按钮或 CLI 放行）
- [x] 2.5 core/dashboard/static/src/pages/projects/list.tsx：drafted 状态行加「晋升 ready」按钮（Popconfirm 确认，非 drafted 行不显示）；成功刷新列表，失败 message.error 展示 API 返回的拒绝原因/违规摘要
- [x] 2.6 tests/test_dashboard_api.py：promote API 测试——成功晋升、project/spec 404、非 drafted 拒绝、lint 违规返回 violations 且 STATE error 写入

## 3. CLI promote 命令

- [x] 3.1 bin/fenix_cli.py：新建 CLI 入口（argparse 子命令结构，不挂载 fenixd.py），`promote <spec> [--project <path>]`（缺省当前目录）——调共享晋升函数，成功/拒绝/违规明细打印到终端，退出码成功 0 失败非 0
- [x] 3.2 tests/test_pm_promotion_gate.py：CLI 层测试（以函数级调用 promote 主逻辑为主，避免子进程脆弱性）——成功晋升退出码 0、lint 违规非 0 且停留 drafted、`--project` 指向外部路径生效

## 4. 文档同步

- [x] 4.1 docs/help/08-config.md：gates 配置表增补 `promote_mode` 行（枚举 auto/manual、缺省 auto、热更新属性，对齐 approve_mode 行格式）；相关审批/流程描述段落同步（基于当前工作区已有内容追加，不整段重写）
- [x] 4.2 docs/help/06-governance.md：增补「草稿人工放行」说明——单选位置（设置页审批页签）、三种放行方式（/fenix-ready / 项目页按钮 / CLI promote）、lint 拦截语义（违规停留 drafted 写 error）

## 5. 回归验证

- [x] 5.1 相关测试全绿：tests/test_config.py、tests/test_pm_promotion_gate.py、tests/test_dashboard_api.py 及既有 pm_engine/dispatch 回归（test_pm_engine_dispatch_fixes.py 等）无回归
- [x] 5.2 前端编译验证：core/dashboard/static 下 tsc/build 通过（dist 产物不入库，仅本地验证）## 验证修复（第 2 轮失败）

### 上轮实现结论（自动携带，来自上一轮 implementer 收工结论）

修复 CLI --project 参数位置 Bug（将 --project 从主解析器移到 promote 子解析器），CLI promote 命令现在支持 SPEC/文档声明的 promote <spec> [--project <path>] 语法；回归测试全部通过（config/promotion/dashboard-api/dispatch）

- [x] 先复核失败有效性：逐条核对 `spec/changes/add-draft-promotion-gate/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [x] 修复后重跑验证确认通过

## 验证修复（第 1 轮失败）

- [x] 先复核失败有效性：逐条核对 `spec/changes/add-draft-promotion-gate/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [x] 修复后重跑验证确认通过
