<!-- knowledge: capability=tasks-md-tracking rev=1 sources=spec/archive/2026-09-10-task-track -->

# tasks.md 任务清单跟踪

tasks.md 任务清单可跟踪性的三层治理：写入端分组标题格式契约、drafted→ready 晋升可解析性拦截、解析失败显式提示（CLI 与 dashboard 不再静默跳过）。

## 现行规则

- 分组标题格式契约（写入端）：`fenix_spec.py` 的 tasks artifact 生成指引（`instruction` 与 `template` 字段文本）将分组标题格式定为 MUST 约定 `## <编号>. <标题>`——编号为阿拉伯数字、编号后必须带点号（如 `## 1. 归档自动提交`）；指引同时说明下游解析器（CLI 进展脚本与 dashboard）与晋升 lint 均依赖该格式，偏离将导致任务清单不可跟踪。
- 解析兼容：分组标题解析正则点号可选，`## 1. 标题` 与 `## 1 标题` 两种格式均可解析出任务分组；lint 判定与下游解析正则严格同源，漂移由 tasks 跟踪测试兜底。
- 晋升拦截：drafted→ready 晋升校验含 tasks.md 可解析性 lint——文件存在但按下游同源规则解析出 0 个任务分组时判定违规，SPEC 保持 drafted，STATE.md error 含「tasks.md」字样，不派发 implementer；解析出 ≥1 个分组时不拦截；lint 自身异常 fail-open 放行晋升（记 WARNING）。
- 解析失败显式提示（tasks.md 存在但 0 分组，与「无文件」「正常解析」在输出上可区分）：
  - CLI 进展脚本打印含「tasks.md」与「未解析出任务」字样的警告行，其余区块正常输出；
  - dashboard 后端 SPEC 详情 `tasks_note` 字段为非空提示文本（含「未解析出任务」字样）；
  - dashboard 前端任务清单 Card 在 `tasks_note` 非空时显示 warning 级提示。
  无 tasks.md 文件时维持「暂无任务清单」空态，不打印警告、`tasks_note` 为空。

## 溯源

- [2026-09-10 2026-09-10-task-track](spec/archive/2026-09-10-task-track/) — 分组标题 `## <编号>. <标题>` MUST 契约写入生成指引；drafted→ready 可解析性 lint（0 分组拒晋升、fail-open）；CLI 警告行、dashboard `tasks_note` 字段与前端 warning 空态提示落地
