# add-tasksmd-relint-gate

## Why

2026-09-11 add-impl-terminal-nocommit-gate 事故：implementer 用 `sed -i 's/^- \[ \]/^- [x]/'` 勾选 tasks.md 时，replacement 端误转义 `\^` 输出字面 `^`，12 行任务全变成 `^- [x] 1.1 …`。dashboard `parse_tasks` 的任务行正则 `^- \[(x| )\] (\d+\.\d+)` 匹配不上，4 个分组标题在、组内任务数全部为 0——前端渲染形同「没有任务清单」。

现有防线全部失明：

1. `lint_tasks_parseable`（drafted → ready 晋升 lint，task-track R2）只拦「0 个分组」，本次损伤形态是「分组在、任务行 0」，直接穿透；
2. implementer 自己的收尾自检 `grep -c "^- \[x\]"` 返回 0（exit 1），仍照样 commit 并宣布勾选完成——agent 自检 fail-open；
3. 晋升 lint 只在立项期跑一次，implementer 中途（收尾勾选时）编辑 tasks.md 后无任何事后校验。

用户拍板（2026-09-11）：只做 **lint 复检（事后门禁）**，不做 dashboard `tasks_note` 告警扩展。

## What Changes

- **ADDED**：`core/deliverables.py` 的 `lint_tasks_parseable` 加强——「分组存在但任务行总数为 0」新增为违规形态（与既有「0 分组」违规并列），违规文案给出修正处方（含本事故的 `^-` 前缀特征）。
- **ADDED**：implementer 成功收口的事后门禁——在 dispatch 层两条 merge 前路径复用加强后的 lint：
  - full 车道：`dispatch.py` implementer 成功块（交付物守卫同层、merge 之前）；
  - fast-track 车道：`_run_fast_track_flow` 交付物守卫之后、硬校验之前。
  lint 违规 → 不合并、不推进，按失败重派并在 error 中写明违规明细与修正处方；连续计数沿用既有重派语义。

## Capabilities

- `tasks-md-relint`：tasks.md 在实现收口期的可解析性复检门禁

## Impact

- **受影响代码**：`core/deliverables.py`（lint 函数加强）、`core/pm_engine/dispatch.py`（两个挂点）
- **零破坏**：全库扫描（spec/changes + spec/archive）无「分组在但 0 任务行」存量，加强规则零误拦；fast-track 前置 spec 无 tasks.md 的放行语义不变
- **风险**：fast-track 车道部分 SPEC 有意不维护任务清单（若 tasks.md 存在则同样受检）；同源正则三处（data.py / deliverables.py / fenix_process 复用 data）漂移风险由 tests/test_task_track.py 兜底
