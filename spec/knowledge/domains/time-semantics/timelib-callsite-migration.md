# 存量时间调用点迁移完成性契约

<!-- knowledge: capability=timelib-callsite-migration rev=1
     sources=spec/archive/2026-10-07-add-timelib-callsite-migration -->

生产代码的时间调用点已全部收拢进 [timelib 收拢层](timelib-consolidation.md)；本能力锁定迁移完成后的稳态——守卫白名单零豁免、写侧零 naive 产出、调度语义边界换算规则、CLI 展示统一与部署副本刷新登记，防止迁移成果回潮。

## 规则

- **守卫白名单零豁免稳态**：`tests/test_timelib_guard.py` 的 `TIME_WHITELIST` 为空列表，全部生产文件不含任何禁用模式调用（零参 `datetime.now()`、`datetime.utcnow()`、零/单参 `fromtimestamp()`、`utcfromtimestamp()`、timelib 之外的 `fromisoformat()`）；僵尸条目检测常态全绿。棘轮在零白名单下同样生效——迁移合入后任何生产文件再次引入违例，守卫即时失败并报出文件与行号。守卫扫描面为 `core/**/*.py`（排除 vendored 目录）与仓库根 `fenixd.py`；`bin/` 不在守卫扫描面，其时间原语收敛以源码面机械验收承接。
- **写侧零 naive 产出**：任何持久化字段（jsonl、STATE.md、台账、dashboard API 响应）的写侧一律 `timelib.now_utc()` + `to_storage()`（aware UTC），落盘串含 `Z` 或 `+HH:MM` 后缀，`parse_ts` 解析回的 UTC 时刻与写入时刻一致。`HH:MM` 调度配置与 knowledge 盖戳是人类可读形态（配置/渲染形态，非时间戳存储），不受此约束。
- **调度语义边界换算**：`HH:MM` 调度配置是人类时刻，解析处按本地墙钟构造后立即转为 aware UTC 参与窗口计算，配置字面值不变——UTC+8 机器上配置 `23:00` 即当日 `15:00Z`；配置值非法时回退缺省调度时刻（`SELF_REVIEW_DEFAULT_RUN_AT`，缺省 `02:00`）。窗口计算全程 aware 比较，不再做 naive 收尾。
- **迁移等价替换纪律**：时间调用点迁移限定等价替换——不改窗口阈值、不改超时秒数、不改台账 schema 字段名、不改告警判定边界；迁移中发现必须的行为变化（如存量数据按旧解读已错 8 小时）在 run 结果中申报，行为变化另行走 SPEC，不顺手修改。测试替身与生产同批迁移（逐域 grep 替身内 naive 串构造、`ts[:19]` 切片、`fromtimestamp` 构造），防「替身没跟着改」的假失败/假通过；自省窗口/调度类测试为用户级配置敏感区，替身时间戳格式逐域核对。
- **CLI 展示统一 fmt_display**：`bin/fenix_process.py` 与 `bin/fenix_dashboard.py` 不保留私有本地时间格式化助手（`_local_ts` 类），时间戳展示一律 `timelib.fmt_display`，输出格式 `YYYY-MM-DD HH:MM:SS` 本地时区；`Z` 后缀、`+00:00` 后缀、无后缀三形态输入的输出与既有口径逐字一致（无后缀按本地解读，与 `parse_ts` 策略一致）。`bin/` 脚本的时间戳解析走 `parse_ts`，无裸 `fromisoformat`。
- **部署副本人工刷新**：`bin/*.py` 为跟踪真身，`.fenix/bin` 为未跟踪部署副本——worktree 不含 gitignored 文件，副本改动不随 merge-back 落地。真身修改合入主树后，部署副本刷新是登记在案的人工步骤（`.fenix/todo.md` 或 docs help 人工步骤节），注明需主树手工同步或重启部署机制，agent 不可交付。

## 关键行为

- 迁移后各域对外输出时刻不变（aware UTC 存储值与原 naive 本地值表示同一时刻），唯一可感知差异是字段开始带时区后缀（naive 串 → `+00:00`/`Z` 后缀）；下游解析一律经 `parse_ts`，已兼容三形态。
- 存量 naive 历史数据不做批量改写：历史 jsonl/台账按 `parse_ts` 的 naive→本地策略兼容读取，无数据迁移；个别域发现旧数据按旧解读错读，另行立项。
- dashboard 只读契约在时间戳 aware 化后保持：时间字段 aware 串可被前端 dayjs 正常解析，概览/项目详情页渲染无 Invalid Date，只读端点不因解析 5xx。

## 溯源

- 2026-10-07 add-timelib-callsite-migration（spec/archive/2026-10-07-add-timelib-callsite-migration） — 新增能力：守卫白名单清零进入零豁免稳态、写侧零 naive 产出、self_review 窗口整体迁 aware UTC 与 HH:MM 调度语义边界换算、CLI 展示统一 fmt_display（私有 `_local_ts` 助手退役）、迁移等价替换纪律、`.fenix/bin` 部署副本人工刷新登记
