# Capability: code-review-dispatch（审查/修复子代理扇出 429 节流）

## ADDED Requirements

### Requirement: 缺省在飞上限为 2

code-review run 提示词注入的子代理在飞上限缺省值 MUST 为 2：verify.repo_code_review_concurrency 读器缺省由 4 改为 2，config.template.yaml 模板示例值同步为 2（模板约束：示例值必须等于缺省值）；缺省同源面 MUST 一致降档——core/agent_runner/prompt_builder.py 注入段 fail-open 回退值（含 ConfigLoader 导入失败分支硬编码）与 core/dashboard/static/src/pages/settings/components/QualityPanel.tsx REPO_REVIEW_DEFAULT_CONCURRENCY 同步为 2。code-fix 车道的 {wave_cap} 分档（core/code_fix.py wave_cap_for_groups 按组数分档 4/6/8）不在本静态降档范围，仅受「429 记忆降档」Requirement 的 run 内记忆条款约束。已显式配置的项目行为不变。

#### Scenario: 未配置项目的新审查 run

- **WHEN** 项目配置未显式设置 repo_code_review_concurrency
- **THEN** 注入审查提示词的并行扇出上限为 2

### Requirement: 429 记忆降档

跨 run 记忆：

- **WHEN** run 启动生成扇出上限时，检测到上一轮同车道 run 的归档 jsonl 中存在 429 终态（HTTP 429 / 错误码 1302 / rate_limit）的子代理死亡记录
- **THEN** 本次注入的扇出上限在配置值基础上折减至 1；扫描缺失或异常时按原配置值放行（fail-open，不阻塞派发）

run 内记忆（提示词契约）：

- **WHEN** run 主体收到子代理 429 终态
- **THEN** 契约要求后续波次在飞上限不得回升（不高于已降档值），重派前等待 ≥60 秒，同 run 第二次 429 后等待 ≥180 秒；违反沿既有「违反 = run 判失败」语义

#### Scenario: 上轮 429 后的新一轮审查

- **WHEN** 上一轮 run 存在 3 条 429 子代理死亡记录，新一轮 run 启动注入
- **THEN** 提示词扇出上限为 1 且契约含 run 内记忆条款

### Requirement: 连续 429 死亡升级告警

- **WHEN** run 收尾统计到本 run jsonl 中 ≥3 个子代理以 429 终态死亡
- **THEN** 经 AdminStore.append_if_absent 直写一条告警（不入处置链，先例：lane_preflight 的 ensure_lane_env_alert），内容含 run id、死亡分片名与计数；少于 3 条不发；同 run 至多一条（dedup_key 含 run id）

#### Scenario: 重现 11-24 形态

- **WHEN** 某审查 run 出现 b2/b3 首发死亡加 b2 重派再死（共 3 条 429 终态）
- **THEN** run 收尾产生单条 429 升级告警
