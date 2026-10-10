## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/code_review.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: tests/test_code_fix_night_quiet_window.py
  kind: modify
- path: tests/test_code_review_night_defer.py
  kind: new
- path: tests/test_code_review_salvage_writeoff.py
  kind: new
```

## 1. 窗模型多窗化

- [x] 1.1 core/code_fix.py：新增 `_parse_night_quiet_windows(raw)` 解析逗号/分号分隔的多窗列表（复用 `_parse_night_quiet_hhmm` 单段校验，任一段非法或 end<=start 逆序整体返回 None），`_parse_night_quiet_window` 改为薄包装（取首窗）保持旧签名与旧返回值；空串/off 禁用语义不变。
- [x] 1.2 core/code_fix.py：code-fix 守卫与 `_local_window_end_epoch` 改读窗列表——命中判定为「任一窗 start<=cur<end」，下一可投递时刻取命中窗自身 end（多窗同中取最晚），窗次武装/解除告警的窗次标识携带命中窗文本并保持按窗次幂等。
- [x] 1.3 core/admin_monitor.py：`_night_dispatch_block_reasons`（:5421）改调 `_parse_night_quiet_windows`，命中任一窗即返回对应原因短语（文案含全部命中窗区间），瞬断冻结判定不动。

## 2. 周期审查跨窗顺延

- [x] 2.1 core/admin_monitor.py：`_run_code_review_checkpoint` 在单飞判定后、manifest 收集前新增跨窗判定——读 `.fenix/runs/archive/` 下 code-review 归档 jsonl 尾部 run_metrics 的 duration_s 取最近 3 轮均值（读取异常/无样本回退仅判派发时刻落窗），派发时刻加预计时长与任一静默窗相交即返回 `{"triggered": False, "reason": "night_quiet_window_deferred"}`，MUST NOT 写同日防重状态、MUST 复位单飞标志（对齐空 manifest 分支口径），日志含预计区间与下一可派发时刻。

## 3. salvage partial 痕与 scheduled 全仓核销

- [x] 3.1 core/code_review.py：新增 `write_pending_writeoff / read_pending_writeoff / clear_pending_writeoff`（落 `.fenix/code-review/writeoff-pending.json`，flock 原子，与 items_path 同风格）。
- [x] 3.2 core/agent_runner/maintenance_runs.py：error 收场抢救 inserted 或 updated > 0 时写 pending-writeoff 锚（覆盖写）；核销资格条件（:1721）放宽为 `manual_full` 或（`scheduled` 且 `window_start is None`），redispatch/普通两分支的 `_writeoff_coverage_guard` 解锁门与 observed 非空门原样生效；核销执行且 resolved>0 或覆盖完整成功收尾时清除锚；窗口档 scheduled 与一切 error 收场维持绝不核销红线（注释固定该不变量）。
- [x] 3.3 core/admin_monitor.py：审查完成日志两处落账文案（:1676、:1917）在读到 pending-writeoff 锚时追加「部分覆盖待核销（run_id=…）」标注。

## 4. 测试

- [x] 4.1 tests/test_code_fix_night_quiet_window.py：补多窗用例——多窗配置命中第二窗取该窗末、单窗配置行为与现状逐字节一致、混合非法片段整体无窗并 WARNING 一次、多窗同中取最晚 end；时间注入沿文件内既有 patch 形态。
- [x] 4.2 tests/test_code_review_night_defer.py：覆盖跨窗顺延——样本均值推得预计区间压窗时 reason=night_quiet_window_deferred 且同日防重状态未写、单飞标志已复位；无样本回退仅判派发时刻；预计区间与窗不相交时照常派发；归档读取异常降级不阻断。
- [x] 4.3 tests/test_code_review_salvage_writeoff.py：覆盖——error 抢救写锚；scheduled 全仓 run 成功且累计覆盖完整时解锁核销（resolved>0）并清锚；agent 静默少审（累计覆盖不全）时核销锁定、open 不动；窗口档 scheduled 与 error 收场绝不核销；完成日志含待核销标注。
- [x] 4.4 全量回归核对既有源码契约断言：tests/test_code_fix_night_quiet_window.py 以 read_text 文本契约固定 code_fix.py 常量文本（:153 `NIGHT_QUIET_WINDOW_DEFAULT = "04:15-04:45"`）、checkpoint 单点不变量与「maintenance_runs.py 零 night_quiet_window 字样」（:497-510）——本 SPEC 对 code_fix.py 守卫/常量与 maintenance_runs.py 核销条件的改写触碰契约文本时同步更新对应断言，MUST NOT 静默放宽契约。