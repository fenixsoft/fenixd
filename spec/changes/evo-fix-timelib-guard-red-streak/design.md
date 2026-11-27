# 设计：timelib 守卫回绿与已知失败基线治理

## D1. timelib 新增 local_date 助手

core/timelib.py 追加（API 契约 ADDITIONAL 扩展，__all__ 与模块 docstring 的 API 清单同步追加）：

```python
def local_date(ts):
    """epoch 秒 → 本地时区 date（本地日分桶唯一入口）。"""
    return datetime.fromtimestamp(ts).date()
```

timelib.py 本体在扫描豁免清单内，内部用底层 fromtimestamp 合法；无 tz 的 fromtimestamp 返回本地 naive，.date() 即本地日——与 admin_monitor 现语义逐位一致。

## D2. 三处调用点收拢

- core/admin_monitor.py:4217-4218（车道停滞 run_metrics 记账）：day/today 两行改 timelib.local_date(mtime) / timelib.local_date(now)。语义保持：mtime 是本地墙钟近端锚，「非今日收尾产物不计今日」的本地日分桶语义不变（UTC+8 下 0-8 点产物归日本地锚）。
- core/admin_monitor.py:4245（车道×日阈值评估）：today 改 timelib.local_date(time.time())。
- core/worktree_manager/mergeback.py:204-215 _extract_log_timestamp：函数体收拢为 timelib.parse_ts 转发（延迟 import timelib；parse_ts 对 Z 后缀/±HHMM 偏移/小数秒位数的归一全部内置；失败返 None 与现 except 语义一致；naive 输入按本地解读与现 fromisoformat naive → .timestamp() 的本地解读一致），删除延迟 import datetime。
- core/worktree_manager/stray_wip.py 守卫违例行 :354 所在的日志时间戳解析助手：函数体收拢为 timelib.parse_ts 转发（保留函数签名与 None 返回语义），删自定义小数秒右补零截断逻辑（与 timelib._fromiso_compat 归一重叠）。语义注记：现实现对 naive 输入补 UTC，parse_ts 按本地解读——实现时先核对调用方输入形态（生产写侧 isoformat 产物恒带时区），若确认存在 naive 输入路径，在函数注记登记解读差异（UTC → 本地）及其影响面。

## D3. KNOWN_RED_BASELINE 机制

tests/test_timelib_guard.py 新增常量与主断言改造：

- KNOWN_RED_BASELINE: list = []（条目 = (仓库相对路径, 模式名, 理由, 到期日 "YYYY-MM-DD")；本案五处违例修复后初始保持空表）。
- 主测试 test_current_production_zero_non_whitelist_violations 改造：violations 按 (rel, pattern) 与基线比对分桶——基线外非空 → 失败（现状文案）；基线条目到期日 < 今日（timelib.now_utc() 转本地日）→ 失败并列出超期条目（回绿时限）；基线条目在违例中无命中 → 失败提示收缩（僵尸检测同款文案）。
- 新增单测：超期基线条目报失败；基线命中分桶正确（基线内不计失败）；基线条目违例消失报收缩。

## D4. 注记治理

tests/test_timelib_guard.py:206 的 [fenix-ignore:4b216478bc98] 注记：理由「当前 0 违例」在红窗期间失真。回绿后更新理由文本为反映事实的表述（提及 2026-11-16 三交付五违例已收拢回绿、后续已知红走 KNOWN_RED_BASELINE 登记），保留注记本体（仅为注释，不影响守卫运行，避免触碰 code-fix 消费端匹配）。

## D5. 验证

- python3 -m pytest tests/test_timelib_guard.py 全量绿（18 用例 + 新增基线用例）。
- 受影响调用方定向回归：admin_monitor 车道停滞记账相关测试、worktree_manager mergeback/stray_wip 日志解析相关测试（tests/ 下按 lane_stall、mergeback、stray_wip 关键字定位）不红。