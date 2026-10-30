# design.md

## 根因坐标（已核实）

- 指纹：core/code_review.py:524-531 sha1(file|category|normalize_title(title))[:12]；normalize_title（:515）折叠空白+小写，title 为易变中文文案；台账双指纹对实测 b1eeebc0f4d9/d493c3cfa216（0.58）、b576000bfd68/20f078330d5d（0.66）。
- 核销：resolve_snapshot（:993，:1029-1033）；资格门 core/agent_runner/maintenance_runs.py:1998；观测集现算 :2100-2113；调用点 :2115。
- 来源混用：合回核销 resolution='code-fix-auto'（:2201-2203），快照核销无标记（resolution=None）；dashboard 投影 core/dashboard/data/code_review.py:20、:52-66 默认只回 open。

## 设计决策

1. **核销时点对账而非指纹重构**：把 title 移出指纹会让同文件同类目的不同缺陷坍缩为同一条（粒度过粗、漏报）；改为核销前用同 file+category+标题相似度兜底，指纹本身不动，命中即把旧条目指纹迁移为新指纹——下一轮直接命中，漂移闭环收敛。
2. **阈值 0.55**：取自实测两对漂移样本相似度（0.58/0.66）之下沿，既覆盖实测漂移形态，又留出「真不同缺陷」的区分带；常量缺省，不新增配置键。
3. **来源标记向后兼容**：只给新核销写 resolution='snapshot_closed'，存量 None 不回填（避免 6433 行批量改写）；完成行/rollup/dashboard 的新分列只影响新数据，历史口径在文档注明解读方式。
4. **todo 建议①不再需要探测轮**：原建议「同树双轮审查比重合率」的定位目标（易变字段=title）已被代码阅读+台账双指纹对静态证实，SPEC 直接进入修复。
5. **相似度用标准库 difflib.SequenceMatcher**：归一化标题上运行，无新依赖；对账开销仅作用于核销路径的少量未命中条目。

## 风险

- 相似度对账可能把「恰好同文件同类目且措辞相近的两个不同缺陷」误并为一条（保持 open+迁移指纹）：概率低且后果是延迟核销而非丢缺陷，接受；测试覆盖低相似度不误保。