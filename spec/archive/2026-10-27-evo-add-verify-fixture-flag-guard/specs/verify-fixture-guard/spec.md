# verify-fixture-guard Specification

## Purpose

让验证场景自注册的探针夹具一律带 fixture 标记，杜绝夹具假告警进入人工告警聚合横幅；规范触达出题端（提示词）、知识层（领域文档）与守卫层（静态扫描情报）三处。

## ADDED Requirements

### Requirement: 场景夹具注册必须打 fixture 标记

验证场景在场景命令内自注册探针项目（/tmp 扫描根外临时路径）时，MUST 以 fixture=True 调用 Registry.add_project。

#### Scenario: 正确打标

- **WHEN** 场景命令包含 reg.add_project(SROOT, name=…, fixture=True)
- **THEN** 静态扫描不产出任何情报

#### Scenario: 显式 False 或缺省不传

- **WHEN** 场景命令包含 add_project( 调用且实参未含 fixture=True（显式 fixture=False 或缺省不传）
- **THEN** 静态扫描产出 judge 情报，提示按 ADR-163 打标（点名查询零改动）

### Requirement: 规范可被出题端与知识层触达

出题提示词与领域文档 MUST 同时载明该规则，含正反示例与依据（ADR-163）。

#### Scenario: 出题端有规则

- **WHEN** planner 按出题提示词生成验证场景
- **THEN** 提示词含「场景注册夹具 MUST fixture=True」规则与反例形态说明