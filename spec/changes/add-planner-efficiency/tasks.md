## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/ParallelSettingsPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: bin/gen-route-map.py
  kind: new
- path: bin/analyze_run_latency.py
  kind: new
- path: tests/test_planner_route_map.py
  kind: new
- path: tests/test_planner_throttle.py
  kind: new
- path: tests/test_run_latency_stats.py
  kind: new
```

## 1. 路由地图生成协议（planner-route-map）

- [x] 1.1 `verification.py` 阶段1 进入处（run_planner 前）接入地图生成：发现 `bin/gen-route-map.py` → 以 impl worktree 为根执行（超时 60s）→ 写 `<worktree>/.fenix/route-map.md`；复用键=worktree HEAD（未变跳过）；失败/缺生成器 fail-open 记 warning
- [x] 1.2 静态地图兼容：无生成器地图时回退主树 `.fenix/route-map.md`；两者皆无则不注入
- [x] 1.3 `prompt_builder.py` `_project_extra_section` 新增 route-map 段：注入地图全文 + 钉死措辞「已知入口索引、非穷尽清单；spec 涉及但地图未覆盖的入口仍须自行源码取证」
- [x] 1.4 `bin/gen-route-map.py` dashboard 参考实现：扫 server.py 路由表 + SPA hash 路由 + 关键 data-testid，条目含 `文件:行号` 出处；内置自检（宽 grep 启发式计数 vs 解析条目数，差 ≥30% 输出 warning）
- [x] 1.5 `tests/test_planner_route_map.py`：生成触发/HEAD 复用/HEAD 变更重生成/注入措辞/无生成器回退/生成器失败不阻塞/静态地图注入/自检告警

## 2. planner 生成节流（planner-generation-throttle）

- [x] 2.1 `agent_runner.run_planner` 入口加跨管线信号量：`verify.planner_max_concurrent`（0/缺省=不节流），BoundedSemaphore 按配置惰性重建（热更新生效），try/finally 释放（取消/异常不泄漏）
- [x] 2.2 排队可观测：等待信号量时打 INFO 日志（spec 名+等待序位）；等待期 run 保活事件（防 stuck 误判，设计 D2 备选方案）
- [x] 2.3 `ParallelSettingsPanel.tsx` 新增「planner 生成节流」Switch（默认关）+ 上限 InputNumber（1-10）+ 注解文案（限什么/为什么/代价三点）；`dashboard.ts` 配置读写通道
- [x] 2.4 `tests/test_planner_throttle.py`：上限生效/缺省不节流/取消释放/冻结复用零节流/配置热更新生效

## 3. run 级 API 延迟直方图（run-latency-observability）

- [x] 3.1 `runner.py` `_run_claude` 流式循环旁路延迟统计：`_parse_event_timestamp` 读侧记录「tool_result → assistant」间隔样本；成功/失败/取消统一 run 末摘要日志（轮数/中位/p90/max/长尾>60s 计数与占比，含 run_id）
- [x] 3.2 失败 run 错误上下文附延迟摘要（卡死 vs 慢可判）
- [x] 3.3 `bin/analyze_run_latency.py`：历史转录批量扫描（与在线同口径，复用公共解析函数），按 p90 排序，损坏/空文件跳过并报告
- [x] 3.4 `tests/test_run_latency_stats.py`：摘要行口径/失败附证/脚本批量与容错/统计不改流式行为

## 4. 回归与收尾

- [ ] 4.1 全量测试回归（tests/ 全绿，含 prompt/verify/throttle 相关既有套件）
- [ ] 4.2 dashboard 设置页 UI 手动验证（并发度页签开关持久化、注解可见）+ dist 重建不入库
- [ ] 4.3 自举验证：fenixd 主树生成器对本项目产出地图，planner prompt 含 route-map 段
