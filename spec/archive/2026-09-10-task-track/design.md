# Design: task-track — tasks.md 任务清单跟踪链路治理

## Context

2026-09-04 诊断确认（run-lifecycle-hardening 任务清单在 CLI 与 dashboard v3 详情页静默消失）：

- tasks.md 分组标题历史双格式：旧 `## 1. 标题`（带点号）、2026-09 起漂移出 `## 1 标题`（无点号）。
- 两处解析正则副本 `^##\s+\d+\.\s+` 要求点号：`.fenix/bin/fenix_process.py:76`、`core/dashboard/data.py:824`（行号为热修前）。
- 失效链：分组匹配不上 → `current_group` 恒 None → 任务项被过滤 → `groups=[]` → 输出层 `if groups:` 静默跳过。
- 已热修：两处正则放宽为 `^##\s+\d+\.?\s+`（点号可选）。本 change 治本：写入端契约 + 晋升拦截 + 失败显式提示。
- 写入端唯一落点：full/fast-track 模式的 tasks.md 均由需求 Agent 按 `fenix_spec.py instructions tasks` 的 instruction/template 撰写（fast-track Agent 只实现不生成 spec），故固化模板文本即固化全部写入路径。

## Goals / Non-Goals

- Goals：格式漂移不再复发（写入端）；万一复发在晋升时被拦（lint）；再万一漏网则在展示层可见（提示）。三层防御各自独立生效。
- Non-Goals：不迁移/重写存量 tasks.md 文件；不统一两处解析正则为共享模块（副本收敛属后续重构，本 change 仅要求 lint 与下游解析「同源规则」）；不改变 tasks.md 勾选语义与 run 记录叠加逻辑（`_should_overlay`/`parse_run_task_done` 不动）。

## Decisions

### D1. 解析正则以「点号可选」为唯一兼容基线

所有解析点维持热修后的 `^##\s+\d+\.?\s+(.+)$`。任务项正则 `^- \[(x| )\] (\d+\.\d+) (.+)$` 不变。写入端 MUST 约定为带点号格式（`## 1. 标题`），兼容不删——存量文件不迁移，lint 不拦截双历史格式。

### D2. 晋升 lint 落点：`core/deliverables.py` 新增独立函数，`engine.py` 并列调用

- `core/deliverables.py` 新增 `lint_tasks_parseable(spec_dir, project_root) -> list`：tasks.md 不存在 → 返回 `[]`（不拦，fast-track 前置 spec 允许后补）；存在 → 用与 `data.py parse_tasks` 同源的分组正则（`^##\s+\d+\.?\s+` + 任务项 `^- \[(x| )\]`）解析，0 分组 → 返回含「tasks.md」字样的违规消息。
- `core/pm_engine/engine.py:_on_spec_drafted` 在既有 `self._lint_deliverable_declarations(...)` 调用后并列调用；违规合并进同一 error 写入路径（保持 drafted + STATE error），沿用 fail-open（异常 → WARNING + 放行）。
- 「同源规则」的实现方式：lint 函数内以相同正则字面量实现并在两处注释互指（`data.py:parse_tasks` ↔ `deliverables.py:lint_tasks_parseable`），不提取共享模块——解析器在 `data.py`（dashboard 进程），lint 在 `deliverables.py`（daemon 进程），跨进程共享模块收益低且引入耦合；正则字面量漂移风险由本 change 的双格式兼容 Scenario 回归兜底。

### D3. CLI 提示：`if groups:` 空分支细分

`fenix_process.py` `show_progress` 中，改为先判断 tasks.md 文件存在性：存在但 `parse_tasks` 为空 → 打印 `⚠ tasks.md 存在但未解析出任务（分组格式不匹配？）`（YELLOW）；文件不存在 → 维持现状。`parse_tasks` 返回空列表时同时打印，避免再次静默。

### D4. dashboard：`tasks_note` 字段 + 前端三分支空态

- `core/dashboard/data.py` spec 详情组装（`"tasks": parse_tasks(...)` 处，约 :2166）并列新增 `"tasks_note"`：`tasks.md` 存在且 `parse_tasks` 为空 → 提示文本「tasks.md 存在但未解析出任务分组（分组格式不匹配或文件为空）」；否则 `None`。
- `core/dashboard/static/src/pages/projects/detail.tsx` 任务清单 Card 空态分支（现 `: <Typography.Text type="secondary">暂无任务清单</Typography.Text>`）改为三分支：`detail?.tasks_note` 非空 → `<Typography.Text type="warning">`（文案取自 `tasks_note`，附「可检查 SPEC 的 tasks.md 分组标题格式」）；否则维持 secondary「暂无任务清单」。
- 移动端适配沿用既有 screen-xs 作用域惯例，无新增断点。

### D5. dist 产物重建提交

`detail.tsx` 变更后必须重建 `core/dashboard/static/dist/` 并提交（v3 入库产物，主树 :8787 静态实时读盘；漏建将导致 UI 验证全量假阴性——既有事故教训）。构建在实现 worktree 内完成，随实现分支提交。

## Risks / Trade-offs

- **[lint 误拦存量 spec]** → D2 判定正则与下游解析严格同款（点号可选双格式），实现分支上对全库既有 spec tasks.md 跑一遍 lint 回归（脚本或单测枚举），0 误拦为通过标准。
- **[tasks.md 为空的合法场景被拦]** → 守卫性选择：tasks.md 存在但文件内容为空（0 字节/无任务行）同样拦截——此类 spec 无可跟踪任务属撰写缺陷，拦截早于 run 烧钱（与 add-fast-track-mode 守卫目录型声明同哲学）。文件不存在不拦。
- **[模板文本改动影响进行中 change]** → 模板仅影响新撰写，无运行时读取方依赖其具体文本；单测断言关键词存在即可，不锁全文。
- **[dashboard 需重启]** → `data.py` 变更对常驻 :8787 不热生效，push 后按惯例重启 dashboard（人工步骤，见 proposal Impact）。

## Open Questions

（无）
