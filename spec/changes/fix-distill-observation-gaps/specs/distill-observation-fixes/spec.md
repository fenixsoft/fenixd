## ADDED Requirements

### Requirement: 归档清单剔除豁免蒸馏车道

`aggregate_org` 的「已归档 SPEC（STATE.archive.md 清单）名下 run 全窗剔除」规则 MUST 对 `knowledge-distiller` lane 豁免：raw `agent_type == "knowledge-distiller"` 的 run 无论其 spec 段是否在归档清单，MUST 计入现役车道统计（runs/成功率/时长/活动桶全窗口径与其他 lane 一致）；其余 lane 的剔除语义 MUST NOT 变化。豁免判定 MUST 基于剔除检查点的 raw agent_type（现行代码剔除在前、LANE_ALIASES 归一在后，不得因重排序引入行为变化）。

#### Scenario: 已归档 SPEC 的完成批出卡

- **WHEN** 今日窗口内存在一条 done 终态的 knowledge-distiller 产物，且其 spec 段（如 `2026-11-02-fenix-prototype`）在归档清单中
- **THEN** 运营线「知识蒸馏」卡 runs 计 1、成功率分母含该 run、last_activity 更新——与该产物在 get_runs 的归属/终态一致

#### Scenario: 非蒸馏 lane 剔除不回归

- **WHEN** 已归档 SPEC 名下存在 impl-/planner- 等其他 lane 的 run 产物
- **THEN** 这些 run 仍被全窗剔除（现役车道统计不含完结历史实现过程），剔除行为与豁免前完全一致

### Requirement: 蒸馏批心跳保活

蒸馏批 spawn 等待期间 MUST 向批产物定期追加非终态心跳事件行：心跳间隔 MUST 安全低于 `_RUN_STALE_SECONDS`（1800s）——长跑批（超过 stale 阈值）MUST NOT 被读侧判 stale、MUST NOT 被 retention 提前移出活跃目录；批收尾终态行 MUST 追加为末行（覆盖心跳的 running 判定）。心跳写入 MUST fail-open（OSError 静默吞掉，不阻断批执行，与批产物既有写口径一致）；心跳线程生命周期 MUST 严格限于批执行窗口（批开始启动、批收尾停止，异常退出路径不留存活线程）。

#### Scenario: 长跑批不被判 stale

- **WHEN** 蒸馏批 spawn 持续超过 1800s（如网关 stall 慢跑）且心跳按间隔落盘
- **THEN** 产物末行为心跳行（读侧判 running 而非 stale），retention 不移动该产物，批收尾 error 终态行正常追加于同一文件

#### Scenario: 终态覆盖心跳

- **WHEN** 批收尾（成功或失败）在心跳行之后追加终态行
- **THEN** classify_run 按末行判定 done/error（心跳行不影响终态判定），产物归档/成功率口径正确

#### Scenario: 心跳写失败不阻断批

- **WHEN** 心跳追加遇 OSError（产物目录不可写等）
- **THEN** 心跳静默放弃本轮，批 spawn/校验/提交/台账行为与无心跳形态完全一致，无异常外泄
