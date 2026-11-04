# memory 存量蒸馏：未走 SPEC 的已落地代码/前端规则补遗

## 背景

auto-memory 存量中的**原地修复（未走 SPEC 管线）已落地规则**——对照 2026-11-04
代码复核仍现行，且未见于能力页（`spec/knowledge/domains/` grep 核验）。适合折叠进
code-fix-lane / dashboard-frontend 域相应能力页。

## 结论（当前事实）

### code-fix 链进度分母活口径

链进度 total 用活口径 `total = done + total_open`（`core/code_fix.py:5066` 现行）：
核销转移（done+1/open-1）不变分母，链在飞期间新审查 arrivals 推高分母、外部核销
缩小分母；`_process_deferred_merges` 的 done 写点不写 total 自动保不变式。设计
原则：链身份「稳定分母」与「中途 arrivals 可见」冲突时后者优先——进度条撒谎比分母
跳动更伤。改 total 语义须跑
`test_chain_total_grows_on_midchain_new_items` +
`test_activation_id_total_preserved_across_chain`（双测试锁双向语义）。

### 前端停轮询终态必须有恢复路径

CodeFixProgressCard 连续读取失败（≈6s）→ 停轮询 + 红条终态：effect 依赖不变时
移动端切后台掐 fetch 后回前台**永不恢复**。现行防线：组件监听 `visibilitychange`
（visible → retryKey+1 重启主轮询），对齐 list.tsx/overview 既有补刷模式。设计
原则：「宁停不错」的停轮询终态必须有环境性失败的恢复路径。验证手法：playwright
route `--status=500` ×9s 复现红条 → unroute → dispatch visibilitychange → 2s 内
恢复。

### code-review 台账 severity 写读双归一

写侧 `core/code_review.py normalize_severity()`（`core/code_review.py:657` 现行，
口径同 artifacts.py severity_map：high/medium→major、low→minor、空→info、未知
透传 fail-open）接入 upsert_findings；读侧 `read_code_review_items` 返回前就地归一
（存量漂移行零迁移治愈，随下次 upsert 自然刷新盘上值）。severity **不参与
fingerprint**——归一不影响去重；出现四档之外未知值应在 `_SEVERITY_NORMALIZE` 表
补值而非改消费端。

### LLM 拒绝出口（skip_reason 契约）

agents/code-fix.md 输出契约 `skip_reason`（false_positive/not_worth_fixing→
mark_ignored 置终态 ignored；unfixable/needs_human/无标注→维持 open 链内跳过，
缺省保守防轻率清账）；mark_ignored 仅 open 可降（in_spec/resolved 不触碰），记
ignored_by/reason/at 供人工重开；同条目「首轮 skipped、重试轮 fixed」以 fixed 为准
（纯函数分区并集口径）；全批降级时无改动可合回按完成收尾。

### 周期审查为纯 LLM 逐文件审查

ocr scan 辅助手段已整体移除（2026-09-24，a19bb956）：其扫描进程曾网络僵死 2h20m
（101 文件仅累计 49s CPU）且 agent 失败后重试而非降级；现车道 MUST NOT 调用
ocr/`bin/ocr_review.py`（该包装器仅供其他车道），无任何「等外部扫描产物」步骤，
审完即落盘、全部文件落行即收工。cancel 终态不做产物抢救——人工 cancel 带完整产物
时先验证 out 文件再动手，补账走 `_read_code_review_out(None, root, run_id)` +
`upsert_findings(review_kind='scheduled')`（scheduled 不触发快照核销，无白洗风险）。

### 治理判定（快速对照，防重复立项）

以下历史缺口**均已闭合勿重复立项**：回归异常熔断分档已含 timeout 无明细形态
（`core/code_fix.py:42,106,116`，ANOMALY_FAIL_RETRY_MAX=1 +
REGRESSION_ANOMALY_BREAKER_THRESHOLD=2）；checkpoint disabled 分支守卫链已含
already_running 与在飞检查（`core/code_fix.py:4133,4688`）；per-test timeout 门
（pytest.ini timeout=10 signal + tests/timeout-allowlist.yaml）已落地；
knowledge-distiller 已收编进 command_center ZONE_OPS（归档剔除豁免，
`core/dashboard/data/command_center.py:62-67`）。

## 证据

- 源记忆：fenixd-codefix-progress-denominator-and-background-freeze、
  fenixd-codereview-severity-drift-ocr-passthrough（含 LLM 拒绝出口段）、
  fenixd-codereview-cancel-salvage-gap-and-ocr-stall、
  fenixd-codefix-regression-selfpoison-loop-1008、
  fenixd-codefix-regression-sigkill-loop-1007。
- 2026-11-04 复核：上述代码锚点逐一 grep 现行；「治理判定」段各项 grep 确认闭合。
