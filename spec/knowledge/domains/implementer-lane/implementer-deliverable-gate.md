<!-- knowledge: capability=implementer-deliverable-gate rev=5 sources=spec/archive/2026-09-06-add-implementer-deliverable-gate,spec/archive/2026-09-07-add-deliverable-extractor-semantics,spec/archive/2026-09-19-add-deliverable-delete-kind,spec/archive/2026-09-23-add-declaration-relocation-protocol,spec/archive/2026-09-26-fix-relocation-writeback-layer -->

# 交付物声明收工硬门

实现 run 收工时对交付物声明的最后关卡：在 merge 之前核对生效声明中每个硬校验条目在实现分支上真实达成，并防护声明被收缩绕门。

## 现行规则

- 提取范围：`tasks.md` 的 `## Deliverables` 声明段，条目 `kind` 限四值——`new`（本仓库新建文件）、`modify`（修改既有文件）、`delete`（交付物是让该路径合并后不存在，仅限入库文件）、`reference`（运行时写入目标/既有引用，非本仓库交付物）；`kind` 超出四值集合的条目被忽略；同一路径重复声明保留首见条目。
- 硬软分组：`new`/`modify`/`delete` 归 `deliverables`（硬校验组），`reference` 归 `references`（软校验组）；`references` 类路径缺失仅记审计日志（含 spec 与路径清单），不产生缺件、不重派、不变更状态。
- 收工校验时点与基准：实现 run 声明成功后、merge 之前，对**生效声明**（经统一解析入口取得，分支/worktree 优先、主树回退，见 `deliverable-declaration-resolution`）的 `deliverables` 组逐条在**实现分支 HEAD** 上按 kind 校验达成条件：`new`/`modify` 要求该路径 blob 存在，`delete` 要求该路径 blob 不存在。任一未达成 → 不执行 merge、不推进状态，按既有失败路径处置。声明来源必须取统一解析入口的分层结果，不得硬编码直读主树 `spec/changes/<spec>/tasks.md`。
- 结构化违规返回：校验结果为条目列表（每项含 `path`/`kind`/`violation`，`violation ∈ {missing, undeleted, removed}`），dispute 匹配、LLM 终审、重派话术据此按 kind 分化表述与可用归宿。
- 校验成本：纯文件系统/对象库存在性检查，不触发测试执行、LLM 调用或网络请求。
- 声明收缩防护：以派发时落盘的可信基线快照（见 `deliverable-declaration-resolution`）为参照——基线中的路径若在生效声明中被无声剔除（条目被删除，或 kind 被改写为 `reference` 等不满足原语义的 kind，且该路径在实现分支 HEAD 也不满足原 kind 要求），判收缩违规 `removed`。收缩违规与 `missing` 同源进入裁决流水线（见 `deliverable-declaration-triage`），不静默放行、不无界重派；经凭据登记或合法软化后复检通过方放行。
- 收缩防护的合法豁免仅两类：该路径有重定位凭据在册（见 `declaration-relocation-protocol`），或其 kind 经合法裁决软化（`reference` 且审计留痕）。删条目与改 kind 均不构成豁免。
- 基线快照不可用（未落盘/读取失败）时，收缩防护保守降级——不产生违规条目，并审计留痕说明本轮未做收缩判定。
- 陈日声明前置分类：产生缺件清单后、进入 LLM 终审前，先对缺件条目做确定性分类（纯机械的基线树存在性判定，零 LLM）；命中陈日信号（见 `declaration-relocation-protocol`）的条目走重定位通道，不直接按缺件打回重派；剩余非陈日缺件方进入既有终审/裁决流程。
- 缺件凭据核销收敛：`missing` 条目在跨 run 持久的 dispute 审计流中已有凭据（`typo` 裁决或重定位凭据，且凭据携带的替代路径在实现分支 HEAD 真实存在）时，以凭据核销收敛——不再要求旧路径在实现分支存在，不因「本轮无新凭据」而无限重派。凭据不存在或替代路径无据时不核销（fail-safe，走既有缺件处置）；核销仅作用于 `missing`，`undeleted`/`removed` 不被核销吞掉。

## 溯源

- 史前复原（早于 2026-09-06） — 基线形态：交付物存在性守卫核对声明与工作树实际产物，`.fenix/` 前缀路径归一化到项目根路径后核对
- 2026-09-06 2026-09-06-add-implementer-deliverable-gate — 建立守卫：从 tasks/proposal 提取交付路径、收工存在性校验、缺件阻断 merge、纯 stat 零成本约束
- 2026-09-07 2026-09-07-add-deliverable-extractor-semantics — 提取器升级硬软两类输出与 `.fenix/` 前缀归一化正式化，引用类缺失仅审计留痕
- 2026-09-19 2026-09-19-add-deliverable-delete-kind — 提取契约改为声明段显式四类 kind；校验基准迁移到声明段 + 实现分支 HEAD blob；`delete` 反判与结构化 violation 返回
- 2026-09-23 2026-09-23-add-declaration-relocation-protocol — 校验声明源改为生效声明（消灭主树硬编码错层）；新增声明收缩防护（`removed`）与陈日声明前置分类
- 2026-09-26 2026-09-26-fix-relocation-writeback-layer — 新增缺件凭据核销收敛：跨轮残留凭据 + 替代路径落地校验，收敛「缺件 → 无界重派」
