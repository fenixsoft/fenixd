# Design: improve-run-lifecycle-governance

## Context

2026-08-27 事故实证链（详见 proposal）：`core/agent_runner.py:1181` 取 `agents.run_timeout_seconds`（默认 3600）做纯墙钟 deadline，`core/agent_runner.py:1289-1326` 到点无条件杀进程；attempt N 失败后同一工作线程立即在同 worktree 内启动 attempt N+1（resume），而 `core/pm_engine.py` 的 BLOCKER CHECK 对「stuck ≥60m」执行 auto-recovery 时既不感知存活子进程也不释放 `core/worktree_manager.py:44-52` 的内存锁集合 `_spec_locks`；此后 `_on_spec_ready`（pm_engine.py:116）被 `has_active_worktree` 护栏拦下，~5s×3 重试瞬时耗尽标记 retries exhausted；巡检组件只盯 in-progress 态，假 ready 全程盲视约 1 小时，直到孤儿进程自然超时自愈。

相关既有能力（本设计不修改其需求）：`retry-resume`、`provider-fault-fuse`（网关瞬时故障如 unrecognized_model 归其职责）、`agent-cost-control`、`admin-health-monitor`。

## Goals / Non-Goals

**Goals:**
- 运行时限从「墙钟硬杀」升级为「活性评估 + 受限续期」，且绝对上限封闭成本风险
- auto-recovery 与真实运行时状态（存活子进程、worktree 锁）强一致；锁支持重启后按进程表重建
- 派发遇锁冲突退避重试而非瞬时耗尽；恢复动作之后必有闭环复查；假就绪滞留纳入巡检并触发 Administrator

**Non-Goals:**
- 不改动 agent_runner 内部的 attempt/resume 串联机制本身
- 不处理 inferaiapi 等网关瞬时故障的识别与退避（归 `provider-fault-fuse`）
- 不改 Dashboard UI（巡检告警经既有 Administrator 通路与 admin activity view 呈现）

## Decisions

**D1 活性评估数据源 = run jsonl 流统计 + 有活动才问 LLM。**
run jsonl 每行已含 timestamp/uuid/tool_use 结构。判定流程：取判定窗口（默认 10 分钟）内事件数、tool_use 数与最后事件距此刻的间隔；窗口内**零事件**则跳过 LLM 直接判停滞（省一次调用）；有活动则把窗口内事件摘要（工具名序列去重计数、最后一条输出片段）交给判定 LLM 输出 `{verdict: advancing|stagnant, evidence}`。理由：纯启发式无法区分「真推进」与「循环空转」（token-waste 事故教训：agent 可以高频产出却无进展）；全量喂转录给 LLM 成本过高。
备选否决：仅用启发式（漏判空转）；每分钟连续采样（调用过频）。

**D2 判定调用复用 fallback 模型路由，不新建 agent run。**
新增一个轻量函数直接以 SDK 单轮调用完成评估（无 provider 分配的 agent 类型沿用 `agents.subagent_model` 的默认网关路径，同 admin agent）。不落 .fenix/runs 正式 run 文件，判定结论写入被监督 run 的 jsonl 与 daemon 日志即可。

**D3 续期 = deadline 顺延 + 同步顺延 stuck 检测基准。**
单次续期 `extension_seconds`（默认 1800）、次数上限 `max_extensions`（默认 2）、总上限 `absolute_max_seconds`（默认 7200，命中即无条件终止）。每次续期 MUST 把顺延后的时间基准通知调度侧（写 spec 内存注册表并由 pm_engine 的 stuck 计算读取），确保不会出现「agent 还活着却被 stuck 规则重置」——这正是本次事故的第 3 环根因。

**D4 存活探测 = 进程表扫描为主、流文件新鲜度为辅。**
`agent_runner.has_live_attempt(spec)`：pgrep 匹配 cmdline 含 `.claude/worktrees/{impl,verify}-<spec>-*` 的 claude 进程；不可用时回退「run 文件 mtime < 120s」。worktree_manager 新增 `refresh_locks()`：daemon 启动首扫 + `has_active_worktree` 疑似陈锁（在册但扫描不到进程且文件不再增长）时回收再返回。reason：锁是内存集合，daemon 重启/孤儿 resume 两类场景都需要以进程为唯一真相。

**D5 锁冲突退避 = 固定序列计划，不动 attempt 配额。**
`pm.dispatch_backoff_schedule` 默认 `[30, 120, 600]` 秒。派发因锁冲突被拒时不调 `_retry_count`、不写 retries exhausted，spec 保持 ready 并在其 error 字段注明下次尝试时间；序列耗尽 → 发出 `dispatch_stalled` Administrator 信号（severity major）。锁最终释放由下一轮成功派发自然收敛。
备选否决：无限重试（回归空转环，fix-fenix-token-waste 已踩过）。

**D6 闭环复查 = 内存观察项字典 + 重启持久化。**
auto-recovery 成功即登记观察项（spec、指纹、期限=`followup_check_minutes` 默认 15），条目镜像到 `.fenix/recovery_watch.json` 便于 daemon 重启后续查。到期复查通过标准：spec 已离开 ready 或已有活跃派发；否则发 `dispatch_stalled` 信号。巡检侧同时增加 ready 滞留通用规则（阈值 `ready_stall_threshold_minutes` 默认 20），并要求「No in-progress SPECs」分支不得提前 return、仍需执行非运行态扫描。信号指纹 = hash(spec+status+error 摘要)，冷却期复用 admin 告警既有去重参数风格（默认 30 分钟）。

## Risks / Trade-offs

- [LLM 误判 advancing 造成长尾燃烧] → absolute_max_seconds 无条件硬封顶；判定证据全量留痕；与 `agent-cost-control` 的既有预算维度并存兜底
- [进程扫描匹配过宽把无关进程当成持锁者] → 匹配串严格锚定 worktree 目录字面量 `<prefix>-<spec>-<ts>`，并用流文件新鲜度二次确认；单测覆盖孤儿/陈锁两态
- [deferred recovery 若子进程异常长寿] → 子进程本身已被本设计的绝对上限约束必然终止；deferred 次数同时计入观察项，逾期照样触发信号
- [退避期 spec 在 Dashboard 显示 ready 但无进展造成困惑] → error 字段携带「backoff until <time>」，后续如需可视化属 Non-Goal
- [新配置键过多] → 全部键均有安全默认值；`enabled=false` 一键回到现行行为，形成整体回滚开关

## Migration Plan

1. 先落地 D4/D5/D6（纯防御面：锁重建、退避、复查巡检），不影响正常 happy path
2. 再落地 D1–D3（超时监督），配合 tests 用假时钟/桩 LLM 验证续期与封顶矩阵
3. 回滚策略：`agents.timeout_supervision.enabled=false` 即刻回到纯墙钟硬杀；其余键恢复默认即等价旧行为

## Open Questions

- 判定模型的默认取值确认沿用 `agents.subagent_model` 当前指向（默认网关上的便宜模型）即可，无需专门新键
