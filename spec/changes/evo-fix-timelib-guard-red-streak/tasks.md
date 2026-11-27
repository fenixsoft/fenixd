## Deliverables

```yaml
# 2026-11-27 复评修订：五处违例迁移已由外部 4fec3994c 合入（from_epoch / parse_ts）、
# 设计 D1 已降级不新增 local_date，四个生产文件本 SPEC 不再触碰，交付收缩为守卫测试文件。
- path: tests/test_timelib_guard.py
  kind: modify
```

## 1. 违例收拢（已由外部 4fec3994c 完成，2026-11-27 复评修订收缩为只读核对）

- [x] 1.1 只读核对（不触碰生产文件）：core/admin_monitor.py 日桶（:4342-4343、:4448 及同族 :4607、:4642）均为 timelib.from_epoch（UTC 日桶）、core/worktree_manager/mergeback.py:235 _extract_log_timestamp 与 core/worktree_manager/stray_wip.py:339-350 解析助手均为 timelib.parse_ts 转发，守卫无白名单外违例；core/timelib.py 不新增 local_date（设计 D1 已降级），六函数契约不变

## 2. 已知红基线机制

- [x] 2.1 tests/test_timelib_guard.py：新增 KNOWN_RED_BASELINE 常量（条目 = (文件, 模式名, 理由, 到期日)，初始空表）并改造主断言——基线外违例非空才失败；基线条目到期日早于今日即失败（回绿时限）；基线条目违例已消失即报收缩；与 TIME_WHITELIST 棘轮正交、互不混用
- [x] 2.2 tests/test_timelib_guard.py：新增基线机制单测三例（超期失败、命中分桶正确、违例消失报收缩）
- [x] 2.3 tests/test_timelib_guard.py:206：在 [fenix-ignore:4b216478bc98] 注记末尾补记「后续已知红走 KNOWN_RED_BASELINE 登记」通道说明一句（原「当前 0 违例」失真已随外部回绿自愈，注记本体与其余文本保持不动）

## 3. 测试

- [x] 3.1 python3 -m pytest tests/test_timelib_guard.py 全量绿（既有 18 用例 + 新增基线用例），core/ 无白名单外违例、KNOWN_RED_BASELINE 无条目
- [x] 3.2 定向回归确认外部修复态：python3 -m pytest tests/test_lane_stall_accounting.py tests/test_timelib.py 不红（4fec3994c 合入的 from_epoch 日桶与 parse_ts 收拢在调用方无回归）