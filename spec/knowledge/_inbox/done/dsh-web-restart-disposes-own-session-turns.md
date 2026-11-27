# dsh-web restart 会 dispose 全部在飞会话 turn（含发起重启的会话自身）

- 日期：2026-11-26
- 域：harness-integration / daemon-runtime
- 现象：会话 session-e0ba7f25-b687-4113-9b6f-2123023b66e2 一天内 11 个 turn 中 10 个以 `turn/end {reason:{kind:"aborted", reason:{kind:"disposed"}}}` 终止（08:43、08:57、08:59、09:17、09:21、09:22、09:23、14:57、14:59×2），表现为"多次自动中断"。
- 根因：每次中断秒级对应 `systemctl restart dsh-web.service`（journal dsh-web 单元 Stopping/Started 与会话 jsonl 中止时刻逐一对齐）。DSH web 会话的 agent 进程宿主在 dsh-web.service cgroup 内，重启即 dispose 所有在飞 turn——包括发起重启的会话自己（bash 子进程同组被杀，journalctl -u dsh-web 里 sudo 行只在用 sudo 时出现，直接 root systemctl 无调用者痕迹）。
- 执行者归因：10 次中 9 次是 e0ba7f25 自己的 turn 内 bash 调用（任务为 fenix-dsh-dashboard-bridge 插件 i18n 修复，需重启 dsh-web 生效并轮换 ?token= 登录令牌），1 次（09:17:07）来自兄弟会话 d493c1b0（同插件 rc.5 验证循环）。用户每次续做→任务计划含"重启+playwright 验证"→重启又杀掉自己 turn→验证永不完成→再续做再重启，形成自毁反馈环（09:21–09:23 与 14:57–14:59 两个三连）。
- 教训/规则：**禁止在 dsh-web 会话 turn 内直接 `systemctl restart dsh-web`**（自我终止命令）。需应用插件变更时用脱离机制：`systemd-run --on-active=2s systemctl restart dsh-web.service` 或 `nohup … &`（转写验证探针+token 抓取为单脚本落盘，重启后新 turn 读文件取结果）。
- 关联：d493c1b0 会话内另有「restart dsh-web ×13」历史排查摘要与 04:32 自动更新重启（包替换 04:32:11、服务重启 04:32:24）；另有无关但值得关注的 systemd 崩溃循环单元 `fenixd-test-unavailable-raises-readab0-3bb1a1`（CHDIR 失败，重启计数 25 万+）。
