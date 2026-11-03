## Deliverables

```yaml
- path: core/knowledge.py
  kind: modify
- path: core/knowledge_audit.py
  kind: modify
- path: core/knowledge_backfill.py
  kind: modify
- path: core/dashboard/routes/knowledge_routes.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/KnowledgeTab.tsx
  kind: modify
- path: agents/knowledge-distill.md
  kind: new
- path: agents/knowledge-audit.md
  kind: new
- path: agents/knowledge-backfill.md
  kind: new
- path: agents/knowledge-prehistoric.md
  kind: new
- path: core/knowledge_prompts/distill.md
  kind: delete
- path: core/knowledge_prompts/audit.md
  kind: delete
- path: core/knowledge_prompts/backfill.md
  kind: delete
- path: core/knowledge_prompts/prehistoric.md
  kind: delete
- path: spec/knowledge/_inbox/README.md
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: restart_request
  kind: reference
```

## 1. 候选区地基

- [x] 1.1 创建 `spec/knowledge/_inbox/README.md`：投递契约（自由格式 markdown，
      含背景/结论/证据段即可，不守能力页契约）、折叠成功移 `done/`、校验失败滞留
      原地待下轮重试、`done/` 为溯源永久保留区
- [x] 1.2 扫描范围显式排除 `_inbox/**`（现状天然体外，补显式排除防未来扫描范围
      变更误伤）：validate 侧在 `core/knowledge.py`（domains/index/adr 遍历点），
      audit 侧在 `core/knowledge_audit.py`（候选集 rglob 收集点，现仅扫 `domains/`）；
      新增测试断言：含 marker 缺失/超行数/失效链接的 `_inbox` 夹具不产生任何违规

## 2. marker sources 契约扩展

- [x] 2.1 sources 机器校验放行 `spec/knowledge/_inbox/done/` 前缀（file 形态校验
      文件存在），其余前缀行为不变；测试覆盖放行与文件缺失拒绝双形态

## 3. piggyback 折叠管线

- [x] 3.1 distill 车道入口新增 inbox 折叠前置段：逐条消化 `_inbox/` 存量（按条目
      顺序、每条独立提交可中断），按能力页契约折叠进相关能力页或新建能力页，
      超 150 行拆页（主从分片互链），成功条目移 `_inbox/done/` 并改写能力页
      marker sources 指向 `done/` 路径，失败条目滞留原地不丢弃
- [x] 3.2 折叠落盘前跑实时 `validate_knowledge`，失败不落盘（测试覆盖校验失败
      滞留形态）；折叠挂点与队列台账单写者（ADR-234）兼容，不引入双写者
- [x] 3.3 测试覆盖 Scenario：候选折叠闭环 / 超顶拆页 / 无 SPEC 批次不派发
      （piggyback-only 语义断言：`_inbox` 非空不产生独立 run）

## 4. log.md 编年账

- [x] 4.1 新增 `spec/knowledge/log.md` 追加机制：行前缀常量
      `## [YYYY-MM-DD HH:MM UTC+8] <操作> | <主题>`（操作 ∈ distill/fold/backfill/
      lint），本地时区显式标注，追加并发安全（文件锁或复用 ADR-234 单写者纪律），
      并发追加不丢行有测试
- [x] 4.2 distill/audit/backfill 轮收尾追加对应行（折叠轮先 fold 行后 distill 行）；
      写入主体 MUST 为 daemon 代码侧轮收尾逻辑（依据 run 产物中的折叠/轮次结果
      报告，如 status 行扩展段），MUST NOT 依赖车道 LLM 在轮内直接写 `log.md`
      （写面纪律与并发安全在代码侧收口）；测试覆盖轮次收尾留痕 Scenario

## 5. 归档改写豁免

- [x] 5.1 `rewrite_source_links_to_archive` 显式排除 `spec/knowledge/log.md` 与
      `spec/knowledge/_inbox/**`（含 `done/`），新增测试：夹具候选原文含
      `spec/changes/<名>` 字符串，归档改写后逐字节不变、能力页照常改写

## 6. 积压提醒

- [x] 6.1 audit 周期轮积压检测：积压 ≥10 条或最老条目滞留 ≥7 天（mtime 起算）落
      `log.md` lint 提醒行，同轮幂等去重，MUST NOT 写 AdminStore（测试断言无人工
      告警产生）
- [x] 6.2 dashboard 积压计数：`knowledge_routes.py` 返回 `_inbox/` 积压计数与最老
      滞留天数，`KnowledgeTab.tsx` 展示；跑构建产出 dist 并确认锚点文件更新

## 7. 蒸馏 prompt 归位

- [x] 7.1 四个 prompt 迁移到 `agents/` 平铺：agents/knowledge-distill.md、agents/knowledge-audit.md、agents/knowledge-backfill.md、agents/knowledge-prehistoric.md（与既有 agents 命名一致，内容分别来自 `core/knowledge_prompts/` 下同名文件）；先 merge main 再迁移（prompt 契约段纪律）；agents/knowledge-distill.md 增补 inbox 折叠段（与任务 3.1 代码行为一致）；知识车道加载点全部改为 `agents/` 新路径
- [x] 7.2 删除 `core/knowledge_prompts/` 全部四个文件（合并后目录不存在），旧路径
      残留引用清零——grep 验收范围＝活代码与活文档（`core/`、`tests/`、`agents/`、
      `core/dashboard/static/src/`、`docs/`），MUST 显式豁免 `spec/changes/**` 与
      `spec/archive/**`（历史流转记录不可篡改）及 `spec/knowledge/**`（能力页对
      run 形态的历史描述由 distill 车道后续蒸馏自然更新，不入本 SPEC 验收）；
      落位 `restart_request`
      交付物（根路径 JSON：reason/origin/date）并冒烟预演（全新进程 + 知识车道
      prompt 加载 + validate_knowledge），实际重启由 supervisor 消费信号完成

## 8. 验证收尾

- [x] 8.1 端到端测试：合成夹具 `_inbox` 条目 → 驱动 distill 轮 → 断言能力页折叠
      内容、marker sources 校验通过、条目移 `done/`、`log.md` fold+distill 行齐备
- [x] 8.2 存量知识车道测试全绿（`tests/test_knowledge*.py` 族），跑全量
      `validate_knowledge` 对 fenixd 主树知识库无回归违规；Scenario 全量静态对账
      结论写入收工报告
