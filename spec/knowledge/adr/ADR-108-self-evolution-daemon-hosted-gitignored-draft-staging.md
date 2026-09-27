# ADR-108：自进化车道 daemon 宿主、草稿 gitignored 暂存、LLM 只读复核

date: 2026-09-18
status: accepted

## Context

自省 todo.md 的产出速率远超人工消化，需补齐「条目 → 独立复核 → SPEC 草稿 → 立项」下游。自省条目不可直接采信（复盘实证根因段错 1/3）；跨项目视角只在 dashboard，而执行能力（预算 / 告警 / 监督 / run 记录 / 状态机）只在 daemon。

## Decision

- 宿主与登记必须落在框架 daemon：分析 run 复用 AgentRunner 全套执行语义，接受走 StateMachine 注册、由同进程事件总线拾取——不引入第三条文件信号（文件信号「无消费者确认」是反复出问题的形态）；dashboard 不托管长任务（另建一套 run 记录 / 预算 / 监督且重启杀在飞 run）。仅自托管部署（PROJECT_ROOT == FRAMEWORK_ROOT）启用。
- 草稿全程存 gitignored 暂存区，未注册 SPEC 目录不得落 spec/changes/：daemon 只认 STATE.md 注册，未跟踪目录会与主树 stash / merge-back 相互作用（历史两次熔断）。接受时四步一次做完——复制 → 仅 git add 该目录 → 提交 → 注册 drafted → 删暂存（先提交后注册，任一步失败不留半成品）；拒绝是纯删除零残留。
- LLM 子代理只读复核、产出契约 JSON（判定 + 证据 + SPEC 文本），落盘 / lint / 注册全部由确定性框架代码执行：与 daemon 晋升同源的 lint 硬门不过即 draft_failed 不落地——确定性环节交给 LLM 会让失败模式发散。
- 去重权威 = 条目库已有 id 集合（凡在库不再分析、不再生成草稿）；水位只承担触发判据不承担去重。人工同意与自动接受共用同一实现（只差 decided_by 与终态名），防双路径语义漂移；全局开关存用户级配置并必须带界面。

## Consequences

- 主树 git 状态任何时刻不引入新未跟踪文件；默认人工闸门，自动接受受单轮条目上限与热更新开关约束。
- 复核结论必须引用可核对证据、核实不了写「未核实」，供人工快速识别水货结论。
