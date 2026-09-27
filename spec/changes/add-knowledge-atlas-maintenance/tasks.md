## Deliverables

```yaml
- path: core/knowledge_backfill.py
  kind: new
- path: core/knowledge_audit.py
  kind: new
- path: core/knowledge_prompts/backfill.md
  kind: new
- path: core/knowledge_prompts/audit.md
  kind: new
- path: fenixd.py
  kind: modify
- path: core/config.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: docs/help/knowledge-atlas.md
  kind: new
- path: docs/help/README.md
  kind: modify
```

## 1. 配置项扩展

- [ ] 1.0 前置依赖闸门接线：实现入口首查 `.fenix/STATE.md` 本条目 `depends_on` 字段，为空则登记 `depends_on: add-knowledge-atlas`（派发闸门 `PMEngine._dependencies_satisfied` 消费，缺登记则依赖排序不生效）；若登记时前置 `add-knowledge-atlas` 尚未合并，按 blocked 上报零文件改动退出，由闸门在前置合并后接管重派
- [ ] 1.1 core/config.py 新增 `knowledge.audit_enabled` 与 `knowledge.graph_enabled` 解析（bool 默认 true，非法值回退默认并告警），.fenix/config.template.yaml 登记带注释模板行，补解析单测
- [ ] 1.2 core/dashboard/static/src/pages/settings/index.tsx 设置页新增两开关控件与说明文案，补渲染单测

## 2. 存量回填批处理车道

- [ ] 2.1 core/knowledge_prompts/backfill.md 批量蒸馏提示词：复用 distill.md 契约 + 批量模式附加段（一次处理本批全部归档、逐归档应用合并语义、域归位服从既有骨架）
- [ ] 2.2 新建 core/knowledge_backfill.py：进度台账（.fenix/knowledge_backfill.jsonl，pending/distilled/failed）、聚类自举 run 段（产域骨架与 index.md/_domain.md）、按域分批派发（批 ≤20）、断点重入（只处理 pending/failed）、每批 validate_knowledge 全量校验 + pathspec 限定提交（`[fenix] knowledge: backfill batch N/total`）、收敛汇报（批数/成败计数/失败清单/规模统计）；单测用 fake spawn 替身覆盖全量成功/批失败续跑/中断重入三支路
- [ ] 2.3 回填车道经 import 复用 core.knowledge 的 validate_knowledge 与提交工具函数（core/knowledge_backfill.py 自含调度逻辑，不修改 core/knowledge.py 本体；若实现中发现确需微调，作为伴生修改最小化处理），补接线单测

## 3. 周期 audit 淘汰车道

- [ ] 3.1 新建 core/knowledge_audit.py：五类病灶扫描（悬空链接/超行数/ADR diff 与链断裂/格式为机械项直修直提交 `[fenix] knowledge: audit fix <摘要>`；矛盾与重复为语义项转定向蒸馏 run 重写，失败登 todo.md）、体检报告落 .fenix/knowledge_audit_report.md（过/修/转写/待人工计数与明细 + 规模趋势超 +10% 标「需精简」附候选页清单）；单测覆盖机械自修/语义转写/零病灶三支路
- [ ] 3.2 core/knowledge_prompts/audit.md 转写提示词：给两处冲突上下文、按增量蒸馏契约重写受影响页、允许「判无矛盾」零改动收场
- [ ] 3.3 fenixd.py daemon 主循环挂自然日检查点（audit_enabled 门控，与自动归档 300s 周期检查同款挂载），补调度门控单测

## 4. Graphify 关系图生成

- [ ] 4.1 core/knowledge_audit.py（或独立模块）挂 graph 生成：每日窗口 shutil.which('graphify') 探测、对 spec/knowledge/ 执行生成落 graph/（graph.html + GRAPH_REPORT.md + graph.json）、pathspec 限定提交、CLI 缺失/执行失败 fail-open 单行日志、knowledge.graph_enabled 门控；单测用假 CLI 替身覆盖成功/缺失/禁用三支路

## 5. 文档与端到端

- [ ] 5.1 新建 docs/help/knowledge-atlas.md：真相源使用说明（目录结构、页签导航、audit/graph 行为、graphify 人工安装步骤[uv tool install graphifyy]、daemon 重启生效说明）；docs/help/README.md 完整目录表补登记行（帮助条目必须可发现）
- [ ] 5.2 e2e 测试（fake spawn 替身 + 临时 fixture 归档集）：回填车道端到端（自举→分批→收敛汇报）、audit 端到端（植入病灶→机械修+语义转写→报告断言）、graph 端到端（假 CLI 产物落盘与提交断言）
- [ ] 5.3 全量回归通过（pytest 既有套件 + 本 SPEC 新增用例）
