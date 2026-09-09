## Context

merge-back 失败链路现状：`worktree_manager._merge_back_from_branch_locked` 内置两级自愈（产物冲突对齐、ignored-DU 采纳删除），自愈不适用时 abort 主树、返回失败；调度层将 spec 置 ready 并全新重派 implementer（新 worktree、从零实现）。add-dashboard-incremental-data 事故实测重派代价：首个 implementer 3.5h 工作全废。产物类冲突自愈已在 be29a63 目录层次容错化，语义冲突失败是剩余的最大浪费点。

归档能力衔接：`merge-circuit-breaker`（失败指纹熔断）与 `repair-lane-dedup`（fix 链去重，名字相近但域不同）——repair 通道不得绕过熔断，也不产生新 spec 故不触发同根互斥。

## Goals

- merge-back 语义冲突失败后，实现工作（分支 + worktree 现场）可被原地修复而非重做
- 主树在任何时刻不进入半合并态
- 与既有预算、熔断、遗产清扫机制无缝协同，不新增配置键

## Decisions

### D1 分层：git 层判定、调度层决策
`worktree_manager` 保持纯 git 操作层：merge-back 失败返回值增加结构化的冲突分类信息（冲突路径清单 + 是否仍有语义冲突）。**是否进入 repair、派发与轮次计数由调度层（pm_engine/dispatch）决策**——worktree_manager 不直接派 agent，与现有自愈"能治则治、不能治交回上层"的边界一致。

### D2 修复方向反转
repair agent 在实现分支一侧执行 `git merge main` 并解决冲突（而非在主树合分支）。主树在派发前已 abort 保持干净；worktree 内 merge 不触碰主树。repair commit 后框架调用既有 `merge_back_from_branch` 重推——分支已含 main 历史，快速前进。主树不冻结：repair 期间其他 spec 可照常推进主树，re-merge-back 若再遇新冲突按既有重试/熔断路径走。

`.gitattributes merge=binary` 在 worktree 内 merge 同样生效（共享 attributes 文件），dist 内容冲突自动以分支侧为底。

### D3 分支载体三态的判定基准
以 **git 事实**（`git worktree list` + 分支解析）为判定基准，不信任内存表（daemon 重启即失）：
- (a) worktree 目录在且解析到实现分支 → 原地进入
- (b) 目录不在但分支存在 → `git worktree add <path> <branch>` 换壳（checkout 既有分支，非 -b 新建）
- (c) 分支不在 → fallback 全新重派，prompt 注入当次 merge 失败上下文

### D4 认领与清扫竞态
repair run 复用 `_legacy` take 语义：认领时摘出登记表（同 `_active_reuse` fast-track 复用路径），sweeper 宽限期不再回收。同时在 `_spec_locks` 注册同款锁，防止 repair 进行中重复派发。

### D5 repair agent 形态
复用 implementer 派发管线（claude CLI、stream-json、`--add-dir`），run_id 前缀 `repair-<spec>-<ts>`，token 记 spec 名下（run 归属不变，预算天然继承）。`prompt_builder` 新增 repair 模板：spec 身份 + 冲突清单摘要 + 方向说明（合 main 入分支、解冲突、跑测试、commit）+ 显式失败出口；**不含**原 worktree 地址类间接情报。轮次上限 `MAX_REPAIR_ROUNDS_PER_FAILURE = 2` 为模块常量，**不新增配置键**（规避 dashboard UI 联动义务）。

### D6 失败链界定与熔断协同
"同一失败链" = 一次 merge 失败 → repair 轮（≤2）→ re-merge-back 成功，或超轮次/agent 显式失败 → 回退 fallback 结束。状态机以 `_repair_round` 计数，fallback 后新 implementer 的 merge 失败开启新链。熔断指纹计数（`_merge_fp`/`_merge_streak`）**不被 repair 轮清零**；re-merge-back 再失败连续累计。blocked spec 的派发拦截同样覆盖 repair 派发路径。

## Risks

- **repair agent 乱解语义冲突引入回归**：prompt 强制要求跑测试；解不了必须显式失败；最终由 verify 链把关（repair 不自证）——repair 只是把"必然的重做"变成"可失败的努力"
- **repair 期间主树前进致 re-merge-back 新冲突**：不冻结主树的代价，按既有重试与熔断收敛；真实并发窗口小
- **换壳 worktree 缺构建缓存**：npm install 全量成本；与 fallback 重派同量级，可接受
- **原地 worktree 有 agent 遗留脏状态**：repair prompt 要求先 `git status` 自查现场；脏文件属未提交工作，合并决策交 agent 结合 spec 判断，异常时显式失败走 fallback
- **观测**：repair run 以独立 run_id 进 runs 记录与 dashboard 流水，前缀 `repair-` 可辨识，不计入 fix 族谱
