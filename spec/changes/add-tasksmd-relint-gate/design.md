# add-tasksmd-relint-gate 设计

## Context

tasks.md 的解析正则在两处同源维护（task-track D1/D2 双写约定）：

- `core/dashboard/data.py:parse_tasks`——分组 `^##\s+\d+\.?\s+(.+)$` + 任务行 `^- \[(x| )\] (\d+\.\d+) (.+)$`
- `core/deliverables.py`——分组 `_TASKS_GROUP_RE`（同上）+ 任务行 `_TASKS_ITEM_RE = ^- \[(x| )\]`（无 id 要求，用途仅计数）
- `bin/fenix_process.py` 复用 `data.parse_tasks`，不独立维护

既有防线 `lint_tasks_parseable`（deliverables.py:913）只在 **drafted → ready 晋升**时跑，且只拦「分组数为 0」。2026-09-11 add-impl-terminal-nocommit-gate 事故中 implementer 收尾勾选把任务行写成 `^- [x] 1.1 …`（sed replacement 端 `\^` 输出字面 `^`），分组完好、任务行全灭——晋升 lint 已经过期跑不到，收口期无任何校验，dashboard 任务清单空白。

## Goals / Non-Goals

- **Goal**：implementer 中途编辑 tasks.md 后、merge 进主树前有一次机械复检；损伤不进主树。
- **Goal**：lint 规则加强覆盖「分组在、任务行 0」形态。
- **Non-Goal**：dashboard `tasks_note` 告警扩展（用户拍板不做）。
- **Non-Goal**：检查任务行的 id 编号与分组编号的对应关系、勾选态语义（`x` vs 空格）——超出本次损伤面，YAGNI。
- **Non-Goal**：拦截 agent 用 sed 编辑 tasks.md 本身——工具自由，只校验结果产物。

## Decisions

### D1：lint 规则加强放在 `lint_tasks_parseable` 内（同源正则处）

「分组存在但任务行总数为 0」并入 `lint_tasks_parseable` 违规集。用 `_TASKS_ITEM_RE` 计数任务行——注意 `_TASKS_ITEM_RE` 只要求 checkbox 不要求 id，比 data.py 口径宽松；本门禁的目的是「下游能不能展示出任务」，宽松口径恰好正确（checkbox 存在即可读出任务；若连 checkbox 都没有，id 无从谈起）。违规文案给出修正处方，点名 `^-` 前缀特征（本次事故签名），重派 run 可机械自修。

计数逻辑：分组数 > 0 且任务行数 == 0 → 违规。分组数为 0 的既有违规形态不变。

### D2：挂点 = 两条 merge 前路径，交付物守卫同层

**full 车道**（dispatch.py implementer 成功块）：在零变更哨之后、交付物守卫同层（merge 之前）插入复检。此刻分支已定、worktree 已清（full 车道 run 成功后 worktree 清理），tasks.md 以**实现分支 HEAD** 的版本为准——但 merge 前 spec 目录内容在分支上，复检查分支版本的 tasks.md（`git show branch:spec/changes/<name>/tasks.md`）成本与收益不匹配；实际上交付物守卫同层的既有代码就以 `spec/changes/<spec_name>` 主树路径为校验基准的先例（`_lint_deliverable_declarations` 同形态），而**主树版本在 merge 前 = 立项版本**——这正是缺口：中途损伤发生在分支上。

因此 full 车道复检基准 = **分支上的 tasks.md**：`git show <branch>:spec/changes/<name>/tasks.md`，失败（路径不存在/读取失败）→ fail-open（不拦，与 lint 既有 fail-open 语义一致；交付物守卫兜底其它缺件形态）。实现为 `lint_tasks_parseable` 的变体入口：接受已读入的文本或分支 ref 而非 spec_dir 路径。为避免两套解析漂移，核心计数逻辑抽为模块级纯函数 `_tasks_parse_counts(text) -> (groups, items)`，`lint_tasks_parseable` 与分支变体共用。

**fast-track 车道**（`_run_fast_track_flow`）：fast-track 成功时不清理 worktree（延迟清理，merge 前 worktree 仍在）——worktree 内 `spec/changes/<name>/tasks.md` 即最新版本，直接读文件复检；路径不存在 → fail-open。

两车道违规处置一致：**不合并、不推进状态**，error 写违规明细 + 修正处方，按失败重派（full 车道走既有失败重派通道、fast-track 走 `_handle_fast_track_failure`）。连续重派封顶沿用车道既有熔断语义，不新增计数器。

### D3：fail-open 语义保持

lint 函数自身异常 → 调用方 WARNING 放行（engine 层 `_lint_tasks_parseable` 既有形态）。复检挂点同样：任何读取/执行异常 → WARNING 放行。理由：tasks.md 损伤的代价是显示层空白（不烧钱、不阻塞推进），门禁误拦的代价是整轮重派烧钱——宁可漏拦不可误拦。

### D4：不扩 tasks_note、不动 data.py

`tasks_note` 维持现状（只兜 0 分组）。`data.py`/`fenix_process.py` 解析端零改动——本次只加写入端门禁。

## Risks / Trade-offs

- **分支读取基准与主树不同**：full 车道用 `git show branch:path`，fast-track 用 worktree 文件——两条读取路径都要测试覆盖。风险缓解：纯函数 `_tasks_parse_counts` 单点测试，读取路径薄封装。
- **误拦风险**：加强规则在全库 177 spec（changes + archive）扫描零命中，首日零存量误拦。新 spec 撰写期就有晋升 lint 拦截（加强后同样生效），不会带病进入实现期。
- **重派循环**：若网关返回的 implementer 反复产出同形态损伤，重派会消耗预算——熔断沿用既有 3 次封顶 → blocked 交人工，与零变更哨同构，无新增循环风险。

## Migration Plan

无迁移。加强规则对存量 spec 天然通过（扫描证实），对增量 spec 晋升期即生效。

## Open Questions

无——挂点、口径、fail-open 语义均已在事故解剖与用户拍板（只做 lint 复检）中定案。
