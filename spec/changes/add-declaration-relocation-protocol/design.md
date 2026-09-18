# Design: add-declaration-relocation-protocol

## Context

交付物声明（tasks.md `## Deliverables`）在**规划期**由 planner 写入**主树**；**实现期**
Agent 只能改 **worktree/分支** 内的那份。所有消费方（收工守卫
`_deliverable_gate_missing`、晋升 lint、预分类、LLM 终审/裁决、提示词组装
`prompt_builder`、fast-track 快照 `fast_track_result`）目前各自硬编码
`project_root/spec/changes/<spec>/` 直读主树，形成**声明权威源**与**声明改写权限**
的错层。

当规划期声明的路径被**后续上游重构**删除/改名（非本 spec 所为），主树声明即陈旧
且**永不可满足**：守卫每轮判 `missing` → 打回重派 → 重派复用同分支（
`fix-redispatch-loop-governance` 的 worktree 保留机制）→ 实现方已无新事可做 →
原地打转至 `blocked`，烧掉整轮预算与全部既有成果。

09-18 `fix-relint-redispatch-legacy` 实证：`core/pm_engine/dispatch.py` 被
`refactor-giant-classes`(6491c960) 拆为包并删除；该 spec 主树声明仍指单文件；实现方
已在分支 `814f64f5` 对齐声明为 6 条真实路径、验证 5/5 全过，守卫仍读主树旧声明，
两轮空转（`_retry_count` 2/3）。人工回填主树声明方才解卡。

约束：改动触及核心门禁链路与双车道状态机，回归面广；且「读分支声明」天然引入
**实现方自证**张力（被守卫者可删声明行绕门），必须由独立的可信参照系闭合。

## Goals / Non-Goals

**Goals:**

- 消除声明读取基准错层：全部消费方经**单一解析入口**取「生效声明」，基准为
  **实现分支/worktree**（实现期真实在测的那份），主树回退。
- 闭合「删声明行绕门」：以派发时落的**可信基线快照**（实现方不可触及）做**收缩防护**。
- 为「规划期路径因上游重构失效」建立正式语义与机械执行（**重定位协议**），
  使其走**重定位**而非打回重派。
- 双车道（full / fast-track）缺件处置收敛为**同源裁决流水线**，fast-track 获得与
  full 一致的终审/裁决兜底。
- 重定位与软化统一落 dispute 审计流，可追溯、可复核、可回滚。

**Non-Goals:**

- 不改动 kind 语义（`new`/`modify`/`delete`/`reference` 的既有判定与反判）。
- 不改动晋升 lint 的形态规则（`declaration-premechanize` 已覆盖）。
- 不引入「声明自动跟随重构」的语义推断（只认可满足性确定性信号，不做「哪个新文件
  对应旧路径」的猜测——那是「无凭据的声明改写」，与防洗白冲突）。
- 不改动 merge-back / autostash 机制本身（另属 `evo-merge-back-wip-*` 治理面）。
- 不解决「实现方主动删除声明以缩小交付面」以外的作弊向量（如伪造文件内容）。

## Decisions

### D1：声明读取基准 = 实现分支（worktree 优先 → 分支次之 → 主树回退）

**决策**：新增统一解析入口（`core/deliverables.py` 内 `resolve_effective_declaration`），
按 `worktree 内文件 > git show <branch>:...tasks.md > 主树文件` 优先序读取，返回与
既有 `extract_declared` 同构的结果。全部消费方改经此入口。

**理由**：实现期「在测的那份」就是分支上那份；主树在 merge-back 前只是立项旧版本。
`_tasks_md_relint_from_branch` / `_tasks_md_relint_from_worktree` 已是「读分支/worktree」
的既有先例（`add-tasksmd-relint-gate`），本决策把它推广为全消费方的统一契约。

**备选**：(a) 保留主树读取、仅在「主树声明解析失败」时回退分支——治不了根（主树声明
语法合法但语义陈旧时不会失败）；(b) 全部改 worker 侧在派发前把主树声明同步进 worktree
——引入额外写主树路径，且丧失「分支是权威」的语义。

### D2：声明改写基准 = 同一份生效声明（分支/worktree），主树由 merge-back 自然对齐

**决策**：裁决（typo 修正 / reference 软化 / 重定位）改写的目标 = **生效声明所在位置**，
与 D1 的读基准同位。full 车道在守卫/裁决窗口保留 worktree（复用
`fix-redispatch-loop-governance` 落地的 legacy 保留机制），改写直接写 worktree 内
`tasks.md` 并由 merge 带入分支；worktree 已清理的兜底路径以
`git -C <root> commit` 原子落到分支。

**主树对齐由 merge-back 完成**：分支的 tasks.md 会随 merge 带入主树，故**不再**单独
写主树声明——彻底消除「分支已改、主树仍旧」的错层复发面。

**理由**：读写同位是本次修复的核心；若读分支、写主树，judge 的修正对守卫不可见，
等价于把现有死循环换个触发条件（这正是 `adjudication.py` 当前写
`self._pm.project_root/spec/changes/...` 的隐患）。

**备选**：(a) 读写均改主树——回到 D1 的根因；(b) judge 修正后强制重启一轮让 worker
重新同步——多烧一轮，且仍有竞态。

### D3：收缩防护以「派发时可信基线快照」为独立参照系

**决策**：实现 run **派发时**，daemon 把当前**主树**声明集合快照落到
`.fenix/verify-progress/<spec>/declaration-baseline.json`（含 path+kind、时刻、run id）。
该位置**不在 worktree 内**，实现 Agent 路径不写入——它是被守卫者不可触及的参照系。
守卫对账时：基线路径若在生效声明中**无声剔除**、且该路径在实现分支 HEAD 也不满足
其原有 kind 要求、且无重定位/软化凭据 → 判 `violation: "removed"`，不放行。

**理由**：允许读分支声明后，守卫实际上信任了被守卫者提交的声明；收缩防护把
「声明只可增不可减（除非有凭据的替换/软化）」机械化为一道独立校验，闭合该张力。

**备选**：(a) 不设防护、信任实现方——直接复刻「删声明即绕门」；(b) 防护锚在 git 历史
（对比上一提交的声明）——分支复用/多轮重派下历史锚点漂移，且实现方仍可提交删除，
不如独立快照稳固。

### D4：陈日声明 = 确定性信号 + 三要素凭据的重定位

**决策**：陈日信号 = 生效声明中 `new`/`modify` 条目在**基线树（主树 HEAD）不存在**。
命中即走重定位：凭据三要素齐备（旧路径基线不存在 + 替代路径在实现分支 HEAD 存在 +
来源标注）方机械改写，`kind` 保持；任一缺失或 basename 多命中/零命中 → 不自动重定位，
转 LLM 终审或人工。

**理由**：这是本次事故的直接病灶——上游删了 `dispatch.py`，声明指向不存在路径，
不判「本轮实现缺失」而应判「声明陈旧需重定位」。零语义推断（只认存在性）避免
把「该新建的 new 文件尚未建」误判为陈日。

**备选**：让 LLM 直接给替代路径并改写——已有 `typo` 裁决归途可复用（`actual_path`），
故重定位复用该归途而非新造一条；机械 basename 唯一命中作为无 LLM 时的确定性快路。

### D5：双车道裁决流水线统一

**决策**：把 full 车道现有的「预分类软化 → 终审 → 机械执行 → 防洗白复检」抽为车道
无关入口（`_adjudicate_deliverable_missing` 泛化），fast-track 车道
（`fast_track.py:263`）接入同源调用。陈日前置分类插在预分类之前。重定位/软化
**不消耗重派预算**，仅确认缺失（`missing`/`unclear` 转打回）计数。

**理由**：fast-track 当前缺件直落重派（无终审兜底），与 full 行为分叉；本次治理的
死循环在两车道同源，收敛为一处逻辑才能一次修净。

**备选**：仅修 full、fast-track 另开 spec——分叉会持续漂移，且本次事故正是 full 车道
表现，fast-track 的同型缺口迟早复现。

## Risks / Trade-offs

- **[读分支声明引入自证风险]** → D3 可信基线快照 + 收缩防护闭合；无基线时降级为
  保守（不做收缩判定）并审计留痕，避免误伤正常轮次。
- **[full 车道保留 worktree 至裁决终态，占用磁盘/与清扫器竞态]** → 复用
  `fix-redispatch-loop-governance` 的 legacy 保留与清扫器豁免（宽限期回收已在册）；
  裁决终态后释放。
- **[分支声明与主树声明在多轮重派下累积漂移]** → 以「生效声明（分支）」为唯一真相，
  主树只作基线快照来源与 merge-back 落点；不做双向合并。
- **[替代路径 basename 误匹配]** → 仅「唯一命中」自动重定位；多命中/零命中转终审或
  人工（与 `deliverable-declaration-triage` 的 basename fail-open 取向一致）。
- **[回归面：存量无声明段 spec]** → 统一入口对无声明段返回空（等价跳过），行为退化
  到守卫上线前，零迁移。
- **[并发编辑（spec-review 同写声明）]** → 改写遵循「读-改-写 + 改前重读校验」；
  漂移则 fail-safe 转缺件处置，不覆盖。
- **[fast-track 接入流水线后行为变化]** → 以「缺件 → 终审」替代「缺件 → 直落重派」，
  回归测试须覆盖 fast-track 缺件的终审触发与判定通过放行两条路径。

## Migration Plan

1. 统一解析入口先落地并让**读取侧**切换（守卫/预分类/lint/prompt/快照），此步单独
   可用、零语义变化（分支缺失时回退主树 = 现状）。
2. 落**可信基线快照**写入（派发时），再开**收缩防护**判定（先 WARNING 观察一轮，
   再升硬门）。
3. 落**陈日声明前置分类 + 重定位协议**（先只做确定性 basename 重定位，再接入终审
   `actual_path` 归途）。
4. 最后做**双车道统一**（fast-track 接入）。
5. 回滚：各步均以「分支/worktree 优先」为增量，回退即改回读主树（删除入口调用），
   基线快照与收缩防护可独立关停（配置开关或降级审计）。

## Open Questions

- **重定位的替代路径来源优先级**：机械 basename 唯一命中 vs LLM 终审 `actual_path`，
  两者冲突时以谁为准？（初版倾向：终审优先，机械仅在无终审可用时兜底。）
- **收缩防护的硬门时机**：直接硬门还是先 WARNING 观察若干轮（存量 spec 可能存在
  合法的声明收缩——如规划冗余条目被实现方精简）？需实证存量行为面。
- **主树声明是否需要一次「立项期对齐」**：上游重构删除声明路径后，立项期声明的
  陈旧是否也应在晋升 lint 处预警（而非等到收工守卫）？属收益延伸，非本次必需。
