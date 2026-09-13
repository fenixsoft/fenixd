## Deliverables

```yaml
- path: core/fast_track_result.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_fast_track_scale_precheck.py
  kind: new
```

## 1. 规模预估纯函数

- [ ] 1.1 在 core/fast_track_result.py 新增 `estimate_spec_scale(spec_dir) -> int`：按 tasks.md 未勾选任务条数 + spec 目录源码文件数加权返回规模分；tasks.md 缺失或读取失败记 WARNING 返回低档分
- [ ] 1.2 新增 `budget_tier_for_scale(scale) -> str`：按 design D1 阈值返回档位（normal / higher / full），阈值常量固化并注释样本依据

## 2. 派发预检接入

- [ ] 2.1 core/pm_engine/dispatch.py fast-track 分支派发前调用规模预估，超阈时按档位调整 extension 上限或标记降级 full，预留日志（含 spec、规模分、档位）
- [ ] 2.2 小规模 spec 路径行为零变化（回归断言）

## 3. extension 末位自动保全

- [ ] 3.1 在 core/agent_runner/runner.py 超时监督路径新增『extension 末位窗口』判定（剩余时间 < 设计提前量常量），命中即调用 commit_wip_checkpoint（消息契约 `fenix(wip): checkpoint extension-tail <spec>`）
- [ ] 3.2 保全失败仅 WARNING 不阻断既有超时收口（降级语义与 add-impl-wip-checkpoint 一致）

## 4. 测试

- [ ] 4.1 tests/test_fast_track_scale_precheck.py：规模分档边界单测（小样/大样/输入缺失放行）
- [ ] 4.2 末位保全触发断言：模拟 extension 末位窗口进入触发 checkpoint 事件；git 失败降级不抛
