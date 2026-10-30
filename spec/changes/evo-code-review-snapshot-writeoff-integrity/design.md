# design.md

## 根因坐标（2026-10-24 评审复核）

- 指纹：core/code_review.py:607-613 sha1(f"{file}|{category}|{normalize_title(title)}")[:12]；normalize_title（:597-604）折叠空白+小写，title 为易变中文文案；台账漂移实测（2026-10-24 对 .fenix/code-review/items.jsonl 全量复核）：同文件同类目跨指纹且标题相似度≥0.55 的条目对 228 对，最高 0.99（同缺陷双指纹，如 pid_int 未使用变量两条仅「/」措辞之差）。
- 核销：resolve_snapshot（core/code_review.py:1076-1123）；资格门 core/agent_runner/maintenance_runs.py:2352-2354（manual_full 或 window_start=None 的全仓 scheduled）+ 覆盖完整性守卫 _writeoff_coverage_guard（:2034）+ observed 非空门（:2458）；观测集现算 :2445-2457；调用点 :2459。
- 事件证据：2026-10-19T18:36:50Z 完成行 resolved=214/updated=0/inserted=178（.fenix/logs/fenixd.log.3:32573，日志轮转后现位于 .3 分片）；台账现存 214 条 resolved_at=2026-10-19 且无 resolution 字段。
- 来源混用：合回核销 resolution='code-fix-auto'（core/code_review.py:2329，mark_resolved）；快照核销无标记（:1114-1115 只写 status/resolved_at，resolution 字段缺失）；完成行由 core/admin_monitor.py:1918-1925 按 CodeReviewResult.resolved（core/agent_runner/result_gate.py:367，装配于 maintenance_runs.py:2612-2621）单值输出；dashboard 台账列表端点默认只回 open（core/dashboard/data/code_review.py:52-86，:65 wanted={"open"}），QualityTab 把 resolved 统一文案为「已修复」（core/dashboard/static/src/pages/projects/components/QualityTab.tsx:125）。
- code-fix 计数口径（复核结论）：链 rollup 的 resolved 与进度 done 均由 mark_resolved 真实命中累积（core/code_fix.py:5929/:7484/:7489），机制上不含快照核销；「假清零计入修复成果」的实际混同面在完成行与 dashboard 展示口径，不在 code-fix 计数器。

## 设计决策

1. **核销时点对账而非指纹重构**：把 title 移出指纹会让同文件同类目的不同缺陷坍缩为同一条（粒度过粗、漏报）；改为核销前用同 file+category+标题相似度兜底，指纹本身不动，命中即把旧条目指纹迁移为新指纹——下一轮直接命中，漂移闭环收敛。
2. **阈值 0.55**：台账全量复核显示同缺陷双指纹对集中于 ≥0.82（实测最高 0.99），0.55 覆盖更重的措辞漂移形态并留出「真不同缺陷」的区分带（同组跨指纹对中 ≥0.55 占 228/55979，占比低）；常量缺省，不新增配置键。
3. **来源标记向后兼容**：只给新核销写 resolution='snapshot_closed'，存量 None 不回填（避免数千行批量改写）；完成行/dashboard 的新分列只影响新数据，历史口径在文档注明解读方式。
4. **对账 1:1 领用**：一条观测记录至多对账一条存量条目、一条存量条目至多领用一条观测——未命中条目取同 file+category 下相似度最高且未被领用的观测（并列取 last_seen_at 更近者），被领用观测不得再被其他条目领用；无可用观测的未命中条目按现语义核销。防止多条存量条目迁移到同一新指纹导致指纹碰撞与重复条目。
5. **迁移去重（孪生合并）**：本轮 upsert_findings（maintenance_runs.py:2324）先于核销（:2459）执行，漂移轮次中新指纹已被 upsert 作为新 open 条目插入台账；对账迁移旧条目至该新指纹时 MUST 合并孪生——保留存量条目（item_id/first_seen_at/龄期稳定），以观测记录刷新其展示字段（title/description/suggestion/evidence/line/severity/last_seen_at/review_id/review_kind/reviewed_at），删除本轮插入的孪生条目，维持「同一 fingerprint 至多一条台账条目」不变量；孪生已非 open（in_spec/ignored 等，缺陷已由他条承载）则放弃迁移，旧条目按未命中语义核销（缺陷不失踪）。
6. **完成行分列落点**：resolve_snapshot 返回值由 int 改为 {'snapshot_closed': n, 'fixed': 0}（本函数不产生合回核销，fixed 恒 0 占位以对齐两计数口径）→ CodeReviewResult（core/agent_runner/result_gate.py:367）新增两计数字段 → maintenance_runs.py:2612-2621 装配 → admin_monitor.py:1918-1925 完成行两计数输出；唯一生产调用方与存量测试随任务 1.2/3.2 同步适配。
7. **todo 建议①不再需要探测轮**：原建议「同树双轮审查比重合率」的定位目标（易变字段=title）已被代码阅读+台账漂移复核静态证实，SPEC 直接进入修复。
8. **相似度用标准库 difflib.SequenceMatcher**：归一化标题上运行，无新依赖；对账开销仅作用于核销路径的少量未命中条目。

## 风险

- 相似度对账可能把「恰好同文件同类目且措辞相近的两个不同缺陷」误并为一条（保持 open+迁移指纹）：台账全量复核中 ≥0.55 对占比 228/55979，概率低且后果是延迟核销而非丢缺陷，接受；测试覆盖低相似度不误保。
