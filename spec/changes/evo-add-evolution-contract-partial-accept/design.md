## Context

core/evolution.py:41 TODO_SECTIONS 三值枚举；read_contract（:2159-2222）在 :2205-2206 对越界 section 抛 ContractError。core/agent_runner/maintenance_runs.py:1043 先 _salvage_evolution_out（:1193，只救文件缺失/不可解析）→ :1048-1068 except ContractError 直接 contract=None 整轮作废 → :1150-1159 finally 清理删除产物文件；对照 :1109-1123「条目不足」已有 partial 语义（落合法条目、run_ok=False、水位不推进、下检查点幂等补齐）。输入侧 core/evolution.py:550-558/:577-584 对未知小节为跳过+WARNING 宽口径。

## Goals / Non-Goals

- Goals：拒绝粒度从「整份」细化到「单条」，与输入侧宽口径及既有 partial 语义对齐；失败现场留档。
- Non-Goals：不新增模型回问回路；不改枚举本身与告警文案；不放非法数据入库。

## Decisions

- D1 选「部分回收」而非「1 次修复回问」：自动重试（fenixd.py:4396 水位不推进下一检查点自动重试）已实测自愈，回问属重复投资；部分回收是一次重跑省为一次部分重跑，改动集中在 read_contract 返回形态与既有 partial 分支复用。
- D2 read_contract 返回形态向后兼容：默认行为不变（或新增 lenient 参数），仅 evolution 落库链路启用宽口径，其他调用方不受影响。混合产物在宽口径下不再抛 ContractError，落库侧自然走 ``contract is not None`` 常规分支、由既有 partial 判定（maintenance_runs.py:1072-1073 计算、:1109-1123 落地）获得 run_ok=False 与水位不推进；except ContractError 分支仅保留全非法与文件级错误。
- D3 全非法仍 fail-closed：防坏数据入库的原始动机保留。
- D4 失败现场留档约定：仅「有合法条目的部分接受」路径留档——:1150-1159 finally 清理前把产物文件改名为 ``<原路径>.failed`` 同目录保留（run_id 每轮递增不碰撞；``_delete_evolution_out`` 对已改名路径 missing_ok 幂等安全），错误文案附留档路径供归因；全非法拒绝路径行为与现状一致（含清理），不扩大留档面。

## Risks / Trade-offs

- 部分接受会让「模型大面积跑偏」退化为多条跳过+少量登记：由「全非法仍拒绝」与既有「条目不足」阈值兜底。
- 留档失败产物增加少量磁盘占用：与 .parts 抢救同目录惯例，可接受。