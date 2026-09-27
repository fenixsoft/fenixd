<!-- knowledge: capability=self-evolution rev=2 sources=spec/archive/2026-09-18-add-framework-self-evolution,spec/archive/2026-09-19-evo-item-retention-doc-tracking -->

# 自进化车道（条目复核与 SPEC 起草立项）

框架自托管 daemon 把各项目 todo.md 的自省条目逐条独立复核、判定，并对值得立项的条目按 fenix-new 流程起草 SPEC：立项默认等用户点「同意」，打开自动接受后才由框架闭环到流水线。

## 现行规则

- 触发与就绪扫描：仅 `PROJECT_ROOT == FRAMEWORK_ROOT` 的自托管 daemon 维护自进化检查点，节拍复用 admin 巡检间隔（`admin.interval_minutes`，缺省 5 分钟）。逐项目就绪条件：`.fenix/self_review_state.json` 的 `last_run_at` 可解析为 ISO8601 且晚于该项目在 `.fenix/evolution/state.json` 的 `last_analyzed_at`（无记录视为从未分析），且 `.fenix/todo.md` 存在非空。未就绪项目不入队、不产生 admin 告警（最多 DEBUG/INFO 日志）；就绪即入队，不等待其它项目到齐。非自托管 daemon 不启用本检查点。
- 单飞：当且仅当无分析 run 在途时，检查点立刻以队列中全部就绪项目启动一次分析 run（一个进程同时拿多份 todo.md，不为每个项目各起进程）；在途判定基于 daemon 内部活跃 run 状态（run_id 前缀 `evo-` 或角色 `evolution`），不依赖外部进程扫描；已有分析 run 在途时就绪项目留队等下一检查点。
- 分析 run 形态：agent 角色 `evolution`、prompt 模板 `agents/evolution.md`，经既有 `AgentRunner._run_claude` 启动（超时、轮次上限、token 预算、provider 熔断、run 文件与归账全走既有链路，不另起子进程路径）；模型链取 `agents.models.self-review` → 回退 `agents.models.administrator` → 默认网关兜底（缺配置不拒绝启动）；在框架主树执行且不创建 worktree；run_id 前缀 `evo-`，stream-json 落 `.fenix/runs/evo-*.jsonl`。
- 逐条子代理复核：一条目派一个 Task 子代理（同一条目单 run 内不重复派发），输入至少含条目在 todo.md 中的原文与所属项目根路径；子代理为只读核查者——不建 `spec/changes/` 条目、不写 STATE.md、不改任何文件。init 事件工具表无 Task 工具族时降级为同进程串行逐条复核，并在 run 日志与契约产物记 `degraded: "no-task-tool"`；降级不导致整轮失败。
- 判定契约：子代理必须独立回源核查（只读日志、源码、STATE.md、git 记录），不直接采信 todo.md 自述的「调查评估」；每条结论含 `problem_exists`、`suggestion_sound`（yes/no/partial）、`worth_spec`（布尔）与 `rationale`（引用 `文件:行号`、日志时间戳、run id、STATE 条目名等至少一项可核对证据）；核实不了明示「未核实」并给保守判定（`worth_spec` 不为真），不编造；`analysis_md` 须可独立阅读（含结论、核查过程、证据、与存量 SPEC 的关系），不只复述原文。
- 产物契约：run 结束写 `.fenix/evolution/out-<run_id>.json`——`items[]` 含 project、date_section、section（∈ 浪费/失误/可改进）、title（逐字取自 todo.md）、impact/evidence/analysis/suggestion、verdict、analysis_md、spec{name/capability/proposal_md/spec_md/design_md/tasks_md（仅 `worth_spec` 为真时必填，否则为 null）}。JSON 非法、缺 `items`、section 越枚举或缺必填字段 → 整轮判失败：admin WARNING（含 run_id 与原因）、水位不推进、零条目零草稿；`worth_spec` 为真而 spec 内容缺失 → 该条标 `draft_failed` 并记录缺失字段，其余条目照常落地。产物文件在框架读取完成后删除。
- 身份与幂等：条目 id = `sha1(f"{project}\x1f{date_section}\x1f{section}\x1f{title}")[:12]`，跨环境稳定；去重权威来源为 `.fenix/evolution/items.jsonl` 已有 id 集合——id 已存在的条目无论状态（pending/analyzed/draft_failed/accepted/auto_accepted/rejected/accept_failed）均不再分析、不再生成草稿；items.jsonl 对同一 id 只保留一条记录（重复落地更新而非追加）。
- 水位：`.fenix/evolution/state.json` 按项目记 `last_analyzed_at`（ISO8601 UTC）与 `last_run_id`，仅作触发判据；推进仅发生在分析 run 成功落地之后，且取 run 启动时刻的快照（不取落地时刻，避免漏掉 run 执行期间新写入的条目）。`self_evolution.max_items_per_run` 限制单轮处理条目数，超出者留待下轮（id 未入库，下轮自然再选中），水位不因截断推进到「已全部处理」。
- 草稿与同源 lint：`worth_spec` 为真且 spec 内容齐全 → 按 fenix-new 流程把 SPEC 全套写入 `.fenix/evolution/drafts/<id>/`（proposal.md、specs/<capability>/spec.md、design.md、tasks.md——`## Deliverables` fenced yaml + `## <编号>. <标题>` 分组任务行、`.spec.yaml`（schema: spec-driven + created + mode: full）），随后执行与 daemon 晋升同源的 lint 预检（`lint_declared` + `lint_tasks_parseable`）：无 violation → 条目 `pending`；有 violation 或内容缺失 → 条目 `draft_failed`、删除草稿目录（不留半成品）、violation 原文与 agent 原始内容摘要记入条目记录，绝不落 `spec/changes/`、绝不注册 STATE.md。`worth_spec` 为假 → 不生成草稿，状态 `analyzed`。
- 接受路径（人工同意与自动接受共用，全程框架代码、不经 LLM）：① 条目状态须 ∈ {pending, accept_failed}，其余状态幂等返回现状；② SPEC 名 = `evo-` + agent 给出的 `spec.name`（须匹配 `^[a-z0-9][a-z0-9-]*$`，不合法 → `draft_failed`）；与 `spec/changes/<name>`、STATE.md 同名条目或 `spec/archive/*-<name>` 撞名时追加 `-<id 前 6 位>`，仍冲突 → `draft_failed` + 告警；③ 草稿复制到 `spec/changes/<name>/` 后仅 `git add spec/changes/<name>/` 并提交（message 形如 `[fenix] spec: <name>`），禁用 `git add -A` / `git add .`；④ 提交成功才 `StateMachine.add_spec(<name>, {status: drafted, priority: 5})`（不写 start_after，立即进入调度）；⑤ 注册成功才删暂存草稿并置 `accepted`/`auto_accepted`，记录 spec_name、decided_at、decided_by（manual/auto）。提交失败不注册、注册失败保留草稿并置 `accept_failed` + admin 告警；不产生「已注册未提交」或「已提交未注册」半成品。注册后的 SPEC 走既有流水线，推送审批门 `gates.require_push_approval` 保持不变。
- 拒绝路径：仅状态 ∈ {pending, draft_failed, accept_failed} 可拒绝；对 accepted/auto_accepted/rejected 拒绝报错且零改动。拒绝时删除 `.fenix/evolution/drafts/<id>/` 并置 `rejected`（记 decided_at）；删除前校验解析后目标路径位于该条目自己的草稿目录内，符号链接与越界路径一律拒绝删除并报错。
- 删除路径：对任意状态生效（不设状态门）；硬删——条目记录移出 items.jsonl（不写墓碑、不留占位），草稿目录存在时一并删除（同样的路径包含校验）；读-改-写在同一把 flock 内完成，不与 daemon 侧写入交错。已知后果（UI 确认弹窗向用户明示）：id 退出 `known_ids()`，todo.md 同名记录会在下一轮分析 run 重新入库。
- 自动接受：`self_evolution.auto_accept` 为真时，分析 run 落地完成后同一检查点内对本轮全部 `pending` 条目逐条走接受路径（`decided_by: auto`），不需要前端交互；单条失败置 `accept_failed` 并保留草稿，不影响其余条目；不作用于 `analyzed` 与 `draft_failed` 条目、不改已决定条目。开关为假（含配置缺失）时保持 `pending` 等待用户决定。
- 条目保留与自动清理：items.jsonl 仅保留「创建时间在最近 7 天内」与「按创建时间倒序最近 100 条」的并集（两者中数量较多者），其余硬删；两阈值为固定常量，不新增配置键。清理复用删除路径语义（不写墓碑、草稿一并删、路径包含校验、todo.md 标记幂等回写）；保留排序以创建时间倒序 + 条目 id 兜底为确定性次序；`created_at` 缺失或不可解析 → 判为保留。清理由 daemon 检查点周期执行，不因分析 run 在途而跳过，也不依赖分析 run 成功落地；逐条删除失败（如 OSError）计数记录、不中断其余条目清理与 daemon 主循环。
- 配置节 `self_evolution`：`auto_accept`（布尔，缺省 false）与 `max_items_per_run`（正整数，缺省 20，上界 200）；节、键缺失或值非法（非布尔/非正整数/超上界）一律回退缺省，不抛异常、不使 daemon 启动失败；走既有 30s 配置热更新。两键均为全局（用户级）键：Dashboard 配置写入 API 对项目级作用域提交 `self_evolution` 返回 400 与可读错误；读取侧取合并后配置。
- 失败与可观测性：检查点整体 try/except，任何环节异常（registry 读取失败、写盘失败等）不中断 daemon 主循环，记 ERROR 日志；分析 run 失败（非零退出、超时、产物文件缺失、JSON 非法）写一条 WARNING admin 告警（含 run_id 与原因），水位不推进、下一检查点自动重试；降级在 run 日志与契约产物留痕；每轮落地结果（就绪项目、条目数、草稿数、接受数、失败数）记 INFO 日志。

## 溯源

- 2026-09-18 2026-09-18-add-framework-self-evolution — 新增自进化链路全部规则（就绪扫描与单飞、evolution 角色与主树直跑、逐条子代理复核与降级、产物契约、水位幂等、草稿同源 lint、接受/拒绝/删除路径、自动接受、配置节、失败可观测）
- 2026-09-19 2026-09-19-evo-item-retention-doc-tracking — 新增条目保留与自动清理（7 天 ∪ 最近 100 条并集硬删、清理独立于分析 run 在途与成败、单条失败隔离）
