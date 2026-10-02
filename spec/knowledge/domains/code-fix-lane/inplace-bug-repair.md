# 验证缺陷原地修复

<!-- knowledge: capability=inplace-bug-repair rev=2
     sources=spec/archive/2026-09-05-add-inplace-bug-repair,spec/archive/2026-09-12-add-bug-repair-mode-config -->

验证裁决认定真实产品缺陷后的处置通道：按 `admin.bug_repair_mode` 分流为原地打回或派生 fix-* 子 SPEC。

## 规则

### 分流
- 验证裁决采纳 `bug-found` 结论且失败被归为真实产品缺陷时，按 `admin.bug_repair_mode` 配置分流（未配置缺省 `inplace`）；分流依据不依赖 SPEC 名称前缀（`fix-` 前缀判定退役），原地打回对任何 SPEC 生效，包括名称带 `fix-` 前缀的 SPEC（不派生 `fix-fix-*`）。

### inplace 模式（缺省）
- 对父 SPEC 原地打回：① 内部字段 `_verify_fail_rounds` 递增 1 并持久化（跨重启不归零）；② 状态重置为 `implementing`（保留 branch/error 等既有字段语义）；③ 在父 SPEC `tasks.md` 末尾追加或更新「`## 验证修复`」任务段——引用 `spec/changes/<spec>/verification-report.md`、指明修复对象为报告中的「真实产品 Bug」、标注当前失败轮数；④ 后续实现与重验由既有派发循环与验证链路接管，不创建 fix-* 子 SPEC。
- 追加任务段不得改写父 SPEC 既有任务与勾选状态；重复失败递增轮数而非新建链条（族谱深度保持 0）。
- 失败轮数升级闸门：`_verify_fail_rounds` 达到模块常量阈值 3 时停止原地打回，SPEC 状态置 `blocked`，发送 human-escalation-alerts 告警（含 SPEC 名、失败轮数与 verification-report.md 路径）；人工介入后计数器语义由人工裁决决定（人工重置即重新获得自动修复机会）。该闸门仅作用于 inplace 模式的打回计数。

### derive 模式
- 按既有派生逻辑创建或复用 fix-* 子 SPEC：`fix-` 前缀逐级命名（`_resolve_fix_spec_name`）、非终态子 fix 去重守卫、族谱收敛 governor（深度/宽度限制与人工放行）均照常生效。
- fix-* 子 SPEC 完成（done）后框架自动触发父 SPEC 重验（闭环）。

## 溯源

- 史前基线 — bug-found 处置已确立原地打回方向：打回 implementer 修复以替代 fix 派生，打回后调度资格放行 implementer，升级告警摘要携带 SPEC 名称。
- 2026-09-05 2026-09-05-add-inplace-bug-repair（spec/archive/2026-09-05-add-inplace-bug-repair） — 契约化原地打回：失败轮数计数持久化、tasks.md「验证修复」任务段注入、3 轮升级冻结闸门与人工升级告警。
- 2026-09-12 2026-09-12-add-bug-repair-mode-config（spec/archive/2026-09-12-add-bug-repair-mode-config） — 分流依据由 SPEC 名称前缀改为 `admin.bug_repair_mode` 配置（缺省 inplace，前缀判定退役），补 derive 模式分支；升级闸门限定仅作用 inplace 计数。
