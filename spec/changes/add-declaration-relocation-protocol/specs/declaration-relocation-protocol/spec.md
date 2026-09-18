# declaration-relocation-protocol — 声明重定位协议

## ADDED Requirements

### Requirement: 陈日声明确定性信号

系统 MUST 机械识别「规划期声明路径已因上游演进失效」这一确定性信号：对生效声明
中的 `new`/`modify` 条目，若该路径在**基线树（主树 HEAD）不存在**、且其达标要求
在实现分支上**永不可满足**（即基线陈旧，非本轮实现缺失），则判为**陈日声明**。

判定 MUST 零语义推断——只认「基线树无该路径」这一确定性事实，与本轮实现 run 的
产出无关。`delete`（反判存在性）与 `reference`（软校验）条目 MUST NOT 参与陈日判定。

#### Scenario: 上游删除致声明失效

- **GIVEN** 规划期声明 `core/pm_engine/dispatch.py`（kind: modify），该文件已被
  上游重构拆分删除，主树 HEAD 无此路径
- **WHEN** 守卫/裁决流水线判定声明的可满足性
- **THEN** 该条被判为陈日声明（确定性信号命中）

#### Scenario: 本轮实现缺失不误判陈日

- **GIVEN** 声明 `core/new_module.py`（kind: new），该文件本就应本轮新建、主树
  基线本不存在
- **WHEN** 判定可满足性
- **THEN** 该条 MUST NOT 被判为陈日声明（`new` 在基线不存在是正常语义）

#### Scenario: delete 与 reference 不参与

- **WHEN** 声明含 `kind: delete` 或 `kind: reference` 条目
- **THEN** 二者 MUST NOT 进入陈日判定（delete 反判存在性、reference 走软校验）

### Requirement: 重定位凭据契约

陈日声明的重定位 MUST 由**凭据**驱动，凭据 MUST 包含三项：（1）旧路径在基线树
不存在（陈日信号）；（2）**替代路径**在实现分支 HEAD 真实存在；（3）来源标注
（重定位凭据类型，如 `relocated`）。三者齐备方可改写生效声明；任一缺失 → MUST NOT
重定位（降级走既有缺件处置）。

替代路径的来源可为：LLM 终审给出的 `actual_path`（复用 `typo` 归途），或机械
定位（如 basename 在树内的唯一命中，须同时满足「唯一」）。多命中或零命中 MUST NOT
自动重定位。

#### Scenario: 三要素齐备触发重定位

- **GIVEN** 旧路径 `core/pm_engine/dispatch.py` 基线不存在，替代路径
  `core/pm_engine/dispatch/adjudication.py` 在实现分支 HEAD 存在，来源标注 `relocated`
- **WHEN** 执行重定位
- **THEN** 生效声明中旧路径被替换为替代路径（kind 保持）

#### Scenario: 替代路径不存在拒绝重定位

- **WHEN** 陈日信号命中但给出的替代路径在实现分支 HEAD 不存在
- **THEN** MUST NOT 改写声明（防「改声明 ≠ 交付物落地」），该条按既有缺件处置

#### Scenario: 多命中不自动重定位

- **WHEN** basename 匹配在树内命中多个候选
- **THEN** MUST NOT 自动重定位，转 LLM 终审或人工

### Requirement: 重定位机械执行与审计

重定位 MUST 机械执行（不经 Agent 手改文档）：将生效声明中旧路径确定性替换为
替代路径（同名去重，与既有 `replace_declared_path` 语义一致），改写目标为**生效
声明所在位置**（分支/worktree 版本，或经裁决回写主树——由解析契约决定）。

每次重定位 MUST 落 dispute 审计流，含：旧路径、替代路径、来源标注、触发 run id、
声明改写前后 diff、时间戳。人工可据审计复核与回滚。

#### Scenario: 重定位替换并留痕

- **WHEN** 三要素齐备的重定位执行
- **THEN** 生效声明旧路径被替换为替代路径
- **AND** dispute 审计流新增条目含旧/新路径、来源、run id 与前后 diff

#### Scenario: 审计可回滚

- **WHEN** 人工判定某次重定位有误
- **THEN** 可据审计中的前后 diff 恢复声明段原文并触发重派

### Requirement: 重定位后防洗白复检

重定位改写落盘后，MUST 以改写后的生效声明重跑收工守卫对账：替代路径在实现分支
HEAD 真实存在方可通过；仍缺失 → MUST NOT 放行（改写声明 ≠ 放行缺件），按既有
缺件处置路径处理。

#### Scenario: 重定位后守卫复检通过放行

- **WHEN** 重定位后所有声明条目在实现分支 HEAD 满足（new/modify 存在）
- **THEN** 守卫复检通过，正常合并推进，不重派

#### Scenario: 重定位后仍缺件打回

- **WHEN** 重定位改写的替代路径仍不满足存在性
- **THEN** MUST NOT 放行，按既有缺件重派路径处置

### Requirement: 重定位失败安全

重定位任一环节异常（声明段解析失败、改写失败、并发编辑致内容漂移）MUST
fail-safe：该条不改写、不判定，回退既有缺件处置（LLM 终审 / blocked 人工），
MUST NOT 因重定位异常阻塞整条收工链，也 MUST NOT 静默放行。

#### Scenario: 改写异常回退缺件处置

- **WHEN** `replace_declared_path` 抛出异常（并发改写/格式漂移）
- **THEN** 该条不做重定位，等价转入既有缺件处置通道
- **AND** WARNING 留痕说明异常
