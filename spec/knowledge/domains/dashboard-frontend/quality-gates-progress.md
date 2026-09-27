<!-- knowledge: capability=quality-gates-progress rev=2 sources=spec/archive/2026-09-26-add-quality-gates-visibility,spec/archive/2026-09-27-add-impl-selfcheck-model-probe -->

# 质量门禁进度呈现

implementer 收尾自查与框架守卫合成的 6 道质量门禁状态，在 SPEC 详情页以勾选列表 + 进度条呈现；纯可观测性能力，不新增/放宽任何门禁判定。

## 现行规则

- 落盘契约（键名固化）：implementer 收尾检查阶段将 run 内自查 3 项结果写入 worktree 内 `.fenix/verify-progress/<spec>/quality-gates.json`，顶层结构固定 `{"gates": {<gate-id>: {"status": <枚举>, ...详情键}}, "updated_at": "<UTC ISO8601>"}`；gate-id 全集与顺序固化为 `full-suite`（全量回归测试）/ `frontend-build`（前端构建与类型检查）/ `interaction-contract`（交互契约自查）；status 枚举四值 `passed`/`failed`/`running`/`skipped`，未写入的 gate-id 由读侧视为 `pending`；`frontend-build` 仅涉前端改动时执行，否则写 `skipped` 并附非空 `reason`；写入前先创建父目录（mkdir -p 语义）；文件随既有 verify-progress 目录拷回机制在 run 结束时落主树，runner 不新增拷贝逻辑。`code-review` 不在落盘契约之内——implementer 不向该文件写 `code-review` 键（写了也被读侧忽略），该门由读侧从 ocr 异步车道产物合成。键名与契约逐字一致，禁止同义改写。
- 收尾守卫宽松对账（fail-open）：impl 产物硬门不因 quality-gates.json 缺失判 run 失败；文件存在时仅做机械合法性检查（JSON 可解析、status 在枚举内、gate-id 在全集内），违规仅记 WARNING 日志并放行，不产生任何打回/重试/预算消耗；框架不针对该文件新增失败终态。
- 读侧合成 6 道门（fail-open）：数据层按 spec 名输出 `items: [{id, desc, status, detail}]`，`total = 6`，`done = passed + skipped`（skipped 表示该门已了结）。run 内 3 项取 quality-gates.json——implementing 且 worktree 存在时优先读 worktree（缺失回退主树双位置兜底），run 结束读主树拷回版本。框架守卫 3 项：`result-artifact-gate` 取最新 impl run 终态（run 过门进入 implemented 及之后为 passed；最新 run gate-blocked 为 failed、detail 含截断归因原文；implementing 在飞且无 gate-blocked 痕迹为 pending）；`deliverable-guard` 取 STATE 状态（status ∈ {implemented, testing, verified, done, pushed} 为 passed；blocked 且 error 归因命中词表「交付物/deliverable/dispute/格式复检」为 failed，否则 pending）；`code-review` 取 ocr 车道产物 `.fenix/verify-progress/<spec>/code-review.json`（worktree 优先、主树兜底；车道在飞或产物 `running` 为 running、`completed` 为 passed 附 findings 与处置计数摘要、`unavailable` 为 skipped 附非空 reason、不可见为 pending）。缺数据一律 `unknown`（如历史 spec 无文件，仅影响对应数据源条目）；解析全程 fail-open，任何缺失/损坏不抛异常、不产生 error 字段。
- 产物指纹：`code-review` 门读侧校验产物 `(branch, merge_base, head_commit)` 指纹，指纹陈旧按不可见处理（pending），不采信 stale 报告的状态。
- `full-suite` 门数据源优先级：①框架侧回归产物（`core/regression.py` 产出、带分支指纹的回归结果快照，指纹校验对齐 ocr 门语义，指纹陈旧不采信）→ ②quality-gates.json 的 run 内自查值（存量与降级兼容来源）→ ③两者皆无 → `pending`。全量回归判定责任单点在验证链，读侧因 full-suite 项 pending 呈现的缺口不触发任何打回。`desc` 使用固定中文文案：全量回归测试 / 前端构建与类型检查 / ocr 代码审查与处置 / 交互契约自查 / 结果文件产物硬门 / 交付物守卫与格式复检。
- 详情页渲染：SPEC 详情页在「任务清单」Card 之后、「验证进度」Card 之前渲染「质量门禁」Card——上部进度条（复用 `ProgressBarTile` 形态，done/total 取合成值，从零起走，门禁专属橙色系，区别于任务进度蓝绿渐变），下部 6 道门勾选列表（与任务清单同款交互：passed 项勾选 + 删除线置灰）。状态渲染区分：`passed` 勾选+删除线；`failed` 未勾选+红色文字、detail 归因为辅助文案；`running` 未勾选+「进行中」标识；`pending` 未勾选+灰色；`skipped` 勾选框置灰打勾样式或显式「不适用」徽标（不与 passed 混淆）；`unknown` 未勾选+「无记录」灰色辅助文案。数据经 `spec_detail` 下发 `quality_gates` 字段 `{exists, done, total, current, items}`，SSE 增量推送自动携带。空态：`exists == false` 且 spec 状态在 implementing 之前（drafted/ready）时不渲染本 Card；其余状态 `exists == false` 时渲染 Card 并显示「暂无质量门禁记录」提示。

## 溯源

- 2026-09-26 add-quality-gates-visibility — 建立门禁可观测全链：quality-gates.json 落盘契约（键名固化、code-review 不落盘）、守卫宽松对账、读侧合成 6 道门与详情页门禁 Card
- 2026-09-27 add-impl-selfcheck-model-probe — `full-suite` 门改数据源优先级：框架侧回归产物优先、run 内自查降级兼容、皆无 pending 零打回
