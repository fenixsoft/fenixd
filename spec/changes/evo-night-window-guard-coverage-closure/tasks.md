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
- path: tests/test_code_fix_night_quiet_window.py
  kind: modify
- path: spec/knowledge/domains/code-fix-lane/codefix-night-quiet-window.md
  kind: modify
```

## 1. 缺省窗多窗化

- [ ] 1.1 core/code_fix.py：NIGHT_QUIET_WINDOW_DEFAULT（core/code_fix.py:3346）改为「03:00-03:15,04:15-04:45」，同步 :3340-3345 常量注释与 :3381 解析器 docstring（缺省即覆盖已观测散布断窗形态；运行时显式覆盖与空串/off 禁用语义不变）
- [ ] 1.2 .fenix/config.template.yaml：补 night_quiet_window 键文档（多窗示例值与说明），与代码注释口径一致
- [ ] 1.3 tests/test_code_fix_night_quiet_window.py:174：源码契约断言「NIGHT_QUIET_WINDOW_DEFAULT = "04:15-04:45"」同步为多窗缺省字面量（沿 evo-add-review-night-defer-snapshot-writeoff 4.4 先例：契约文本随实现同步更新，MUST NOT 静默放宽契约）
- [ ] 1.4 缺省字面量同步消费面：fenixd.py:4525 CODE_FIX_RESULT_MESSAGES["night_quiet_window"] 用户文案「默认 04:15-04:45」改为多窗口径；spec/knowledge/domains/code-fix-lane/codefix-night-quiet-window.md 缺省值描述同步

## 2. 自进化车道窗避让

- [ ] 2.1 fenixd.py：_check_evolution_checkpoint（fenixd.py:4843 一带）派发前新增预计跨窗判定——守卫落在保留清理之后、单飞判定与派发之前（prune 不因窗顺延跳过）；复用 core.code_fix._parse_night_quiet_windows 解析窗列表，配置读同键 admin.code_review_fix.night_quiet_window、缺省 NIGHT_QUIET_WINDOW_DEFAULT（不引入第二份窗配置/第二键），读取/解析/导入异常按无窗 fail-open；时长估计取近几轮自进化归档 run_metrics duration_s（样本策略对齐 core/admin_monitor.py:1992-2050），命中任一窗即本轮跳过并写 reason=night_quiet_window_deferred 日志（仅宿主层 fenixd.py，不落 maintenance_runs/event_bus），不消费水位/就绪标记
- [ ] 2.2 守卫写在 fenixd.py 检查点层，MUST NOT 把 night_quiet 关键字引入 core/agent_runner/maintenance_runs.py 与 event_bus.py（tests/test_code_fix_night_quiet_window.py:538-539 assertNotIn「night_quiet_window」子串契约——reason 值 night_quiet_window_deferred 含该子串，同样不得落入）

## 3. 派发前连通预检

- [ ] 3.1 core/agent_runner/runner.py：_run_agent（runner.py:5985 一带，Popen :6138）派发前加轻量连通探测（socket.getaddrinfo 解析 API 域名；getaddrinfo 无原生超时参数——独立线程 join(2-3s) 判超时），失败则顺延本轮派发并写含 reason 的跳过日志；探测自身异常记日志后放行（fail-open）；仅挂派发前，不影响在飞 run
- [ ] 3.2 预检按 agent_type 白名单仅作用于维护车道派发（evolution/code-review/code-fix/administrator/self-review）；_run_agent 实测同时服务 dispute-judge（runner.py:1618）、spec-review（:1839）、impl 派发族（:3530）、regression（maintenance_runs.py:2848 run_regression）——这些车道与交互式 run 一律不做探测顺延（对齐 proposal Out of Scope「不动 spec-review/regression 车道派发时点」）

## 4. 测试与回归

- [ ] 4.1 tests/test_night_window_dispatch_guard.py：覆盖缺省多窗解析（「03:00-03:15,04:15-04:45」解析两窗、单窗输入行为不变、空串/off 禁用）
- [ ] 4.2 tests/test_night_window_dispatch_guard.py：覆盖自进化检查点跨窗顺延（stub 归档时长使预测入窗→跳过且水位/就绪标记不动；预测不入窗→照常派发）
- [ ] 4.3 tests/test_night_window_dispatch_guard.py：覆盖连通预检（stub getaddrinfo 失败→顺延＋跳过日志；stub 抛异常→放行派发）
- [ ] 4.4 回归：tests/test_code_fix_night_quiet_window.py 全绿（关键字缺席契约＋既有单窗/多窗行为）