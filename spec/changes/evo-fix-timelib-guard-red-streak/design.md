# 设计：timelib 守卫回绿与已知失败基线治理

## D1. （2026-11-27 复评修订：已降级，不新增 local_date）

原设计拟新增 local_date（epoch 秒 → 本地时区 date）。外部 code-fix batch 4fec3994c（2026-11-21）已先行合入等效守卫修复：admin_monitor 日桶收拢 timelib.from_epoch（UTC 日桶，对齐「存储与计算层 aware UTC」分层约定，见 core/admin_monitor.py:4340 收拢注记），守卫回绿、零豁免稳态保持。本 SPEC 不再新增 local_date——新增本地日入口与已合入的 UTC 日桶语义相反且将零调用方；日桶如需改本地分桶属行为变化，另行立项。timelib 六函数契约保持不变。

## D2. （已由外部 4fec3994c 完成，2026-11-27 复评修订收缩为只读核对）调用点收拢现状核对

迁移已由 4fec3994c 合入主树，本节改为实现时的只读核对清单（不触碰生产文件）：

- core/admin_monitor.py 日桶（现 :4342-4343、:4448，及同族 :4607、:4642）：均为 timelib.from_epoch(...).date()（UTC 日桶），无裸 fromtimestamp 残留（守卫绿即证）。
- core/worktree_manager/mergeback.py:235 _extract_log_timestamp：已收拢为 timelib.parse_ts 转发（延迟 import，失败返 None 语义保持，现签名返 Optional[float]）。
- core/worktree_manager/stray_wip.py:339-350 日志时间戳解析助手：已收拢 timelib.parse_ts 唯一入口，小数秒归一由 parse_ts 内置。
- 核对若发现与上述形态不符的残留（不应发生），按守卫失败路径登记 KNOWN_RED_BASELINE 或另行立项，不在本 SPEC 内顺手改写。

## D3. KNOWN_RED_BASELINE 机制

tests/test_timelib_guard.py 新增常量与主断言改造：

- KNOWN_RED_BASELINE: list = []（条目 = (仓库相对路径, 模式名, 理由, 到期日 "YYYY-MM-DD")；本案五处违例修复后初始保持空表）。
- 主测试 test_current_production_zero_non_whitelist_violations 改造：violations 按 (rel, pattern) 与基线比对分桶——基线外非空 → 失败（现状文案）；基线条目到期日 < 今日（timelib.now_utc() 转本地日）→ 失败并列出超期条目（回绿时限）；基线条目在违例中无命中 → 失败提示收缩（僵尸检测同款文案）。
- 新增单测：超期基线条目报失败；基线命中分桶正确（基线内不计失败）；基线条目违例消失报收缩。

## D4. 注记治理（2026-11-27 复评修订收缩）

tests/test_timelib_guard.py:206 的 [fenix-ignore:4b216478bc98] 注记：原「当前 0 违例」失真已随外部回绿（4fec3994c）自愈，注记现为事实表述且自带迁移溯源。本节任务收缩为：随 KNOWN_RED_BASELINE 落地在注记末尾补记「后续已知红走 KNOWN_RED_BASELINE 登记」通道说明一句，保留注记本体与其余文本不动（仅为注释，不影响守卫运行，避免触碰 code-fix 消费端匹配）。

## D5. 验证

- python3 -m pytest tests/test_timelib_guard.py 全量绿（既有 18 用例 + 新增基线用例）。
- 外部修复态定向回归：tests/test_lane_stall_accounting.py、tests/test_timelib.py 不红（复评实测 48 passed，确认 4fec3994c 合入的 from_epoch 日桶与 parse_ts 收拢在调用方无回归）。