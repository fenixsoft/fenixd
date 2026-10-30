# 多 harness 接入
> 最后更新：2026-10-30 23:11 UTC+8

多 harness 接入：以进程边界为唯一接缝（SpawnSpec 进、归一化事件出），把「换 harness」收窄为「实现 adapter + 部署注册」——HarnessAdapter 协议与 claude 字节级平移、`agent.harness` 全局开关、fenix-dsh Bundle（dsh 侧机制等价物五件套）、DshAdapter 事件投影接入、dsh 主通道真实验收与切换治理。run jsonl 以 claude stream-json 形状为唯一 canon、读侧零改动；dashboard 自由会话与 CLAUDE_PID watchdog 为显式豁免面（ADR-271）。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [agent-harness-adapter](agent-harness-adapter.md) | HarnessAdapter 进程边界协议与 claude 平移（字节级等价、一次性 spawn 收编、进程识别泛化） | 2026-10-30 23:11 |
| [harness-config](harness-config.md) | `agent.harness` 全局开关（校验、缺省、设置界面、热重载生效语义、健康检查门控） | 2026-10-30 23:11 |
| [fenix-dsh-bundle](fenix-dsh-bundle.md) | fenix-dsh Bundle 五件套（Task 工具族/三守卫/非交互审批/模型显式配置/AGENTS.md 载体）与版本钉扎 | 2026-10-30 23:11 |
| [dsh-harness-integration](dsh-harness-integration.md) | DshAdapter 接入（spawn 契约、事件投影、stderr 分类接口化、session 绑定、健康检查、prompt 注记、usage 降级、采集可观测性） | 2026-10-30 23:11 |
| [dsh-primary-acceptance](dsh-primary-acceptance.md) | dsh 主通道验收与切换治理（一键验收脚本三模式、切换/回切运行手册、真实验收人工信号式触发、缺省翻转人工裁决） | 2026-10-30 23:11 |
