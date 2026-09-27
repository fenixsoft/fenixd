## Deliverables

```yaml
- path: core/knowledge_backfill.py
  kind: modify
- path: core/knowledge.py
  kind: modify
- path: core/knowledge_prompts/backfill.md
  kind: modify
- path: core/knowledge_prompts/prehistoric.md
  kind: new
- path: tests/test_knowledge_backfill.py
  kind: modify
- path: tests/test_knowledge.py
  kind: modify
```

## 1. 聚合语义（方案 B）

- [ ] 1.1 core/knowledge_backfill.py 新增链索引构建（遍历 spec/archive/*/specs/ 目录名 × 归档日期前缀升序，产出 capability→有序归档 delta 链，纯机械零 LLM）；build_batches 改能力粒度（域内能力集合批 ≤20，聚类自举的 domain_map 对象同步从归档名改为能力名）
- [ ] 1.2 core/knowledge_prompts/backfill.md 改聚合式：输入为单能力全链 delta（+史前基线若有），一次成文最终态页面（rev=链长、sources 全链、溯源按时间序、禁中间态措辞），删除逐归档重放指引
- [ ] 1.3 BackfillLedger 台账 v2：条目键改 `capability:<名>`/`adr:<归档名>` 双维度（各 pending/distilled/failed），旧归档粒度条目首次重入作废重建，断点重入按维度独立续跑，收敛汇报分维度计数
- [ ] 1.4 tests/test_knowledge_backfill.py 更新：链索引确定性（同输入同链序）、多归档能力一次成文（×3 链产 rev=3 且无中间态残留）、批次顺序无关（颠倒/并行同结果）、台账 v2 断点续跑与 failed 不阻塞

## 2. 史前复原

- [ ] 2.1 新建 core/knowledge_prompts/prehistoric.md：输入 git 提交群（首提交至 2026-09-02 前，git log 标题行）+ core/ 顶层模块骨架 + 归档能力全集（求差基准），输出史前能力清单（宁缺勿滥判据入词）+ 未覆盖能力的史前页散文（同 150 行硬顶与禁历史措辞契约）
- [ ] 2.2 core/knowledge.py parse_marker 增可选 origin 字段（缺省 archive）；validate_knowledge 按 origin 分支：prehistoric 页 sources 校验 `git:<ref>-..<日期>` 锚点格式与起始 ref 可解析（git cat-file -e），不要求归档目录存在；archive 页行为零回归
- [ ] 2.3 core/knowledge_backfill.py 自举段接入史前复原：跑 prehistoric 复原 → 求差 → 未覆盖能力产史前页（入正确域、登记 index）、已覆盖能力基线作为链头输入聚合单元；自举重跑以真实聚类重建域清单并清理 fixture 遗留域（如 zn-demo-domain）；补史前求差与基线链头单测（tests/test_knowledge_backfill.py）

## 3. 回填期排队

- [ ] 3.1 core/knowledge.py dispatch_distill 增排队判定：回填台账存在 pending 时不派发增量 run，把该归档登记为 pending 的 capability/adr 条目后返回（fail-open 语义不变），收敛后恢复即时派发；tests/test_knowledge.py 补排队登记与恢复派发两支路单测

## 4. 端到端与回归

- [ ] 4.1 e2e（fake spawn 替身 + fixture 归档集）：聚合回填全流程（史前复原→聚类→能力批次→收敛汇报，含 1 个史前独有页 + 1 个基线+链页 + 回填中新归档排队入台账被消化）
- [ ] 4.2 全量回归通过（pytest 既有套件含 knowledge 全家族用例）
