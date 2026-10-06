# 时间原语统一模块 timelib

<!-- knowledge: capability=timelib-consolidation rev=2
     sources=spec/archive/2026-10-07-add-timelib-consolidation-layer,spec/archive/2026-10-07-add-timelib-callsite-migration -->

`core/timelib.py` 是全框架唯一的时间原语模块：一切时间的产生、解析、序列化与人读渲染都经它进行，并在此之上固化「存储 aware UTC、渲染本地时区」的分层约定，消除各模块对无时区时间戳各自解读的分叉。

## 规则

- **唯一时间原语**：`core/timelib.py` 零第三方依赖，导出六个函数——`now_utc()`（aware UTC 当前时间，等价 `datetime.now(timezone.utc)`）、`now_local()`（aware 本地时区当前时间，等价 `datetime.now().astimezone()`）、`parse_ts(value)`（唯一时间戳解析入口，接受 ISO 串含 `Z` 后缀、`+00:00` 偏移、无偏移 naive、纯日期串）、`from_epoch(ts)`（epoch 秒 → aware UTC）、`to_storage(dt)`（写侧唯一序列化）、`fmt_display(value, fmt="%Y-%m-%d %H:%M:%S")`（渲染边界转换，接受 datetime 或 ISO 串）。六函数 API 契约冻结；后续迁移批次发现缺口以 ADDITIONAL requirement 扩展函数，不破坏既有签名。
- **模块外禁直调时间原语**：`core/timelib.py` 之外的代码不得用 `datetime.now()`（零参）、`datetime.utcnow()`、`datetime.utcfromtimestamp()`、未显式指定时区的 `datetime.fromtimestamp()` 产生时间戳，不得用 `datetime.fromisoformat()` 解析时间戳，一律改走 timelib 对应函数。`core/timelib.py` 自身豁免全部禁用模式（内部即以 `fromisoformat` 实现解析）；`tests/` 目录不在约束面；`.astimezone()` 不在禁用清单（dashboard 展示路由合法在用）。
- **naive 唯一解读策略 = 本地时区**：`parse_ts` 对无时区后缀的输入统一按系统本地时区解读（机器时区固定 Asia/Shanghai、无 DST）。这是全框架唯一的 naive 解释，任何模块不得自行实现第二种 naive 解读。naive 解读只存在于读侧兼容面：生产代码零 naive 产出（见 [存量时间调用点迁移完成性契约](timelib-callsite-migration.md)），存量 naive 历史数据（jsonl/台账）按本地解读兼容读取，不做数据迁移。解析失败（非法串、空串、非字符串类型）返回 `None` 而非抛异常；需要异常语义的调用方自行包装。
- **分层时区约定**：存储与计算层一律 aware UTC；本地时区只允许出现在渲染边界（CLI 展示、knowledge 真相源盖戳、浏览器 dayjs 前端）与调度语义边界（`HH:MM` 人类时刻配置，进入计算前转为 aware UTC）。前端 dayjs 本地渲染与 `verify_engine/browser.py` 的 `timezone_id`（playwright 语义）不在本约定管辖范围。
- **知识真相源盖戳走 timelib**：`knowledge.local_now_stamp` 与 `knowledge_backfill` 同逻辑副本的时间源为 `timelib.now_local()`，输出 `("YYYY-MM-DD HH:MM", "UTC+8")` 元组、行格式 `> 最后更新：YYYY-MM-DD HH:MM UTC+8`，行尾偏移量兼容任意时区机器；盖戳助手留在 knowledge.py——盖戳是知识域领域格式，不入通用模块。
- **读侧解析单源**：`core/regression.py`、`core/dashboard/data/timeline.py` 的 `_parse_iso_ts`、`core/dashboard/routes/code_review_routes.py`、`core/evolution.py` 的 `_parse_iso` 的时间解析一律经 `timelib.parse_ts`，四处对同一 naive 串解读一致；`core/code_review.py` 与 `core/self_review.py` 不得保留私有 `_iso_to_local_dt` 实现（以 parse_ts 转发或调用点直连承载）；`core/pm_engine/verification/escalation.py` 的 `_parse_ts` 与 `core/pm_engine/recovery.py` 的 `_parse_event_timestamp` 同走 `parse_ts`（recovery 对 epoch 数值直通）。
- **AST 守卫棘轮**：`tests/test_timelib_guard.py` 复用 `tests/fenix_guards.py` 扫描基建，AST 扫描 `core/**/*.py` 与仓库根 `fenixd.py`（排除 vendored 目录），锁定五类禁用模式（零参 `datetime.now`、`utcnow`、未显式指定时区的 `fromtimestamp`、timelib 之外的 `fromisoformat`、`utcfromtimestamp`）。白名单为最小粒度键（路径 + 模式名，不含行号），只允许减少；新增未登记违例即时失败并报出文件与行号；守卫对「白名单条目已无对应违例」（僵尸条目）报失败而非警告——无失败信号的收缩会被遗忘，名单虚胖即棘轮失效。白名单为空集（零豁免稳态），棘轮语义不变：任何新违例直接报失败。

## 关键行为

- `to_storage` 对 aware UTC 与 aware 本地输入统一输出以 `Z` 结尾的 ISO UTC 串：本地 `2026-09-30 10:33 +08:00` 序列化为 `2026-09-30T02:33:00Z` 形态。
- `parse_ts` 对等价的 aware 形态返回相等的 datetime：`…T02:33:00Z`、`…T02:33:00+00:00`、`…T10:33:00+08:00` 时刻一致，aware 输入不叠加时区偏移；纯日期串 `2026-09-30` 可解析。
- `fmt_display` 按本地时区输出人读串：`2026-09-30T02:33:00Z` → `2026-09-30 10:33:00`（Asia/Shanghai）；naive 串本地进出不二次平移。
- timeline 域（deferred findings 时间轴）排序键与解析同走 parse_ts 单一策略，解析失败兜底 `datetime.max` 不回退（保持既有 P0 排序行为）；regression 守卫 stale 判定对畸形 marker JSON 判 stale 不抛异常、无 marker 判 False。

## 溯源

- 2026-10-07 add-timelib-consolidation-layer（spec/archive/2026-10-07-add-timelib-consolidation-layer） — 新增能力：timelib 六函数契约与模块外禁直调、naive 按本地唯一解读、分层时区约定、四处读侧统一与重复轮子收拢、AST 守卫棘轮（白名单只许收缩 + 僵尸条目报失败）
- 2026-10-07 add-timelib-callsite-migration（spec/archive/2026-10-07-add-timelib-callsite-migration） — 修改：废除「self_review 窗口气泡保持 naive 本地」（窗口整体迁 aware UTC，见 [存量时间调用点迁移完成性契约](timelib-callsite-migration.md)）；守卫白名单清零、naive 解读收敛为纯读侧兼容面
