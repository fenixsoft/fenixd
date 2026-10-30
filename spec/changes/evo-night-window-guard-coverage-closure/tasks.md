## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_night_window_dispatch_guard.py
  kind: new
```

## 1. 缺省窗多窗化

- [ ] 1.1 core/code_fix.py：NIGHT_QUIET_WINDOW_DEFAULT（core/code_fix.py:3249）改为「03:00-03:15,04:15-04:45」，同步 :3245-3247 与 :3280 附近注释（缺省即覆盖已观测散布断窗形态；运行时显式覆盖与空串/off 禁用语义不变）
- [ ] 1.2 .fenix/config.template.yaml：补 night_quiet_window 键文档（多窗示例值与说明），与代码注释口径一致

## 2. 自进化车道窗避让

- [ ] 2.1 fenixd.py：_check_evolution_checkpoint（fenixd.py:4504 一带）派发前新增预计跨窗判定——复用 core.code_fix._parse_night_quiet_windows 解析窗列表，时长估计取近几轮自进化归档 run_metrics duration_s（样本策略对齐 core/admin_monitor.py:1865-1921），命中任一窗即本轮跳过并写 reason=night_quiet_window_deferred 日志，不消费水位/就绪标记
- [ ] 2.2 守卫写在 fenixd.py 检查点层，MUST NOT 把 night_quiet 关键字引入 core/agent_runner/maintenance_runs.py 与 event_bus.py（tests/test_code_fix_night_quiet_window.py:512-513 契约）

## 3. 派发前连通预检

- [ ] 3.1 core/agent_runner/runner.py：_run_agent（runner.py:5842 Popen 一带）派发前加轻量连通探测（socket.getaddrinfo 解析 API 域名、2-3 秒超时），失败则顺延本轮派发并写含 reason 的跳过日志；探测自身异常记日志后放行（fail-open）；仅挂派发前，不影响在飞 run
- [ ] 3.2 预检作用域限于维护车道派发路径；如该入口同时服务用户交互式 run，以 run 类别区分、交互式 run 不做探测顺延

## 4. 测试与回归

- [ ] 4.1 tests/test_night_window_dispatch_guard.py：覆盖缺省多窗解析（「03:00-03:15,04:15-04:45」解析两窗、单窗输入行为不变、空串/off 禁用）
- [ ] 4.2 tests/test_night_window_dispatch_guard.py：覆盖自进化检查点跨窗顺延（stub 归档时长使预测入窗→跳过且水位/就绪标记不动；预测不入窗→照常派发）
- [ ] 4.3 tests/test_night_window_dispatch_guard.py：覆盖连通预检（stub getaddrinfo 失败→顺延＋跳过日志；stub 抛异常→放行派发）
- [ ] 4.4 回归：tests/test_code_fix_night_quiet_window.py 全绿（关键字缺席契约＋既有单窗/多窗行为）