<!-- knowledge: capability=judge-incremental-attribution rev=1 sources=spec/archive/2026-09-18-evo-add-judge-incremental-attribution -->

# judge 增量归因

planner-judge 归因的逐场景增量写盘与查重拒绝的场景级回炉：拒绝仅回炉重复子集，非重复场景归因保留复用。

## 现行规则

- 归因逐场景增量写盘：planner-judge 输出归因时按场景逐个落盘（每场景一条目，含场景 id、归因文本、落盘状态与时间戳），同一轮产出不以整块单条目落盘；条目在同一产物文件内逐条组织，各自可独立读取与覆写。
- 读侧兼容：读入旧版整块归因产物按旧结构回退解析，不报错（向后兼容）；新增逐场景结构并行支持。
- 查重拒绝场景级回炉：批量归因查重判定不通过时按场景粒度定位重复子集，仅重复场景的归因标记为待回炉（requeue），非重复场景归因保留可复用；不因子集重复废弃整轮已写盘归因。
- 全量重复仍全量回炉：全部场景归因均命中查重（如模板化硬编码）时按既有语义整批回炉且 escalation 告警照发（不弱化查重防御）。

## 溯源

- [2026-09-18 evo-add-judge-incremental-attribution](spec/archive/2026-09-18-evo-add-judge-incremental-attribution/) — 确立归因逐场景独立条目落盘、旧整块结构回退兼容与查重拒绝场景级回炉（子集回炉/全量重复整批回炉）
