# 散件首现预防提示

<!-- knowledge: capability=stray-first-sight-prevention rev=1
     sources=spec/archive/2026-10-30-evo-stray-first-sight-prevention -->

主树 untracked 散件治理从被动链路（产物滞留 → 告警 → 升级 → 被动 ignore）转向首现预防：新型产物目录第一次出现即提示预防性 ignore，交付侧配套落盘覆盖检查点——同型散件事件从「24 小时滞留 + 升级告警 + admin 处置 run」塌缩为「首现即提示 + 预防性 ignore 一行」。

## 规则

- **盘点首现提示**：untracked 散件盘点在目录型产物集合**首次出现**（首现登记无该目录记录）且未被 `.gitignore` 覆盖（上游散件清单豁免已 ignore 路径保证）时，发出一次 info 级首现提示信号（`kind=maintree_untracked_stray_first_sight`），evidence 携带目录清单、体积与预防性 .gitignore 条目草案（含成因注释）；集合低于既有 info 档 entry 阈值（5）时同样提示（below_threshold 早退不适用于首现判定），但不启动升级时钟。
- **归组与去重键**：首现判定按「目录型产物集合的规范化根目录」归组——同一新建产物目录下的散件条目归为一个集合；顶层散文件（无共同新建目录）不在首现提示面、仍走既有阈值流。去重键为目录路径，MUST NOT 采用随集合内容漂移的条目集指纹（集合增长或跨阈值档切换会换键重复提示）。
- **一次性与复位**：同目录仅提示一次——集合内容增长、跨阈值档切换导致的指纹漂移不视为新首现；目录整轮不再贡献散件条目即复位（同既有 absent 复位模式），复位后再现视为新首现（复发场景正是提示价值所在）。已覆盖目录（check-ignore 命中）不计首现、不提示。
- **登记持久化**：首现登记复用既有未跟踪散件持久化机制（同持久化文件 `.fenix/stray_untracked_registry.json` 承载、独立目录键结构、读写与字段适配同步），跨 daemon 重启保持、重启不重复提示；排除集沿用既有散件判定名单（`.fenix/`、系统临时目录等），不另立名单。
- **首现提示不升级不唤起**：MUST NOT 启动 24 小时滞留升级时钟、MUST NOT 进 STORED_SIGNAL_TYPES 自动唤起收录——消费面是告警面板与后续评审/处置的背景信息，不制造新一轮 admin run；既有升级路径（滞留 24 小时或体积超阈值）行为不变。
- **交付落盘覆盖检查点**：implementer 交付契约要求——交付引入运行时落盘路径（日志、dump、产物目录）且落在仓库树内时，同提交追加对应 `.gitignore` 覆盖或将默认落盘路径移出仓库树，并在提交前以 git status 自查零 untracked 产物。
- **盘点保持只读**：首现提示与交付检查点均为建议面，ignore 动作仍走既有裁决执行器，盘点不获得写副作用。

## 溯源

- 2026-10-30 evo-stray-first-sight-prevention（spec/archive/2026-10-30-evo-stray-first-sight-prevention） — 新增本能力：目录集合首现一次 info 提示（去重键目录路径、低于阈值也提示、复位后再现重提示、不升级不唤起）、implementer 交付契约落盘覆盖检查点（动因实测：三起同型损失全部走被动链路累计烧约 $3.7 admin 处置，低于 5 entry 的散件集合连 info 提示都没有）
