# Design: frozen-scenario-contract-versioning

## D1: contract_version 字段与冻结文件格式

冻结场景文件（test_scenarios.json）根对象增加字段：
```json
{
  "schema_version": 2,
  "contract_version": 1,
  "scenarios": [...]
}
```

- `contract_version`：整型，标识冻结集所符合的场景验收契约规则版本。首次引入时设为 1（v1 无 navigate 必含规则）。
- `CURRENT_CONTRACT_VERSION = 2`：v2 含「web 场景 MUST 含 navigate 步骤」规则。常量定义于 scenario_gate.py。

## D2: 契约迁移逻辑

### D2.1 迁移函数签名

```python
# core/pm_engine/verification/scenario_gate.py
def migrate_frozen_contract(
    scenarios: list,
    current_version: int = CURRENT_CONTRACT_VERSION,
) -> tuple[list, list]:
    """迁移冻结场景集到当前契约版本。
    Returns: (migrated_scenarios, pending_replan_ids)
    migrated_scenarios: 已更新 schema_version 的场景列表（已剔除无法迁移项）
    pending_replan_ids: 需要重新出题的场景 name/id 列表
    """
```

### D2.2 v1→v2 迁移（navigate 补齐）

对 contract_version < 2 的冻结集：
1. 逐场景检查：steps 中是否有 action=run 且 command 含 `http://` 或 `https://` 的命令，且无 action=navigate 步骤
2. 若有：提取 URL（正则 `https?://[^\s"']+`），生成 navigate 步骤 `{"action": "navigate", "url": <提取的 URL>}` 插入 steps 首位，标记 `schema_version = 2`
3. 若无明确 URL 且无 base_url 字段：将场景名移入 pending_replan 列表，从当前冻结集剔除

### D2.3 迁移函数调用点

pipeline.py `_load_frozen_or_escalate` 中：
1. 读取冻结文件后、调用 validate_scenario_dicts 之前
2. 读取 contract_version（缺省 1）
3. 若 contract_version < CURRENT_CONTRACT_VERSION：调用 migrate_frozen_contract
4. 迁移结果：写回冻结文件（scenarios 已更新、contract_version 已升）；pending_replan 非空时记录日志
5. 迁移后场景（含 navigate）再进入 validate_scenario_dicts 校验（navigate 步骤已补齐，应过校验）

## D3: 全场景过时处理（aborted）

当 migrate_frozen_contract 返回 pending_replan 包含所有场景时：
1. pipeline.py 中标记 `_frozen_aborted = True`，不置 blocked/env_blocked
2. 调用现有 replan 逻辑：删除 test_scenarios.json（触发下轮 planner 生成 contract_version=2 的场景集）
3. INFO 日志：「契约升级全场景过时、已自动重新出题，旧场景数=XX」

## D4: 迁移安全性约束

- 幂等：contract_version >= CURRENT_CONTRACT_VERSION 时零操作（不重复迁移）
- 不修改非 navigate 相关字段：只增 navigate 步骤、不改命令/断言
- 迁移后写回冻结文件前 MUST 校验：新 contract_version 已写入，避免写回失败时下次重复迁移

## D5: 测试策略

tests/test_frozen_contract_evolution.py（新建）：
- 用 mock 冻结文件（JSON fixture）覆盖 v1→v2 迁移、v2 直通、全过时 aborted、部分迁移、幂等性
- patch pipeline._load_frozen_or_escalate 路径，不需启动 verify server