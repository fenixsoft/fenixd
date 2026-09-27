# ADR 索引

跨 SPEC 架构级决策记录。每行一条：编号链接、状态、一句话摘要；
superseded 条目保留在列供溯源。编号接续本目录既有最大号。

| 编号 | 状态 | 摘要 |
| --- | --- | --- |
| [ADR-001](ADR-001-agent-run-jsonl-protocol.md) | accepted | Agent 运行产物以 stream-json 逐行落盘 `.fenix/runs/<run_id>.jsonl`，终态行协议保证文件任何时刻可解析 |
| [ADR-002](ADR-002-model-routing-env-plus-official-model.md) | accepted | 模型路由：进程 env 承载真实 baseurl/key/model，`--model` 恒取官方名（`sdk_model`）只过 SDK 校验 |
| [ADR-003](ADR-003-agent-lane-claude-config-dir-isolation.md) | accepted | 配置了 provider 的 agent 车道必须以 `CLAUDE_CONFIG_DIR` 隔离启动，凭据走进程 env 不落盘 |
| [ADR-004](ADR-004-provider-failover-attempt-boundary.md) | accepted | provider 候选链的失效转移只在 attempt 边界推进，切换类错误驱动、4xx 维持熔断、跨 provider resume 零损上下文 |
| [ADR-005](ADR-005-strict-priority-tiered-parallel-scheduling.md) | accepted | 调度为严格优先级分档并行：同档并行至 `max_concurrent`，跨档不并行、不抢占 |
| [ADR-006](ADR-006-config-tiered-deep-merge.md) | accepted | 配置分级：用户级 `~/.fenix/config.yaml` 与项目级深度合并，项目级优先、list 整体替换、缺省键兜底 |
| [ADR-007](ADR-007-multi-project-discovery.md) | accepted | 多项目发现 = 显式注册 + 目录扫描兜底（未配置扫 `~` 一级），项目识别判据仅 `STATE.md` |
| [ADR-008](ADR-008-dashboard-zero-dependency-stack.md) | accepted | Dashboard 固定零新增依赖栈：stdlib http.server + 无构建原生前端 + vendored marked |
| [ADR-009](ADR-009-dashboard-file-endpoint-security-model.md) | accepted | Dashboard 文件读取端点统一安全模型：白名单 + kebab 校验 + resolve 后目录前缀校验，缺失返回 `found:false` |
| [ADR-010](ADR-010-dashboard-writes-via-state-machine.md) | accepted | Dashboard 对状态/配置的写回一律复用既有写入口（flock 序列化 + 原子 rename），并发为最后写者胜 |
| [ADR-011](ADR-011-auto-approve-driven-by-daemon.md) | accepted | auto 审批模式由 daemon 在 done 后执行 push 并标记 pushed；默认 manual，失败保留 done 人工兜底 |
| [ADR-012](ADR-012-admin-zero-llm-monitor-and-main-tree.md) | accepted | 自愈监视零 LLM 成本（规则检测），仅困境时唤起 Administrator；其处置直接落 main 树 |
| [ADR-013](ADR-013-task-writeback-and-completion-gate-at-transitions.md) | accepted | 任务进度回写（只增不减）与完成度门禁挂在 pm_engine 的 run 终态/状态转换点，不在 agent_runner |
| [ADR-014](ADR-014-unattended-retry-safety.md) | accepted | 无人值守重试安全：错误指纹熔断、主树脏走 stash 不 commit、daemon 单实例 flock、max_turns/续跑/孤儿清理 |
| [ADR-015](ADR-015-graceful-shutdown-drain-and-interrupted-mark.md) | accepted | 优雅退出秒级排水（SIGTERM 全部→interrupted 标记→≤10s→SIGKILL），不扩展 supervisor 窗口 |
| [ADR-016](ADR-016-dispatch-selfheal-discipline.md) | accepted | 调度自愈纪律：状态机纯记录直调补发、重发幂等不清历史字段、孤儿判定白名单、单条异常不中止整轮 |
| [ADR-017](ADR-017-fake-success-defense-fail-closed-promotion.md) | accepted | 假成功防御：rc==0 须校验 result 终态；晋级关 fail-closed、推送关 fail-open；VERIFIED→TESTING 仅限自动回退 |
| [ADR-018](ADR-018-push-main-first-sha-idempotent.md) | accepted | pushed 终态以远端内容（SHA）为准：main 先行为成功判据、分支仅审计留痕，ls-remote 去重幂等、失败有界退避超限升级人工 |
| [ADR-019](ADR-019-repair-channel-dedup-family-cap.md) | superseded | 同根缺陷双修复通道（重实现/派生子 fix）先到先得，重置/spawn/派发三边界守卫互斥；族谱深度宽度硬上限越界转人工（已随 ADR-034 原地打回退役） |
| [ADR-020](ADR-020-provider-4xx-circuit-breaker.md) | accepted | provider 4xx 熔断：判据只认解析出的状态码、状态进程内存不落盘，熔断期不动状态机不增重试计数 |
| [ADR-021](ADR-021-mergeback-conflict-selfheal-keep-merge-result.md) | accepted | merge-back 冲突自愈保 merge 结果：pop 冲突 checkout HEAD 弃 stash 版本、untracked 按分支新增路径交集移开备份，不一致副本不静默丢弃 |
| [ADR-022](ADR-022-watchdog-thresholds-derived-single-source.md) | accepted | 看门狗阈值单源派生：恢复阈值=run_timeout+固定宽限，成对时间阈值一律派生自锚点旋钮不设独立键，绝对上限联动校验 |
| [ADR-023](ADR-023-worktree-isolation-cwd-seeding-mergeback.md) | accepted | 实现车道 worktree 隔离三要素：子进程 cwd 锚定 worktree（写读同层）、SPEC 播种分支自包含、成功后框架 merge-back 回主树 |
| [ADR-024](ADR-024-agent-dispatch-thread-per-run.md) | accepted | agent 派发线程化：每运行一 worker 线程、派发即返不阻塞事件循环，max_concurrent 以计数守卫落实 |
| [ADR-025](ADR-025-run-timeout-liveness-supervision.md) | accepted | 运行时限活性监督：零事件直判停滞、有活动才问 LLM（复用 fallback 路由），续期同步顺延 stuck 基准，锁与存活唯一真相是进程表 |
| [ADR-026](ADR-026-resume-via-progress-injection-not-environment.md) | accepted | 断点续跑以进度数据注入实现，跨 attempt 不复用运行环境；与 attempt 内 --resume 续跑分属不同机制 |
| [ADR-027](ADR-027-verify-failure-deterministic-triage.md) | accepted | 验证失败分流用确定性规则：环境性失联探针后置分类、噪音/缺陷按「断言从未执行」分流，不进 prompt 不用 LLM，噪音走告警不自动改场景 |
| [ADR-028](ADR-028-verify-report-synthesis-fallback.md) | accepted | 人读验证报告缺失时由结构化数据确定性合成兜底：agent 报告优先、兜底不覆盖不静默（必发告警）、合成器单一共享实现 |
| [ADR-029](ADR-029-spec-toolchain-native-selfcontained.md) | accepted | SPEC 工具链原生自包含：原生 Python 重实现移除 npm CLI，schema vendored 随库分发，changes 目录布局契约不变 |
| [ADR-030](ADR-030-dashboard-control-plane-file-signals.md) | accepted | dashboard 控制面以文件信号驱动 daemon：server 不直接派发 agent，请求落盘由 daemon 轮询拾取，信号文件即互斥且崩溃安全 |
| [ADR-031](ADR-031-dashboard-project-lifecycle-tmux-softdelete.md) | accepted | 项目运维：daemon 启停走 tmux 会话（优雅信号优先、kill 兜底、启动幂等），软删除=ignored 忽略列表（忽略优先于显式注册） |
| [ADR-032](ADR-032-failover-chain-element-model-mapping.md) | accepted | failover 链元素级模型映射：元素 str|{provider,model} 三级解析回退、角色级 model 可选，校验改「每元素可解析」，保存整体替换防覆写 |
| [ADR-033](ADR-033-v2-frontend-vendored-amis-sdk.md) | accepted | v2 前端栈=vendored AMIS SDK+JSON DSL 页面：tarball 提取无构建链、页面 JSON 深合并单页缺失可跳过；修订 ADR-008 前端形态，其零构建/vendored 原则延续 |
| [ADR-034](ADR-034-inplace-bug-repair-no-derivation.md) | accepted | bug 修复原地打回：重置 implementing 在原 SPEC 内修复，不再派生 fix-* 子 SPEC；3 轮连续失败升级人工，通道去重/族谱治理随派生退役（推翻 ADR-019） |
| [ADR-035](ADR-035-repair-convergence-dual-counter-budget.md) | accepted | 修复收敛双计数器：验证失败轮数只在 PASS 归零（连续性），实现 run 总预算派发时递增、重派决策处设卡耗尽 blocked（总量），沉没成本放行跑完 |
| [ADR-036](ADR-036-deliverable-gate-before-merge-typed-extractor.md) | accepted | 交付物守卫 merge 前零 LLM 校验声明路径存在，提取器语境分类 deliverables/references，无法判定保守归硬校验（宁误拦不漏放），引用缺失仅审计 |
| [ADR-037](ADR-037-worktree-test-server-reverse-proxy.md) | accepted | 页面验证服务=worktree 静态资源+API/SSE 反代主服务：打真后端不跑第二实例，框架管启停注入 V2_BASE_URL，端口高位段确定性分配 |
| [ADR-038](ADR-038-v2-shell-level-sse-broadcast-bridge.md) | accepted | v2 事件架构：SSE 桥挂壳级转 sse:<type> broadcast、页面 onEvent 重拉（500ms 前缘节流）；增量数据流（run_events）自管 EventSource 快照先行 |
| [ADR-039](ADR-039-v2-adapter-pure-function-data-layer.md) | accepted | v2 数据分层：Adapters 纯函数层（UMD 双出口）是字段逻辑唯一收口，计数 Number 归一+三级回退，页面 JSON 不做字段逻辑 |
| [ADR-040](ADR-040-recovery-legacy-file-salvage-no-session-resume.md) | accepted | 死亡恢复=文件级遗产收编：worktree_manager 注册遗产获清扫豁免、prompt 注入快照、agent 只读复制进自己 worktree；跨派发会话续跑不可行不做 |
| [ADR-041](ADR-041-verify-scenario-set-freeze.md) | accepted | 验证场景集跨轮冻结：scenarios.json 持久化，修复轮只增不减、删减须理由，确定性校验器补齐不可绕过，既有场景每轮全量重跑 |
| [ADR-042](ADR-042-verdict-classification-evidence-enforced-checker.md) | accepted | 裁决强制分类+证据结构化：非 PASS 四选一并附证据，分类-状态映射采纳处强制重写，warning 连续 2 轮升级；确定性校验器把关 LLM 产物 |
| [ADR-043](ADR-043-alert-auto-resolve-condition-whitelist.md) | accepted | 告警自动闭环：写入埋 trigger、判定挂既有周期扫描，condition 白名单未识别永不闭环，人工记录不可覆盖，存量首启一次推断回填 |
| [ADR-044](ADR-044-token-accounting-at-completion-budget-alert-only.md) | accepted | token 计量收工单点采集进 STATE 内部字段（jsonl 留审计），验证链增量走侧车；预算线 80%/100% 幂等告警只告警不冻结，存量不回填 |
| [ADR-045](ADR-045-core-componentization-facade-boundaries.md) | accepted | core 巨文件组件化：组合提取+门面、组件只许单向回引门面、锁与状态同迁；测试直调组件、门面只留有生产调用者的方法 |
| [ADR-046](ADR-046-interaction-contract-prevalidation-per-assert-triage.md) | accepted | 交互契约前置校验（声明式可交互候选须有场景或展示声明）+ 豁免逐断言归因：全断言非 product-bug 才豁免，断言级豁免清单可复核 |
| [ADR-047](ADR-047-budget-counter-atomic-primitive-death-refund.md) | accepted | 预算计数单点+补偿回退：死亡 run 豁免在死亡判定点回退而非启动处预判，读改写收敛到 state_machine 锁内原子原语 |
| [ADR-048](ADR-048-admin-lane-threadpool-per-run-disposition-files.md) | accepted | admin 处置并发模型：主循环只拾取投递、线程池后台执行、处置文件按 run_id 实例分离；主循环信号拾取不得同步执行长任务 |
| [ADR-049](ADR-049-agent-prompt-files-single-source-of-truth.md) | accepted | agent 提示词文件为唯一真相（无内置副本、占位符替换、动态段归代码）；项目附加层末尾注入、缺席零注入、软链布局级防护 |
| [ADR-050](ADR-050-dashboard-incremental-data-pipeline.md) | accepted | dashboard 数据面增量化：摘要索引+签名增量重算、广播只带变更条目、前端本地归并 30s 心跳校准、连接/线程硬上限 503 |
| [ADR-051](ADR-051-signature-key-natural-invalidation-dir-level-polling.md) | accepted | 变更检测纪律：读缓存键=(路径,mtime,size) 依赖写后自然失效不维护写侧钩子；watcher 目录级签名两级跳层替代 inotify 保零依赖 |
| [ADR-052](ADR-052-state-md-field-whitelist-terminal-snapshot.md) | accepted | STATE.md 新字段必入序列化白名单；终态统计量在终态转换点快照进 STATE，读取仅终态采用持久值、脏值回退实时路径 |
| [ADR-053](ADR-053-fast-track-single-run-lane-mode-in-spec-yaml.md) | accepted | fast-track：单 run 全包四段守卫保留，mode 存 `.spec.yaml` 缺省 full fail-closed；超预算升级保分支置 implemented 不重跑；判定靠确定性硬校验兜底 |
| [ADR-054](ADR-054-mergeback-conflict-repair-branch-side-merge-main.md) | accepted | merge-back 语义冲突原地修复：git 层判定/调度层决策，repair 在分支侧合 main、主树恒干净不冻结，三态判定只信 git 事实，熔断计数不被 repair 清零 |
| [ADR-055](ADR-055-llm-via-claude-cli-no-native-client.md) | accepted | 框架不实现独立 LLM 客户端：交互场景由执行会话完成、后台场景统一 headless claude -p（参数列表传参、超时有界、失败不改原值） |
| [ADR-056](ADR-056-archive-visibility-dir-existence-periodic-governance.md) | accepted | 归档判定唯一事实源=活跃目录存在性（不写 STATE 标志）；按条目枚举 changes 必须容忍目录缺失；低频治理挂主循环周期计时而非事件埋点 |
| [ADR-057](ADR-057-task-progress-subject-contract-read-side-fallback.md) | accepted | 任务进度协议：一个任务=一个 TaskCreate=一次汇报=一次勾选（subject 内嵌编号为契约）；读侧兜底链不依赖编号（创建序回退带弱一致性门槛） |
| [ADR-058](ADR-058-dispatch-single-flight-inflight-state-protection.md) | accepted | 派发单飞守卫（异步操作前置位查重）+ 在飞态保护：失败回写不降级活跃验证态，verifier 结果竞态下重放合法路径或 blocked 留证，绝不静默丢弃 |
