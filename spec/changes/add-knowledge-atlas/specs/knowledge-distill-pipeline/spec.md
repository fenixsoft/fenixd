## ADDED Requirements

### Requirement: 归档触发蒸馏

SPEC 归档完成后 SHALL 自动派发一次蒸馏 agent run（knowledge-distill 车道）。两条归档路径 SHALL 同等挂载：手工/CLI 路径（`.fenix/bin/fenix_archive.py`）与 daemon 自动归档路径（`auto_archive_check`）。蒸馏触发 SHALL fail-open：派发失败或 run 失败不阻塞、不回滚归档本身，失败信息记日志并生成重试台账条目。`knowledge.enabled` 为 false 时 SHALL 跳过派发。经同一漏斗的软删除路径（`soft_delete_spec` 以归档移动收尾）触发蒸馏 SHALL 视为预期行为。多条蒸馏 run 对 `spec/knowledge/` 的写 SHALL 串行化（单飞或队列）。归档原料缺失（无 `design.md` 或无 `specs/` delta）时蒸馏 run SHALL 降级处理：跳过 ADR 抽取、按可得原料（proposal 摘要）蒸馏能力页或留痕跳过，MUST NOT 因原料缺失判 run 失败。

#### Scenario: 手工归档后蒸馏被派发

- **WHEN** 用户经 `/fenix-archive` 归档一个已完成 SPEC 且 `knowledge.enabled` 为 true
- **THEN** 归档目录移动成功后，框架派发一个 knowledge-distill run（输入含被归档 SPEC 的路径）；归档动作本身的成功返回不依赖蒸馏结果

#### Scenario: 自动归档后蒸馏被派发

- **WHEN** daemon 周期检查触发 `auto_archive_check` 归档了若干 SPEC
- **THEN** 每个被归档的 SPEC 各派发一次蒸馏（或合并为一次批量蒸馏 run，属实现裁量），行为与手工归档路径一致

#### Scenario: 蒸馏派发失败不阻塞归档

- **WHEN** 蒸馏 run 派发时 agent 网关不可用
- **THEN** 归档已完成的目录保持归档态不变，框架记失败日志并生成重试台账条目；后续机制（重试车道或人工触发）可补做蒸馏

### Requirement: 蒸馏合并语义（后写覆盖前写）

蒸馏 run SHALL 读被归档 SPEC 的 `specs/<capability>/spec.md` delta 与 `proposal.md` 摘要，对每个涉及的 capability 执行合并：真相源中**不存在**该能力页 → 新建（ADDED）；已存在 → 重写受影响规则段（MODIFIED，以本次 delta 为准覆盖旧表述，rev 加 1，溯源段追加一行）；delta 声明删除的规则 → 从能力页移除（REMOVED，溯源段留一行「已随 <归档名> 废除」）。同一能力被多个 SPEC 先后修改时，真相源 SHALL 只保留最终态规则。能力页拆为主从分片（marker `part` 字段）时，合并 SHALL 按 capability 名聚合、整体重写该能力全部分片。

#### Scenario: 修改既有能力时覆盖而非追加

- **WHEN** 能力页 `scheduled-spec-pickup` 已存在（rev=2），归档的新 SPEC 修改了其轮询间隔规则
- **THEN** 蒸馏后该页 rev=3，`## 规则` 段陈述新间隔且不再出现旧间隔作为现行规则（旧值不出现在规则段），溯源段新增一行指向本次归档

#### Scenario: 删除规则时移除并留痕

- **WHEN** 归档 SPEC 的 delta 移除了某能力的某项规则（如某废弃开关的行为）
- **THEN** 该规则从能力页规则段消失，溯源段出现「已随 <归档名> 废除」行，页面其余规则不受影响

### Requirement: 蒸馏收尾确定性校验与自动提交

蒸馏 run 落盘前 SHALL 经确定性校验脚本（非 LLM）检查：每个能力页 marker 可解析、sources 指向的归档目录真实存在、单页不超 150 行、`index.md` 与各域 `_domain.md` 的链接可解析。校验全部通过后 SHALL 自动提交真相源变更（commit 形如 `[fenix] knowledge: distill <归档名>`），提交失败 fail-open 记 warning。校验失败时 SHALL 拒绝落盘并将违规项回反馈给蒸馏 run 修正（最多 2 轮），仍失败则按失败台账处置、不产出半成品提交。

#### Scenario: 校验通过自动提交

- **WHEN** 蒸馏 run 产出合法的能力页更新并通过全部校验
- **THEN** 变更以 `[fenix] knowledge: distill <归档名>` 形式入库，`spec/knowledge/` 在主树可直接阅读最新真相

#### Scenario: 溯源链接悬空被拦截

- **WHEN** 蒸馏 run 产出的溯源行指向不存在的 `spec/archive/xxx` 目录
- **THEN** 校验拒绝该产出，run 收到违规说明并修正后重试
