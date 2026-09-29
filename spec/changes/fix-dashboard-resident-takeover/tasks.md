## Deliverables

```yaml
- path: core/dashboard/server.py
  kind: modify
- path: tests/test_dashboard_orphan_guard.py
  kind: modify
```

## 1. 接管路径常驻豁免

- [ ] 1.1 新增 `_parent_is_tmux_server(pid)` 辅助函数：读 `/proc/<pid>/stat` 取占用者 ppid（解析纪律同 `_proc_starttime`：`rpartition(")")` 后按字段取，解析失败返回 False），复用 `_is_tmux_hosted(ppid)` 判定父进程是否 tmux server
- [ ] 1.2 `serve()` 接管分支（占用者身份 starttime 复核通过后、`os.kill(SIGTERM)` 之前）加常驻判定：`_parent_is_tmux_server(occupant["pid"])` 命中时不发送任何信号，stderr 打印含占用者 PID、tmux 常驻说明与「请用 --port 指定其它端口，或直接复用常驻实例」指引的错误，`sys.exit(1)`，5 秒内退出

## 2. 单测

- [ ] 2.1 tmux 常驻占用者拒绝接管：fake 占用者（cmdline 匹配 `fenix_dashboard.py --serve`、starttime 复核通过、父进程判定为 tmux server）下启动 serve，断言未向占用者发信号（SIGTERM/SIGKILL 计数为 0）、serve 以非 0 退出、错误输出含 PID 与 `--port` 指引
- [ ] 2.2 非 tmux 旧实例仍接管：父进程非 tmux server 的 fake 占用者下，断言既有接管语义不变（收到 SIGTERM、新实例完成绑定）
- [ ] 2.3 父进程身份读取失败放行：`/proc/<ppid>` 不可读（孤儿化占用者）时按非 tmux 承载处理，走既有接管路径，不产生新报错分支

## 3. 回归

- [ ] 3.1 `tests/test_dashboard_orphan_guard.py` 全量 + dashboard 相关既有单测（test_dashboard_api 等）全绿；占用者判定新增分支不影响 watchdog 装配语义（`_start_claude_watchdog`/`_bind_parent_lifecycle` 既有用例零改动通过）
