<!-- knowledge: capability=declaration-premechanize rev=2 sources=spec/archive/2026-09-13-add-declaration-premechanize,spec/archive/2026-09-19-add-deliverable-delete-kind -->

# 交付物声明机械化前置约束

确定性形态问题在晋升期就机械处置或拦截，不留到实现期烧轮次：晋升软化、晋升 lint 拒绝、守卫缺件确定性预分类与起草期教学注入。

## 现行规则

- 晋升期机械软化：daemon 在 drafted → ready 晋升时，对声明段中 `kind: new/modify` 且路径命中确定性不可交付模式（gitignored / 仓库外）的条目，在 lint 之前机械改写 `kind → reference` 并落 dispute 审计（reasoning 前缀 `promotion-soften`），随后正常晋升；不停留 `drafted + error` 等待人工修正。tasks.md 其余内容逐字保留。非确定性形态（`<spec_name>` 占位符、目录路径、主树不存在的 modify、basename 唯一命中的疑似笔误 new）不被软化，交由晋升 lint 照旧拒绝。软化编排中单条目改写异常时跳过该条目并记 warning，其余可软化条目继续，晋升流程不因软化编排异常中断。
- `delete` 排除出全部软化路径：晋升期软化（`classify_unsatisfiable`/`soften_declared_kind`）与守卫缺件确定性预分类（`guard-preclassify`）均不处理 `delete` 条目——软化的语义是「降级为仅审计、不再硬校验」，施加于 `delete` 即让「该删」静默消失。`delete` 的不可交付形态由晋升 lint 在前置阶段拒绝；走到软化编排处的 `delete` 条目保持原样交由 lint/人工处置。
- 晋升 lint 拒绝规则（`lint_declared`）：`kind: new/modify` 路径解析后（`~` 展开、绝对/相对路径归一）不在项目根内 → 违规拒绝晋升；`reference` 指向仓库外路径合法放行。`kind: delete` 四类拒绝——路径被 gitignore 排除（守卫基准为实现分支 blob，gitignored 路径反判恒通过）、路径在主树不存在（无可删）、路径是目录（守卫按 blob 校验，处方为逐个文件声明）、路径解析后不在项目根内；任一命中返回违规并阻止晋升，消息含路径、命中规则与处方。lint 自身故障保持 fail-open。
- 守卫缺件确定性预分类：收工守卫判缺件后、派 dispute-judge 之前，daemon 先对缺件清单做确定性分类——命中不可交付模式的条目直接机械软化（`kind → reference`）+ 审计（reasoning 前缀 `guard-preclassify`）+ 重跑守卫；全部命中则走既有放行分支且不派 judge run；混合缺件时确定性条目被软化并从 judge 输入移除，仅剩余真缺件进入 dispute-judge；预分类失败（声明段解析失败或软化改写异常）时全部缺件按既有 dispute-judge 流程处理。
- 产出期教学注入：SPEC 起草指引（fenix-new skill 与 spec_gen tasks 工件 instruction）注入四类 kind 语义——`new`=本仓库新建文件、`modify`=修改既有文件、`delete`=让该路径合并后不存在（仅限入库文件，守卫反判存在性）、`reference`=运行时写入目标/既有引用；及四类不可交付模式的 kind 约定——dist/构建产物 → 锚点文件 + `reference`；gitignored 路径 → 禁 `new/modify/delete`；`~`/仓库外路径 → 禁 `new/modify/delete`；`.fenix/` 运行时文件 → `reference`。明示边界：gitignored 运行时文件的**删除不能由 SPEC 交付**（实现 agent 在 worktree 内物理不可达这些文件，且对主树只读），此类删除不写进 Deliverables 段，须由人工在主树执行；起草指引中不存在「删除目标声明 `reference`」一类把删除引导到软校验的表述。
- 部署副本同源：`.fenix/core/deliverables.py` 与 `.fenix/schemas/spec-driven/schema.yaml` 部署副本与主树保持一致，保证 fenix-new lint 预检与 daemon 晋升审计使用同一份规则。

## 溯源

- 2026-09-13 2026-09-13-add-declaration-premechanize — 确立晋升期机械软化、lint 规则 6 仓库外路径、守卫缺件确定性预分类、产出期教学注入与部署副本同源
- 2026-09-19 2026-09-19-add-deliverable-delete-kind — `delete` 声明的四类不可交付形态 lint 拒绝；`delete` 排除出全部软化路径；教学注入升级四类 kind 语义与 gitignored 删除边界明示
