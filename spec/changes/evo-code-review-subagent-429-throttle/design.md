# 设计：审查子代理 429 节流与退避

## 现状结构

- 在飞上限注入链：agents/code-review.md:39 模板条款（{repo_concurrency} 占位，即既有 SPEC add-code-review-concurrency-and-429-resilience 的落地产物）→ core/agent_runner/prompt_builder.py:2449/2466 注入（detail 缺失/脏值时 fail-open 回退读取器缺省 4）→ core/config.py:4969-4971 get_repo_code_review_concurrency（缺省 4，_positive_int_reader；docstring 明示**一键两用**：提示词侧并行扇出上限 + `ocr scan --concurrency <n>` 缺省并行度）→ core/agent_runner/maintenance_runs.py:3069 传值。
- 既有 429 防线全在 run 终态/provider 级：core/provider_circuit.py:73-91（429/[1302]/rate_limit 三签名分类）、:92-109（重置时间解析）、:110-112（RATELIMIT_REDISPATCH_MAX=1）；runner 收尾仅 `not run_ok and claude_error` 时归因登记（maintenance_runs.py:3663-3689 `_ratelimit_redispatch_on_terminal`）→ core/admin_monitor.py:2843（`getattr(result, "ratelimit_redispatch")` 意图消费，2850 stall_intent 同骨架）+ maintenance_runs error 收场抢救。**run 内子代理死亡（run 主体存活、最终正常收场）不落任何防线**——本 SPEC 的靶面，与 proposal 问题 2 断言一致。
- 关键约束：审查子代理由 run 主体（claude CLI Task 工具）派发，框架代码不在派发路径上——行为面唯一可控通道是 prompt 契约；观测面需「run 主体自报 + 框架收尾解析」两段接力（见决策 2）。

## 设计决策

1. 行为面走契约：429 记忆、指数退避、止损规则写入 agents/code-review.md 由 run 主体执行；框架不做进程内节流器——派发不经框架代码，进程内节流无处安放。退避等待与 code-review.md 既有「禁 async 等待收工」（:44）不冲突：轮询等待期间继续自审未派发文件，不是收工。
2. 观测面走终态标记，物理载体为**完成统计行**：code-review.md:150 既有「回复只报统计：`N files reviewed -> {out_path}`」契约是 run 主体终态输出的唯一固定锚点——风暴时允许（且仅允许）在该统计行末追加标记段 `[review_429_storm=true; failed_shards=<n>]`。runner 收尾本就持有 run 的 result 事件文本（maintenance_runs.py:3677 `result_text=claude_result_text` 同源），按既有 429 归因同骨架解析标记、回填 CodeReviewResult 新字段（review_429_storm / failed_shards），admin_monitor 沿用既有 getattr 意图消费模式（admin_monitor.py:2843 ratelimit_intent 同款）读取并产生 admin 告警，同 run 去重。MUST NOT 让 run 主体另写 sidecar 文件（code-review.md:8「唯一允许的写操作」条款不动）；run 主体漏报时字段保持缺省，降级为「无风暴告警」，不产生假阳性。
3. 缺省并发降 2：改 core/config.py:4969-4971 缺省常量与 prompt_builder fail-open 回退值（4→2），配置键与读取器语义不动。**一键两用声明**：该键同时是 `ocr scan --concurrency` 缺省并行度（config.py:4970 docstring），降档对两通道同时生效——接受 ocr scan 缺省并行度同步降为 2（显式配置不受影响；code-review 车道自身已不调用 ocr scan，见 code-review.md:34）。**前端同源**：core/dashboard/static/src/pages/settings/components/QualityPanel.tsx:56 REPO_REVIEW_DEFAULT_CONCURRENCY（注释明示「缺省同源；模板示例值=缺省值」；:161 空值回显、:727 描述文案插值均消费）同步 4→2，避免设置页与后端生效值漂移；config_admin.py 读侧走 ConfigLoader 自动跟随，无需改。
4. 跨项目维度只提示不排程：告警 evidence 固定提示「同账户多项目审查窗口重叠，建议错峰排程」；排程协调留待该告警实际复发后再立项。
5. 与既有 run 级防线互补不重叠：run 主体被 429 打杀（not run_ok）走既有 ratelimit_redispatch 终局重派，此时风暴标记无从产生也不需要（run 已死）；风暴标记仅出现在 run 正常收场（止损自审兜底成功）时——二者按 run 终态天然互斥，无重复告警面。

## 风险

- 降并发拉长审查墙钟（死亡补审串行时更明显）——接受：墙钟成本远低于 3 死接管补审与 19-20 美元 run 成本。
- 契约条款依赖 run 主体遵从、无硬闸——接受：与 code-review.md 现有条款同级；风暴告警提供观测兜底，标记解析同为软契约，漏报只降级为无告警，无假阳性面。
