# Design: add-declaration-premechanize

## Context

声明段机械校验现状（全部既有设施，本 SPEC 复用而非新建）：

- `core/deliverables.py`：`extract_declared_entries`（声明段解析）、`lint_declared`（晋升 lint，规则 1-5）、`_path_is_gitignored`（规则 5 判定核心，`git check-ignore` fail-open）、`soften_declared_kind(spec_dir, element)`（kind→reference 确定性文本改写，triage D4 落地）、`replace_declared_path`（typo 修正）。
- `core/pm_engine/engine.py:_on_spec_drafted`（drafted→ready）：先 `_lint_deliverable_declarations` + `_lint_tasks_parseable`，违规 → drafted+error 等人工；通过 → ready → 排队实现。**软化接入点在 lint 之前**。
- `core/pm_engine/dispatch.py:_adjudicate_deliverable_missing`（守卫缺件→dispute-judge LLM 终审）与裁决执行段（typo/reference 机械执行 → `DisputeAuditStore.append` 审计 → `_deliverable_gate_missing` 重跑防洗白）。**预分类接入点在 judge 派发之前**。
- `core/admin_store.py:DisputeAuditStore`：`.fenix/dispute_audits.jsonl` append-only 审计流。
- 产出期教学面：`skills/fenix-new/SKILL.md`（fenix-new 是软链，仓库内源副本）+ `schemas/spec-driven/schema.yaml` tasks 工件 instruction（`fenix_spec.py instructions` 输出触达一切起草流）。

## Goals / Non-Goals

- **Goals**：四类已知不可交付模式（dist 构建产物 / gitignored / `~` 仓库外 / `.fenix` 运行时）全链机械化——产出期教对、晋升期软化、守卫期免 LLM 直改；每例「1 次晋升返工 + 1 次 admin 往返」代价归零。
- **Non-Goals**：不动规则 1-4 语义（占位符/目录/不存在/疑似笔误仍拒绝——它们需 path 修正，软化会掩盖真错）；不建新审计通道（复用 dispute_audits.jsonl）；不做 runner 级 hook（框架出库机制之外）；不改守卫 reference 软校验语义。

## Decisions

### D1 分类器（core/deliverables.py）

新增两个纯函数 + 一个编排函数：

- `_path_is_outside_root(project_root, candidates)`：任一 candidate 解析后不在 `project_root` 内 → True。判定顺序：`os.path.expanduser`（`~`/`~user`）→ `os.path.abspath`（`..` 越界在此归一）→ 与 project_root resolve 后做前缀判定（`os.path.commonpath` 或 `relative_to`，`..` 段已消解）。非仓库外（含仓库内相对路径）→ False；异常 fail-open 返回 False（不因判定故障阻塞晋升）。
- `classify_unsatisfiable(entry, project_root)`：entry 含 path/kind；`kind ∈ {new, modify}` 且（`_path_is_gitignored` 或 `_path_is_outside_root`）→ True；其余 False。`reference` 恒 False（它就是软化终点）。
- `soften_unsatisfiable_declarations(spec_dir, project_root) -> list`：`extract_declared_entries` 逐条 `classify_unsatisfiable` → 命中即 `soften_declared_kind(spec_dir, element)`；单条改写异常（并发改写/格式漂移）跳过该条记 warning 不中断（fail-safe，交由后续 lint 拒绝兜底）；返回软化记录 `[{element, kind_before, kind_after}]`。无声明段（start None）早退返回 []。

### D2 晋升接线（engine.py `_on_spec_drafted`）

lint 调用之前插入：`softened = soften_unsatisfiable_declarations(spec_dir, project_root)`；非空时 logger.info（spec 名 + 软化清单）+ `DisputeAuditStore.append`（`{"spec", "trigger_run_id": "", "judge_run_id": "", "verdicts": [{element, verdict: "reference", reasoning: "promotion-soften: gitignored/outside-root", ...}], "diff": {...before/after}}`，trigger 经 reasoning 字段区分，审计 schema 不扩列）；审计写失败非阻塞。软化后 lint 照常执行（软化条目已转 reference，规则 5/6 不再命中；其余违规照旧拒绝）。**软化永远先于 lint**，保证「确定性模式不产生 drafted+error 卡死」。

### D3 lint 规则 6（lint_declared）

`kind: new/modify` 路径（字面 + 归一化候选）经 `_path_is_outside_root` 判 True → 违规，消息含路径与「仓库外路径不可作为 new/modify 交付物，应声明 reference 或改为仓库内路径」。与既有规则同 fail-open 惯例。仓库外 `reference` 放行。规则 5（gitignored）与规则 6 并列共存——晋升路径软化先行两者都不再触发，规则 6 的独立价值在 fenix-new 预检（§3.3）与软化 fail-safe 兜底后的暴露。

### D4 守卫预分类（dispatch.py `_adjudicate_deliverable_missing`）

入口处（组装 judge 输入之前）：

1. 读取声明段 entries，partition：`deterministic = [m for m in missing if classify_unsatisfiable(entry_of(m))]`；声明段无该条目（正则提取的存量 spec）不预分类。
2. deterministic 非空：逐条 `soften_declared_kind`（异常跳过该条、留在 missing 里）→ `DisputeAuditStore.append`（verdicts 带 reasoning: `guard-preclassify`）→ 重跑 `self._pm._deliverable_gate_missing(spec_name, result)`。
3. 重跑全清 → 走既有「裁决执行后守卫重跑通过」放行分支（恢复 in-flight、放行 merge），**不派 judge run**。
4. 仍有剩余 → 剩余项作为 missing 进入既有 dispute-judge 流程（judge 输入只带剩余项）。

### D5 产出期教学

- `schemas/spec-driven/schema.yaml` tasks 工件 instruction 追加四类模式表（经 `instructions tasks` 输出触达一切起草 agent）：
  - dist/构建产物目录 → 写确定性锚点文件且 `kind: reference`（运行时重建，非 git 交付物）
  - gitignored 路径 → 禁 `new/modify`，声明 `reference`
  - `~` 展开或仓库外路径 → 禁 `new/modify`，声明 `reference` 或不声明
  - `.fenix/` 运行时文件 → `reference`
- `skills/fenix-new/SKILL.md` §3.2 tasks 指引同表注入（与 schema 表措辞一致，注明「daemon 晋升时会对命中条目机械软化并审计留痕」）。

### D6 部署副本同步

`.fenix/core/deliverables.py` 与 `.fenix/schemas/spec-driven/schema.yaml` 是主树副本（fenix-new lint 预检 sys.path 指向 `.fenix/`）。实现收尾在 **merge-back 后的主树**执行同步（cp 主树 → .fenix）——worktree 内 `.fenix` 为运行时目录断链（不可在 worktree 内同步），daemon 重启后运行时与预检同源。

## Risks / Trade-offs

- **软化掩盖真缺件**：gitignored/仓库外路径声明 new/modify 本就无法经 git 交付，软化只是把人工必做的修正机械化；防洗白重跑闸门保证其余真缺件仍拦截（与 triage 4.4 同语义）。
- **审计流混用**：promotion-soften / guard-preclassify 与 dispute-judge 共用 dispute_audits.jsonl，靠 verdicts[].reasoning 前缀区分——不扩列，读侧按前缀过滤即可。
- **误判风险**：分类器只认 gitignored（check-ignore 原生判定）与仓库外（路径解析）两个确定性信号，零语义推断；fail-open 双向保底（判定故障 → 不软化 → lint 照旧拒绝）。
- **`kind: new` + gitignored 真需入库文件**：声明白身矛盾（gitignored 文件不可能经 merge-back 交付），正确动作是改 gitignore 或换路径——软化 + 审计留痕把矛盾显式化，不静默。
