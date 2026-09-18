## Context

Deliverables 声明段今天有三类 kind：`new`（本仓库新建）/ `modify`（修改既有）/ `reference`（运行时写入目标或既有引用，仅审计、不参与缺件判定）。收工守卫（`_deliverable_gate_missing`）对 `new`/`modify` 硬校验 —— 判定基准是**实现分支 HEAD 的 blob 是否存在**；`reference` 走软校验，缺失只记审计日志。

「删除某个文件」因此没有可用的声明形态：

- 声明 `modify` → 晋升 lint 时路径在主树存在（通过），但收工守卫看的是实现分支，此时文件**已被删** → 确定性判缺件 → 打回循环。`fix-root-init-import-shadow`（2026-09-12）删仓库根 `__init__.py` 时撞上这条，只能改声明 `reference`，再用一条额外的回归断言手工兜住删除的强制性。
- 声明 `reference` → 晋升与守卫都不校验。`add-stale-code-selfheal`（2026-09-13）删除 `.fenix/hooks/restart-daemon-when-idle.py` 与一条 hook 配置项，tasks 5.1/5.2/5.3 三项全勾 `[x]`、spec 已 pushed，**但两个删除目标原封不动还在主树** —— 那两处是 gitignored 运行时文件，worktree 里根本不存在，删除动作作用在空路径上静默 no-op，而 `reference` 声明意味着连「没做」都没有任何信号，收口后靠人工发现。

也就是说：唯一合法的写法恰好是最不设防的那种，声明了删除与删除真的发生之间只剩作者自觉。

同时，既有框架对「声明与现实的矛盾」有一套**方向相反**的自动化：`promotion-soften`（晋升期）与 `guard-preclassify`（守卫期）会把「确定性不可交付」的声明**机械软化为 `reference`**。软化对 `new`/`modify` 是止血（本就不该硬校验），但对 `delete` 却是**把「该删」降级成「仅审计」**——恰好复刻本 SPEC 要消灭的形态。这是本设计必须正面处理的核心张力。

## Goals / Non-Goals

**Goals:**

- 新增声明 kind `delete`：可声明、可校验、可处置，语义为「合并后该路径不存在」。
- 三条防洗白：任何一条软化路径都不得把 `delete` 静默降级为空操作。
- 守卫的违规结构承载 kind，使「该删的还在」不被说成「缺件」。
- 顶掉产出期教学里「运行时文件删除用 `reference`」的旧处方——事故作者正是照着它走的。

**Non-Goals:**

- 不新增 `kind: manual`／不做「收口时把人工待办浮出到 admin 告警与 dashboard」的通道（本轮取最小面；这类删除的处置仍是「不进 Deliverables 段 + 人工在主树执行」）。
- 不做 delete-or-move（重命名）语义——重命名后旧路径缺失即已满足 `delete`，无需专门支持。
- 不改 Dashboard（当前不渲染 kind 字段）。
- 不回改历史 spec 的既有声明写法（`fix-root-init-import-shadow` 的 `reference` 声明保留原样）。
- 不处理 `.fenix/schemas/spec-driven/schema.yaml` 这份部署副本：全仓检索确认**无任何读取方**（`core/spec_gen.py` 只读框架根 `schemas/spec-driven/schema.yaml`），且它位于 gitignored 路径下——为一个无人读取的副本声明交付物，正是本 SPEC 要消灭的那类空声明。

## Decisions

### D1：`delete` 只允许入库文件，gitignored 路径上的 `delete` 一律 lint 拒

守卫的判定基准是**实现分支的 blob**。gitignored 路径不属于任何分支，若照搬反判逻辑，`_exists_on_branch()` 恒为假 → `delete` 恒判通过 → 静默空跑，新 kind 把脸二原样复刻。因此必须在晋升 lint 处直接拒绝，让「运行时文件删除」在**立项当下**就暴露，而不是留一个永远绿灯的假校验。

被否的替代方案：

- **让守卫改查主树工作目录**：删除在合并后才落到主树，守卫运行在 merge 之前；且 agent 在 worktree 里对主树是写保护的（`block-main-tree-write.py`），物理上做不到。校验一个 agent 根本无法达成的目标没有意义。
- **新增 `kind: manual` 承载「框架交付不了、需人工在主树执行」**：能把静默 no-op 变成显式欠账，是更完整的解法，但引入第二个新 kind + 收口期浮出通道 + 人工销账语义。本轮按最小面不做，作为后续独立议题。

### D2：`delete` 归入 deliverables 桶（硬校验），不新开第三桶

`extract_declared` 的 two-bucket 结构（`deliverables` 硬校验 / `references` 软校验）已承载了「这条声明该不该拦」的全部语义。`delete` 是硬契约（合并后必须不存在），归入 `deliverables` 即可复用既有的 dispute 通道、LLM 终审入口与重派路径。新开 `deletions` 桶会迫使这三条链路各加一套分支。

### D3：守卫返回结构由 `list[str]` 改为 `list[dict]`

```python
[{"path": "core/x.py", "kind": "delete", "violation": "undeleted"},
 {"path": "core/y.py", "kind": "new",    "violation": "missing"}]
```

「该删的还在」与「该建的不在」若共用「缺件 [path]」这一句话术，会同时误导两方：人类读 dashboard 时看到「缺件 core/x.py」却发现文件明明在；LLM 终审拿到的是被反向描述的输入，极易把「文件还在」误判成「声明写错了」从而给出 `reference` 裁决（D4 会再堵一层，但输入本身不该是错的）。kind 应当只有一份真相，因此让守卫直接返回结构化条目，而不是让三个消费点各自重读声明段反查。

代价：`dispatch.py` 内 4 个调用点同步改造。仅框架内部接口，SPEC 作者面不可见。

### D4：`delete` 条目排除出全部软化路径

三处必须显式排除，缺一即复刻原 bug：

| 位置 | 机制 | 若不排除 |
| --- | --- | --- |
| `core/deliverables.py` | `classify_unsatisfiable` / `soften_declared_kind`（`promotion-soften`） | 「该删」被改写成 `reference`，删除要求无声消失 |
| `core/pm_engine/dispatch.py` | 守卫缺件确定性预分类（`guard-preclassify`） | 同上，且发生在守卫判违规之后 |
| `core/pm_engine/dispatch.py` | LLM 终审的 `reference` 归宿 | LLM 看到文件还在，合法地把删除裁决为「应归 reference」 |

前两处是「机械软化」——对 delete 而言软化在语义上就是错的（`delete` 的不可交付形态已在 lint 阶段被拒，走到这里说明声明本身有问题，应当升级人工而非自动降级）。第三处 `delete` 条目的可用归宿收窄为 `typo` / `missing` / `unclear` 三个；判 `reference` 时机械拒绝该归宿并转 `unclear`（人工裁决）。

### D5：`delete` 的违规并入既有处置链，不新开通道

违规之后的动作与缺件同构：改声明（typo）/ 让 agent 真的去做（missing → 重派）/ 交人（unclear）。因此不新建通道，只让话术与可用归宿按 kind 分化。这保证了「收工守卫 → dispute → LLM 终审 → 重派/blocked」这条既有链路对两种违规保持同一套语义与同一份审计。

### D6：教学双源同改

`kind` 的教学出现在两处且互为副本：`skills/fenix-new/SKILL.md`（人读）与 `schemas/spec-driven/schema.yaml`（`fenix_spec.py instructions tasks` 的文本来源，机器读）。只改一处会造成「skill 说四 kind、instructions 说三 kind」的分裂。

更新内容除新增 `delete` 语义外，必须**顶掉**现有表格里「`.fenix/` 运行时文件 → 正确 kind：`reference`」这一行——它只说了运行时文件该用什么 kind，从没说**这类文件的删除交付不了**。事故作者照此推断「删除目标也声明 reference」是完全合理的推理。相应的表述改为：运行时文件的删除不进 Deliverables 段，由人工在主树执行。

## Risks / Trade-offs

- **R1 软化路径漏挡一处即复刻原 bug。** 缓解：三处防线各配独立测试；守卫侧再加一条「软化产物中不得出现 delete 条目」的断言，防止将来新增第四条软化路径时无声破防。
- **R2 返回结构变更外溢。** 缓解：`list[dict]` 的影响面限定在 `dispatch.py` 4 个调用点；对外（dashboard/CLI/agent）无暴露。
- **R3 作者仍可用 `reference` 声明运行时文件的删除。** 这是本 SPEC 无法机械拦截的残余：`reference` + gitignored 是既有合法组合（运行时写入目标），判断「这条 reference 其实是想表达删除」需要语义理解，文本匹配不可靠。故只做教学劝阻，并在本设计中显式承认这一残余，不假装已闭合。
- **R4 同路径同时声明 `delete` 与 `new`。** 提取阶段已有同路径去重（保留首见），不新增拒绝规则——重复声明属作者笔误，守卫会按首见的 kind 判定，行为确定。
