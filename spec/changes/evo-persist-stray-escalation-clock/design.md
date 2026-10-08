# design.md

## 上下文

- 事故面：potplayer-base 主树 92 个未跟踪散件（现值）、告警 34 条零处置、HEAD 树 verify-evidence/ 689.1MB（67 文件），两次整包入库（c91213f、6f1042e）。
- 机制现状：落位契约（core/verify_contract.py:154 DEFAULT_EVIDENCE_DIR_TEMPLATE）、分级留存（evidence_retention.max_binary_bytes 缺省 10MB）、升级告警（maintree_untracked_stray_escalated：滞留≥24h 或体积≥500MB，stray_wip.py:52-58）均已合并；升级裁决三执行器已上线（admin_actions.py:3146/3230/3506）。
- 缺陷实锤：stray_wip.py:202 _untracked_registry 纯内存 dict；restart_history.jsonl 8 次重启，4 条同指纹告警的 first_seen 均落在重启后约 70 秒——一次性告警与 24h 升级双双被重启击穿；escalated 0 条、体积升级差 2.9%（509,103,122 字节 < 524,288,000）未触发属巧合。

## 方案

### 1. 注册表持久化（core/worktree_manager/stray_wip.py）

- 落位：.fenix/ 下运行时状态文件（与既有 stray 通道状态同区），内容为指纹→{first_seen, paths, last_alerted_at} 映射；
- 写时机：每轮盘点完成且注册表变更时原子落盘（临时文件+rename，沿框架既有原子写范式）；
- 读时机：盘点开始时载入，与内存态合并；文件缺失/损坏回退空表并告警（fail-open，不阻断主盘点）；
- 惰性清理：载入与每轮盘点时剔除盘上已消失的路径，集合为空的指纹整条删除。

### 2. 语义保持

- 30 分钟宽限、5 条阈值、500MB 体积阈值与指纹规则全部不变，只改时钟的存续介质；
- info 档 maintree_untracked_stray_stale 的「一次性告警」在持久化时钟下自然恢复跨重启去重，无需新信号类型。

### 3. 项目侧收尾（运维任务，非代码交付物）

- potplayer-base/.fenix/verify.yaml 显式声明 evidence_retention（语法参照 core/verify_contract_template.yaml），接线已上线字段；
- 活跃 tasks.md 中 7 处根 verify-evidence/ 落位路径改写为 .fenix/verify-evidence/<spec>/；
- 存量散件经已上线的 archive_untracked_stray / ignore_untracked_stray 裁决执行器清债（归档落 .fenix/stray-archive/），不新写迁移脚本。

### 4. 权衡与风险

- 不选「升级判定改用 mtime」：散件目录 mtime 会被部分写入刷新，时钟连续性不如持久化 first_seen 可靠。
- 持久化文件本身在 .fenix/ 忽略区内，不入库，无白名单问题。
- 风险：注册表与盘上实态漂移（路径改名/删除）——惰性清理每轮执行即可收敛；测试覆盖损坏降级与清理路径。
