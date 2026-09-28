# Design: add-code-review-sharded-out

## Context

code-review 车道的产物契约是「单一 `out-<run_id>.jsonl`、agent 自觉逐文件追加」。两晚事故取证（code-review-1790178542 / 1790180307，合计 $39.44 零产物）证明该契约在两个环节同时失效：

1. **结果回收**：agent 选择 async 子代理并行审查后，claude -p 非交互模式的 turn 结束即主进程退出，`Async agent launched` 元数据对应的批次结果永不回收。收工词两晚同款「已全部派发，等待批次完成通知」——「等」在非交互模式不存在。
2. **落盘时机**：主 agent 等待期通读 137 文件但零落盘（落盘被视为「最后汇总」），`read_progress` 的 `done` 恒 0。三轮提示词修复失败（第三次 run 收工词证明规则已读入但执行流不变）。

既有防线：`repo-code-review-gate` 硬门（`result_gate._check_repo_code_review_artifact`）收尾拦截有效但纯事后；dashboard 进度读侧 `code_review.read_progress` 的 `done` 只数主产物单文件。

## Goals / Non-Goals

**Goals**

- 分片直写：子代理批次结果即时落盘、即时可见，进度条动起来。
- 聚合消费：进度读侧、收尾 ingest、产物硬门三侧统一聚合口径，台账不丢分片数据。
- 机制性禁绝「等待收工」收工模式。
- 事中停滞告警：零进度 15 分钟主动上报，不再靠用户肉眼发现。

**Non-Goals**

- 不改变台账条目 schema（`items.jsonl` 字段不动）。
- 不改 dashboard 前端组件（`progress` 响应字段形状不变）。
- 不实现框架侧子代理编排（由框架切批派发）——保持 agent 自主决定是否并行，只改产物契约与回收机制。
- 不处理其他车道（impl-ocr / spec-review）的分片化。

## Decisions

### D1: 分片命名与发现 —— `out-<run_id>-b<N>.jsonl`，目录 glob

`core/code_review.py` 新增唯一工具函数 `shard_paths(project_root, run_id) -> list[Path]`（glob `out-<run_id>-b*.jsonl`，按 N 数值升序），三个消费侧（`read_progress`、`_read_code_review_out`、`_check_repo_code_review_artifact`）MUST 全部经它取分片集合——禁止任何一侧自写 glob（三处口径漂移是本仓高频事故模式）。

拒绝的替代：单文件加文件锁多写者（agent 端锁纪律不可依赖，两晚已证明）；框架切批派发（改动面大，Non-Goal）。

### D2: 聚合迭代顺序与去重 —— 分片优先、主产物兜底、按 file 去重

聚合读取顺序：分片（N 升序）→ 主产物。同 `file` 出现多行时保留**先见者**（分片是原始产出，主产物是汇总兜底；提示词已约束主 agent 不重写分片批次，去重是机械兜底）。

- `read_progress.done` 按**去重后**文件数计——进度允许因 agent 重写略虚高（行数和），去重计数让「done==total」语义严格成立。
- ingest `upsert_findings` 幂等（fingerprint 按 file+category+normalize_title），重复行天然合并，读侧去重仅为省 token 与保证确定性。
- `current` 取 mtime 最晚来源（主产物或分片）的末行 `file` 字段。

### D3: 禁等待收工 —— 提示词条款 + 分片路径注入派发 prompt

`agents/code-review.md` 落盘纪律段新增条款：收到 launched 元数据后 MUST 轮询分片文件推进（读分片行数→继续自审未派发文件→再查），MUST NOT 以等待通知为由输出收工词；派发子代理的 prompt MUST 包含该批的分片直写路径 `out-<run_id>-b<N>.jsonl` 与行结构要求（提示词无法机械强制子代理落盘，故叠加 D4 告警与既有硬门兜底）。

拒绝的替代：runner 侧禁用 Agent 工具（`--disallowedTools`）——会失去并行能力，137 文件单进程过慢；框架代为切批派发（Non-Goal）。

### D4: 停滞告警 —— admin_monitor 周期节拍检测

检测函数 `check_progress_stall(project_root, now) -> dict | None` 放 `core/code_review.py`（复用 `read_progress` 聚合口径 + manifest `requested_at` 算已运行时长），由 `core/admin_monitor.py` 既有周期节拍调用。触发条件：`running=true` 且聚合 `done==0` 且运行时长超 `admin.code_review.stall_alert_minutes`（缺省 15，非法值回退缺省）。告警经既有 `core/admin_store.py` 的 `AdminStore` 写入（`append_if_absent` 缺席去重原语；评审注：仓库中不存在 `AdminAlertStore`，本条按实际类名与 API 修正），去重键 `code-review-stall-<run_id>`（单 run 至多一条）；run 终态后不再触发（`running=false` 短路）。

拒绝的替代：dashboard 读侧触发（依赖前端轮询，分面未打开即失效）；独立定时器（复用 admin_monitor 节拍即可，少一个线程）。

设置页同步：`admin.code_review.stall_alert_minutes` 按既有约定（新增配置项必须带 Dashboard 界面）在 settings 分面 admin 作用域补输入项——此处为设置页改动，与 Non-Goal 中「不改 QualityTab progress 组件」不冲突（progress 响应字段形状不变）。

### D5: 硬门聚合口径 —— 存在性校验升级，覆盖率校验不动

`_check_repo_code_review_artifact(manifest, opath)` 签名扩展为接收分片列表（或改为传 project_root+run_id 内部解析），存在性判定改为「主产物与分片合计 ≥1 有效行」；「manifest 全覆盖」类后续校验（若有）口径不变。error 文案更新为聚合口径描述。

## Risks / Trade-offs

- **子代理不落分片**（提示词软约束）：D4 告警 15 分钟内可见 + 硬门收尾兜底——比现状（用户盯 0% 数小时）严格改善。
- **分片残留**：上一 run 的分片不会被误读（glob 以 run_id 为界）；归档清理沿用既有 runs 保留策略，不新增清理逻辑。
- **进度虚高**（agent 重写已落盘批次为不同行）：按 file 去重后计数，虚高可控；ingest 幂等兜底。
- **重复告警风暴**：单 run 去重键 + `running=false` 短路，节拍级频控由 admin_monitor 既有机制承担。

## Migration Plan

无数据迁移。旧 run 的产物（纯主产物）在新读侧聚合口径下行为不变（分片集合为空集时退化为单文件读取）。部署顺序无要求；生效需 daemon 重启（restart_request，supervisor 消费）。

## Open Questions

无——方案两晚事故取证 + 用户已确认（分片直写+聚合方向，full 模式立即执行）。
