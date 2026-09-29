# 知识真相源

知识真相源是 Fenix 的长期记忆层：把已归档 SPEC 里仍然现行的规则、决策与约束蒸馏成一组人可读、可校验、可追溯的 Markdown 页面，放在 `spec/knowledge/` 下随仓库提交。回填（backfill）与体检（audit）两条车道负责让这组页面保持新鲜、自洽、可导航。本文说明目录结构、如何在 Dashboard 里操作、两条车道各自的行为。（关系图（graph）车道已随 graphify 功能取消下线：开关、生成与下发代码均已移除，存量 `graph/` 产物保留但不再更新。）

## 目录结构

真相源固定在仓库根的 `spec/knowledge/`：

```text
spec/knowledge/
├── index.md                    # 真相源导航首页（能力页索引）
├── domains/
│   ├── <域>/
│   │   ├── _domain.md          # 域说明（该域的边界与归属口径）
│   │   └── <能力>.md           # 能力页：现行规则的唯一事实来源
│   └── ...
└── adr/
    ├── index.md                # ADR 索引（编号、标题、状态）
    └── ADR-NNN-*.md            # 架构决策记录（accepted / superseded）
```

每个能力页头部有一行知识 marker，记录能力名、修订号与来源归档，溯源段逐条指向 `spec/archive/` 里的出处；audit 车道据此清理悬空溯源：

```markdown
<!-- knowledge: capability=超时治理 rev=3 sources=arc-a1,arc-b2 -->
# 超时治理

## 规则

- 全局请求超时：300 秒。

## 溯源

- spec/archive/arc-a1
```

约定两条硬规则：能力页不超过 150 行（超限会被标「需精简」并给出候选页清单）；ADR 被 newer 决策取代时用 `Superseded by:` 链接，audit 会校验链完整性。

## 页签导航

Dashboard 设置页（设置 → 杂项设置）的「真相源」卡片提供开关：

- **知识真相源（总开关）**：`knowledge.enabled`，默认开启。关闭后归档照常完成，但不再派发蒸馏 run。
- **周期体检（audit）**：`knowledge.audit_enabled`，默认开启。关闭后 daemon 不再执行每日体检。

开关随设置页统一保存（写入 `.fenix/config.yaml` 的 `knowledge:` 段），保存后由 daemon 的配置热更新（约 30s）生效，无需重启。

## audit 体检行为

daemon 主循环每 300 秒醒一次，到达新的自然日且开关开启时执行一次体检（每车道每天至多一次，异常不落日戳、下周期重试）。体检分两级处置：

- **机械项直修直提交**：悬空溯源行（指向已不存在的归档）、行尾空白等格式违规、ADR 索引状态与条目头不一致。修复后经 `validate_knowledge` 校验通过即以 `[fenix] knowledge: audit fix <摘要>` 提交。
- **语义项转写**：跨能力页的规则矛盾与近重复，脚本只做初筛（宁松勿紧），逐条派定向蒸馏 run 重写受影响页；run 返回「判无矛盾」则零改动收场（计入误报）；转写后校验两轮仍失败则回滚半成品并登记 `.fenix/todo.md` 待人工。

体检报告落在 `.fenix/knowledge_audit_report.md`：过/修/转写/待人工四类计数与明细，外加规模趋势——真相源总行数相对上次增长超过 +10% 时整份报告标「需精简」并附候选页清单。

前置依赖：audit 车道复用 `core.knowledge` 的校验器与提交工具。前置 SPEC（add-knowledge-atlas）未合并时车道静默跳过且不消耗当日窗口，合并后当日即补跑。

## 回填车道（存量归档蒸馏）

回填不挂 daemon 周期，按需手动激活（前置 SPEC 合并、存量归档待蒸馏时）：

```bash
python3 -m core.knowledge_backfill --project-root .
```

流程：清单缺失时先派聚类自举 run 产域骨架与导航页 → 按域分批（每批 ≤20 个归档）派批量蒸馏 run → 每批经全量校验后 pathspec 提交（`[fenix] knowledge: backfill batch N/total`）→ 收敛后输出汇报。进度台账在 `.fenix/knowledge_backfill.jsonl`（pending / distilled / failed），中断后重跑只处理 pending/failed 条目；单批失败不阻塞后续批，失败项登记 todo.md。
