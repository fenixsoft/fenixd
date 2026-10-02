# 多类型验证报告兼容
<!-- knowledge: capability=multi-kind-report-compat rev=1 sources=spec/archive/2026-09-12-add-verify-multi-kind-runner -->

多形态场景（web/cli/api）在验证报告、dashboard 渲染、裁决链与冻结集的下游兼容契约：字段驱动、零迁移。

## 现行规则

- report.json kind 透传：`scenarios` 列表每个元素携带 `kind` 字段（透传场景定义）；`summary` 统计口径不变（blocked-env 仍计入 warning）。CLI/API 场景元素的 `screenshots` 与 `visual_results` 恒为空列表（schema 兼容，旧读侧读到空值不报错）。
- dashboard 字段驱动渲染：spec detail 场景页签对 web/cli/api 做 kind 徽章视觉区分；断言详情按字段有无自适应渲染（有 `selector` 显示选择器；cli 的 `stream`/`exit_code`、api 的 `path`/`status` 各自随字段渲染），不按 kind 写分支组件；截图区对空列表显示占位说明（CLI/API 场景证据为命令输出/HTTP 响应体）。
- verdict 链零改动：逐断言归因（assertion_triage 四分类）、product-bug 拦截豁免、证据合规检查对 CLI/API 断言照常工作——只依赖 `assertion_results` 的 `pass`/`layer`/`classification` 字段与 `failed_assertions` 非空，不依赖 DOM 语义。回归不变量：非 PASS 场景缺 triage 判违规；全失败断言非 product-bug 才可豁免；单条 product-bug 断言阻止场景级豁免。
- 场景冻结 kind 携带：冻结条目（`ScenarioEntry`）含可选 `kind` 字段，`to_dict` 序列化、读侧缺失时缺省 `web`，存量冻结文件零迁移；冻结集补齐/合并场景必须携带 kind，使补齐后的场景可被正确 Runner 执行。

## 溯源

- 2026-09-12 add-verify-multi-kind-runner（spec/archive/2026-09-12-add-verify-multi-kind-runner） — 新增 report.json kind 透传与空证据列表 schema 兼容、dashboard 字段驱动渲染契约、verdict 链对 CLI/API 的零改动回归不变量、冻结条目可选 kind 零迁移
