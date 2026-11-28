# FRP dashboard 公网端口迁移：18787 → 8787（2026-11-28）

## 变更

- 两条 FRP 隧道的 `dashboard` 代理（本机 127.0.0.1:8787 → 公网端口）由 remotePort 18787 改为 8787：
  - `/etc/frp/frpc.toml`（frpc.service → frps 134.175.54.198，域名 frp.icyfenix.cn）
  - `/etc/frp/frpc-remote.toml`（frpc@remote.service → frps 64.90.17.236，域名 home.icyfenix.cn）
- 配置备份：`/etc/frp/*.bak-20261128-093220`。
- 重启方式遵守既有纪律：`systemctl restart frpc` + `systemctl restart frpc@remote`，禁用 nohup 裸进程。

## 验证（2026-11-28 09:32）

- `http://home.icyfenix.cn:8787/` → HTTP 200
- `http://frp.icyfenix.cn:8787/` → HTTP 200
- 旧地址 `http://home.icyfenix.cn:18787/` → 连接失败（已下线）

## 对外地址约定同步更新

- `~/.agents/AGENTS.md`、`~/.claude/CLAUDE.md`：原型交付公网地址 18787 → 8787（纯 HTTP 无 TLS，禁用 https）。
- `skills/fenix-ui-debug/SKILL.md` 对外交付地址纪律同步改为 `http://home.icyfenix.cn:8787`。

## 影响与注意

- dashboard 公网形态不变：仍是纯 HTTP 非 secure context，`navigator.clipboard` 缺失与降级路径的前提不变（见 ADR-361）。
- 历史知识记录（ADR-361、`_inbox/done/*`、早期排查记录）中的 `home.icyfenix.cn:18787` 为当时事实，不回改。
