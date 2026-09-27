# ADR-059：runs 产物只增不减，归档动作是离开顶层的唯一入口

date: 2026-09-09
status: accepted

## Context

`.fenix/runs/` 顶层 run 产物（`*.jsonl`）若允许读取方顺手删除（如按 `runs.keep` 数量自动裁剪），其保护条件在「多实例 + 旧码 + STATE.md 异常」组合下形同虚设——任何持有旧码的实例都能绕过归档机制直接删除运行证据。runs 的留存语义必须由唯一裁定约束所有读写方。

## Decision

- runs 顶层产物**只增不减**：不设任何按数量/时间的自动裁剪路径，相关代码与配置 UI 整体删除而非注释禁用（保留死代码会诱导未来恢复该语义）。
- run 产物离开顶层唯一入口 = spec 归档动作：归档时按 run_id→spec 推断将属主 run 文件移入 `runs/archive/`，只移动不删除、不改内容。
- run_id→spec 推断逻辑单一实现（run_files 公开名），归档脚本与框架复用同一实现、不复制正则；分层依赖方向 dashboard→agent_runner，反向禁止。
- 归档动作中的 runs 搬移 fail-open：单文件失败记 warning 继续其余，归档失败不阻断 change 归档主流程。
- 未来容量治理需求必须以带审计的新机制重新立项，不得恢复匿名自动裁剪。

## Consequences

- 顶层增长接受（单 run 约 50KB–1MB，由归档动作自然分流）；dashboard 等读取方不承担删除职责。
- 已删除的配置键（如 `runs.keep`）在存量 YAML 中残留无害（无 schema 强校验、无消费方）。
