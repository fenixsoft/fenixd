# dsh-web 重启与在飞会话 turn 处置

<!-- knowledge: capability=dsh-web-restart-turn-dispose rev=1
     sources=spec/knowledge/_inbox/done/dsh-web-restart-disposes-own-session-turns.md -->

dsh web 交互会话的 turn 生命周期与 `dsh-web.service` 重启的处置语义：重启即 dispose 全部在飞 turn，会话内自重启属自我终止命令——禁令与脱离配方在此。上游会话组织规则见 [dsh web 会话组织](dsh-web-session-organization.md)。

## 规则

- **进程宿主与 dispose 语义**：dsh web 交互会话的 agent 进程宿主在 `dsh-web.service` cgroup 内——`systemctl restart dsh-web` 会 dispose 该服务下全部在飞会话 turn，包括发起重启的会话自身（其 bash 子进程同组被杀）。取证注意：直接 root `systemctl` 在 `journalctl -u dsh-web` 无调用者痕迹（sudo 调用才有行可查），重启归因不能依赖 journal 调用者行。
- **会话内自重启禁令**：禁止在 dsh web 会话 turn 内直接执行 `systemctl restart dsh-web`——自我终止命令，重启必杀掉自己所在 turn，任务计划中的「重启 + 验证」永不完成，形成「续做→重启自杀→再续做」自毁反馈环。需要重启才生效的变更（如 dsh-plugins 插件更新）必须走脱离机制：`systemd-run --on-active=2s systemctl restart dsh-web.service`（或 `nohup … &`）让重启脱离本 turn 进程组；验证探针与重启后新登录 token（`?token=` 随重启轮换）的抓取转写为单脚本落盘，重启后新 turn 读文件取结果，不在同一 turn 内串行等待。
- **disposed 中止判读**：会话 jsonl 中多个 turn 以 `turn/end {reason:{kind:"aborted",reason:{kind:"disposed"}}}` 终止、且时刻与 journal 中 dsh-web 单元 Stopping/Started 秒级对齐，即服务重启 dispose 签名——属宿主服务生命周期事件，不归因模型故障或 harness 异常；受影响 turn 无需逐个恢复，重启完成后新 turn 续做即可。
- **重启来源面**：重启不止来自人工与 agent——自动更新链路也按设计重启 dsh-web（包替换后随即重启），在飞 turn 同样被 dispose；长任务跨自动更新时点应预期中断，属设计内行为。

## 代码锚点

无独立实现载体（规则面属 dsh 上游服务与本机 systemd 运维语义，非本仓代码）。

## 溯源

- 2026-11-26 dsh-web-restart-disposes-own-session-turns（spec/knowledge/_inbox/done/dsh-web-restart-disposes-own-session-turns.md） — 新建本页：dsh-web.service cgroup 宿主与重启 dispose 全部在飞 turn（含发起者自身）语义、journal 无调用者痕迹取证注意、会话内自重启禁令与脱离机制配方（systemd-run/nohup + 探针与 token 抓取落盘）、disposed 中止签名判读、自动更新重启属设计内来源
