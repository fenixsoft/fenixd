# 多 harness 接入
> 最后更新：2026-11-12 17:36 UTC+8

多 harness 接入：以进程边界为唯一接缝（SpawnSpec 进、归一化事件出），把「换 harness」收窄为「实现 adapter + 部署注册」——HarnessAdapter 协议与 claude 字节级平移、`agent.harness` 全局开关、fenix-dsh Bundle（dsh 侧机制等价物五件套）、DshAdapter 事件投影接入、dsh 主通道真实验收与切换治理、无分配 provider 链时按 harness 自身配置的对称默认回落。run jsonl 以 claude stream-json 形状为唯一 canon、读侧零改动；CLAUDE_PID watchdog 为显式豁免面（ADR-271；原豁免面成员 dashboard 自由会话已随 2026-11-08 会话接入退役批删除）。dsh web 会话组织（分组判据 / registry 写约束 / 归档 API 通道 / 标题服务 / 会话流 append 闸写时机）的上游规则面，与 fenixd 侧会话自动卫生（确定性标题 + run 终态自动归档）也在此域。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [agent-harness-adapter](agent-harness-adapter.md) | HarnessAdapter 进程边界协议与 claude 平移（字节级等价、一次性 spawn 收编、进程识别泛化、spawn env IS_SANDBOX=1 恒注入） | 2026-11-12 17:36 |
| [harness-config](harness-config.md) | `agent.harness` 全局开关（校验、缺省、设置界面、热重载生效语义、健康检查门控） | 2026-10-30 23:11 |
| [fenix-dsh-bundle](fenix-dsh-bundle.md) | fenix-dsh Bundle 五件套（Task 工具族/三守卫/非交互审批/模型显式配置/AGENTS.md 载体）与版本钉扎 | 2026-11-03 10:59 |
| [dsh-harness-integration](dsh-harness-integration.md) | DshAdapter 接入（spawn 契约、事件投影、stderr 分类接口化、session 绑定、健康检查、prompt 注记、usage 降级、采集可观测性） | 2026-11-03 10:59 |
| [dsh-primary-acceptance](dsh-primary-acceptance.md) | dsh 主通道验收与切换治理（一键验收脚本三模式、切换/回切运行手册、真实验收人工信号式触发、缺省翻转人工裁决） | 2026-10-30 23:11 |
| [harness-default-fallback](harness-default-fallback.md) | harness 对称默认回落（无分配按 harness 自身配置启动、bundle 侧 modelConfig 形态划界兑现 dsh 回落、部分链笔误防护划界、两层 WARN 留痕、provider_source 归因标记） | 2026-11-08 21:21 |
| [dsh-web-session-organization](dsh-web-session-organization.md) | dsh web 会话组织上游规则面（workspace 分组 cwd 精确匹配判据、registry 无跨进程写锁、归档 HTTP API 通道与鉴权凭据、标题服务三来源与 limits 必填、会话流 append 闸写时机）；fenixd 消费见 dsh-session-hygiene | 2026-11-09 17:00 |
| [dsh-session-hygiene](dsh-session-hygiene.md) | fenixd 侧 dsh 会话自动卫生：bundle 侧启动期确定性标题（spawn env 派生、120 字节截断、resume 幂等、append 闸下 queueMicrotask 推迟落盘）+ daemon 侧 run 终态自动归档（终态挂接落点全执行面枚举、会话捕获按 attempt 列表登记、终态全量逐 id 投递、Node helper 投递、退出码三分类、事件驱动重试队列与放弃阈值、失败安全）与配置键 | 2026-11-09 20:13 |
