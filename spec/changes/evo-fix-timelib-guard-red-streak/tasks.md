## Deliverables

```yaml
- path: core/timelib.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: tests/test_timelib_guard.py
  kind: modify
```

## 1. 时间原语助手与违例收拢

- [ ] 1.1 core/timelib.py：新增 local_date(ts) 助手（epoch 秒 → 本地时区 date，本地日分桶唯一入口），__all__ 与模块 docstring 的 API 清单同步追加（既有六函数契约只许 ADDITIONAL 扩展不破坏）
- [ ] 1.2 core/admin_monitor.py:4217-4218 与 :4245：三处 datetime.fromtimestamp(...).date() 收拢为 timelib.local_date(...)，保持「本地日」分桶语义逐位不变（UTC+8 下 0-8 点产物归日本地锚）
- [ ] 1.3 core/worktree_manager/mergeback.py:204-215 _extract_log_timestamp：ISO 解析收拢到 timelib.parse_ts 转发（失败返 None 语义不变，Z 后缀/偏移/小数秒归一由 parse_ts 内置），删延迟 import datetime
- [ ] 1.4 core/worktree_manager/stray_wip.py 守卫违例行 :354 所在的日志时间戳解析助手：函数体收拢为 timelib.parse_ts 转发（保留函数签名与 None 返回语义），删自定义小数秒截断；实现前核对调用方输入形态，若存在 naive 输入路径在函数注记登记 naive 解读差异（UTC → 本地）及影响面

## 2. 已知红基线机制

- [ ] 2.1 tests/test_timelib_guard.py：新增 KNOWN_RED_BASELINE 常量（条目 = (文件, 模式名, 理由, 到期日)，初始空表）并改造主断言——基线外违例非空才失败；基线条目到期日早于今日即失败（回绿时限）；基线条目违例已消失即报收缩；与 TIME_WHITELIST 棘轮正交、互不混用
- [ ] 2.2 tests/test_timelib_guard.py：新增基线机制单测三例（超期失败、命中分桶正确、违例消失报收缩）
- [ ] 2.3 tests/test_timelib_guard.py:206：更新 [fenix-ignore:4b216478bc98] 注记理由使其反映回绿事实（原「当前 0 违例」在红窗期间失真），并指明后续已知红走 KNOWN_RED_BASELINE 登记

## 3. 测试

- [ ] 3.1 python3 -m pytest tests/test_timelib_guard.py 全量绿（既有 18 用例 + 新增基线用例），守卫回绿后 core/ 无白名单外违例、无基线条目
- [ ] 3.2 定向回归受影响调用方：tests/ 下按 lane_stall、mergeback、stray_wip 关键字定位相关测试并运行，确认车道停滞记账与日志时间戳解析行为不红