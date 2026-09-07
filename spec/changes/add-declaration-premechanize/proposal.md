# Proposal: add-declaration-premechanize

## Why

2026-09-06 当日声明类违规 3 次人工/预防性修正（14d6efc 14:48 / c254246 17:15 / ba5e4a8 19:49），直到第 4 个动作（867923d 20:07 晋升 lint 规则 5）才把已归纳的模式沉淀为规则——「逐例救火、当日第 4 次才规则化」，每例代价 = 1 次晋升返工 + 1 次 admin 往返，实测 08:46Z 守卫 block 挂到 17:15 修正（约 8.5 小时）。

同时 add-deliverable-declaration-triage（同日 03:11 verified）的三层拦截治的是「路径写错」（存在性），当日下午违规是另一类「路径不可交付」（路径存在但 gitignored / 仓库外，走不了 git merge-back），两类互不覆盖。规则 5 治理 gitignored 类后仍有盲区：`kind: new` 声明 `~`/仓库外路径时规则 4 零命中放行。

四类已知不可交付模式（dist 构建产物、gitignored 路径、`~`/仓库外路径、`.fenix` 运行时文件）在规则落地时其实早已归纳完毕，本可以在产出当下机械拦截、命中后机械改判——而不是等每例复发后人工修。本 SPEC 把这四类模式机械化前置：产出期教学 → 晋升期机械软化 → 守卫期确定性预分类，消除「1 次晋升返工 + 1 次 admin 往返」的每例代价。

## What Changes

1. **晋升期机械软化（zero admin 往返）**：`_on_spec_drafted`（drafted → ready）在 lint 之前调用新增 `soften_unsatisfiable_declarations`——声明段中 `kind: new/modify` 且路径命中确定性不可交付模式（gitignored / 仓库外）的条目，daemon 直接改写 `kind → reference`（复用既有 `soften_declared_kind`），软化记录落 dispute 审计流（trigger: `promotion-soften`）后正常晋升。不再「拒绝晋升 + 卡 drafted + error + 等人工修正 + 等 30min full_scan」。规则 1-4 类形态（占位符/目录/不存在/疑似笔误）不软化，维持既有拒绝语义（需 path 修正非 kind 修正）。

2. **lint 规则 6（仓库外路径）**：`lint_declared` 新增——`kind: new/modify` 声明 `~` 展开后、绝对路径越界或 `..` 越界的仓库外路径时拒绝晋升（规则 5 的 gitignore 机制覆盖不到仓库外；规则 4 的零命中放行盲区就此关闭）。仓库外 `reference` 合法放行（reference 本就是非交付物语义）。

3. **守卫缺件确定性预分类（跳过 LLM 往返）**：`_adjudicate_deliverable_missing` 派 dispute-judge 之前先跑确定性分类——缺件中命中不可交付模式的条目直接机械软化 + 审计（trigger: `guard-preclassify`）+ 重跑守卫；全清走既有放行分支，剩余真缺件才进既有 dispute-judge 流程（输入只带剩余项）。fail-open 覆盖晋升软化漏网（lint fail-open / 存量 spec）。

4. **产出期教学（写对而非改对）**：fenix-new skill（`skills/fenix-new/SKILL.md`）与 spec_gen tasks 工件 instruction（`schemas/spec-driven/schema.yaml`）注入四类不可交付模式表——dist 构建产物 → `reference`、gitignored 路径 → 禁 `new/modify`、`~`/仓库外路径 → 禁 `new/modify`、`.fenix` 运行时文件 → `reference`。SPEC 起草时声明即合规，违规根本不进入流水线。

5. **部署副本同步**：`.fenix/core/deliverables.py`、`.fenix/schemas/spec-driven/schema.yaml` 与主树同步（fenix-new lint 预检 sys.path 指向 `.fenix/` 部署副本，须与 daemon 审同一份规则）。

## Capabilities

- `declaration-premechanize`: 不可交付声明模式的确定性识别、晋升期机械软化、守卫期预分类与产出期教学。

## Impact

- **代码**：`core/deliverables.py`（分类器 + 软化编排 + 规则 6）、`core/pm_engine/engine.py`（晋升前软化接线）、`core/pm_engine/dispatch.py`（守卫预分类）、`schemas/spec-driven/schema.yaml`、`skills/fenix-new/SKILL.md`。
- **行为**：gitignored/仓库外 new/modify 声明从「拒绝晋升等人工」变为「daemon 机械软化 + 审计留痕 + 正常晋升」；守卫缺件命中确定性模式时不再派 dispute-judge LLM run（省 1 次轻量 judge 往返）；违规 SPEC 起草时即被教学拦截。
- **兼容**：规则 1-4 语义不变；`soften_declared_kind` / `DisputeAuditStore` / 防洗白重跑闸门均为既有设施复用；无声明段存量 spec 行为不变（提取路径早退）。
