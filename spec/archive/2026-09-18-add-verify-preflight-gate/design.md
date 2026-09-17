# Design: add-verify-preflight-gate

## Context

验证契约/环境错误当前在场景执行甚至整轮结束后才暴露，四个实锤事故（fenix-server add-web-ui 入口错、add-ssh-foundation prepare 裸跑、自证工具零调用、planner 侦测蒸发）共同指向「确定性错误晚暴露 + 证据湮灭」。框架已有资产：`validate_contract` 三段自证 CLI（起草期在用）、`verify_contract_missing` 信号通道、`scenario_static_findings.json` 情报注入机制、`CommandVerifyServer.failure_note` 失败描述。本设计全部复用既有资产做「前移」，不新建机制。

## Goals / Non-Goals

**Goals**
1. 入口不存在类确定性错误：spawn 前 fail-fast，场景执行数为 0，错误信息含修复指引。
2. 契约 mtime 变化后首轮消费期轻量自证，后续轮次零开销。
3. spawn 启动即死错误（Cannot find module 等）证据落盘进告警。
4. planner 侦测到的契约偏差必送达 admin（落盘 + prompt 注入）。

**Non-Goals**
- 不重复 `add-main-tree-deps-provision` 的依赖供给（预检在其后执行，两案验收时对齐边界）。
- 不重复 `add-verify-contract-autodraft` 起草期三段自证（消费期只做轻量版，不跑 prepare）。
- 不做通用 shell 命令静态分析（复合命令保守跳过，零误杀优先）。
- 不做契约语法校验器（YAML 解析失败已有 load 侧 warning 路径）。

## Decisions

### D1: 入口解析器——最小确定性，不追求完备

`core/verify_contract.py` 新增纯函数 `resolve_entry_path(cmd: str, cwd: Path) -> Optional[Path]`：

- `shlex.split` 失败（引号不配对）→ None（跳过）。
- 可执行名（argv[0] 去目录）∈ {`node`, `nodejs`, `tsx`, `ts-node`, `bun`, `deno`} 且命令无 shell 元字符（`&&` `||` `|` `;` `>` `<` `$(` 反引号）→ 取第一个非 `-` 开头参数为入口。
- 其余形态（npm run、python -m、复合命令）→ None（跳过预检）。
- 入口按 cwd 解析绝对路径返回；解析出但文件不存在 → 预检失败。

确定性优先：只拦「100% 是错误」的形态（node + 单脚本 + 文件不存在），其余一律放行走既有探活兜底。误杀率零、漏检交给自证与探活。

调用点（两处，均在 spawn 前）：
- `verification.py::_serve_command_in_worktree`（L548 Popen 前）：cwd=worktree 根。
- `verification.py::_ensure_app_reachable` 兜底 spawn（L860 Popen 前）：cwd=项目根；失败时错误串含候选提示（同目录扫描 `*.js`/`index.js` 存在性）。

失败返回形态：`(False, False, "入口存在性预检失败: <路径> 不存在（候选: <存在候选>…）")`，上层既有分支将其按 `_escalate_env_blocked` 同款路径处理并写 `verify_contract_missing` 信号（description 前缀「入口存在性预检失败」，与契约缺失信号同通道、severity=major、evidence 附 cmd 原文与解析结果）。

### D2: 消费期轻量自证——mtime 快照门

`core/verify_contract.py` 新增 `selfcheck_contract_light(project_root, logger) -> Optional[str]`（返回错误串或 None）：

1. 读 `.fenix/verify-serving/contract_selfcheck.json`（{mtime_ns: ...}）；契约 mtime_ns 一致 → 返回 None（零开销）。
2. serve 段合法性：kind 枚举、static 模式 root 目录存在、command 模式 cmd 非空（复用 load 后的 VerifyContract 对象 + 原始 YAML serve 段，同 `validate_contract` 第 2 步口径）。
3. ready 探针鉴别力自检：仅当当前已有可达实例时跳过（无实例时不起实例——这是与三段自证的关键差异：消费期不承担构建/启动成本）。
4. 通过 → 写 selfcheck 记录；失败 → 返回错误串（含段落与原因）。

调用点：`verification.py` `_run_three_stage_verification` 阶段 2 前（阶段 1 场景冻结复用之后），契约存在且自证返回错误 → 走 D1 同款信号通道 fail-fast。selfcheck.json 属运行时产物（.fenix/ 下），不入库；admin 修正契约 → mtime 变化 → 下轮自动重证，无需失效指令。

### D3: 兜底 spawn 证据捕获——最小改动

`_ensure_app_reachable` 兜底 Popen（L860）：`stdout=DEVNULL, stderr=DEVNULL` → `stderr=subprocess.PIPE` 不可行（无 drain 会堵管道），改为 `open(boot_log, "ab")` 追加写句柄（`.fenix/verify-serving/<spec>-boot.log`，每轮启动前 truncate 控制大小），Popen 持句柄、进程退出后关闭。探活最终失败分支：读 boot.log 尾部 ≤2KB 附入返回错误串 → 现有 `_escalate_env_blocked` 链路自动带进告警 evidence（零新通道）。worktree 路径 `CommandVerifyServer` 已有 failure_note 机制，仅补充 boot.log 同款落盘（构造参数传入句柄）。

### D4: planner findings——扩展 scenario_static_check 表驱动

`core/verify_engine/scenario_static_check.py` 已是 pattern 表驱动落盘机制。新增独立扫描函数 `scan_contract(project_root) -> list[dict]`（不进场景扫描器，契约检查与场景无关），落盘 `.fenix/verify-progress/<spec>/contract_findings.json`（覆盖写，同款 JSON 结构）。调用点：planner-plan 产物验收通过后（`pm_engine` 出题完成处，fail-open try/except）。

初始规则表（机械可查，误报即删）：

| rule_id | 触发 | severity |
|---|---|---|
| `serve_entry_missing` | serve.cmd 入口（D1 同源解析器）文件不存在 | high |
| `serve_entry_vs_start_mismatch` | serve.cmd 入口 ≠ package.json start script 入口 | info |
| `serve_entry_no_port_injection` | cmd 无 {port} 且无 $FENIX_VERIFY_PORT（已有 load 侧 warning，补落盘进 findings 让 admin 可见） | info |

prompt 注入：`prompt_builder.py` 新增 `_contract_findings_section(spec_name)`（克隆 `_scenario_static_findings_section` 骨架），挂载点为 Administrator 处置派发 prompt（admin 职责含修正契约，judge 不修契约故不注入 judge）。

### D5: 与 add-main-tree-deps-provision 的边界

该案在 `_ensure_app_reachable` 主树 prepare 前做依赖供给（装 node_modules）；本 SPEC 预检在 prepare 之后、spawn 之前执行入口检查——顺序：供给 → prepare 构建 → 入口预检 → spawn。两案改同一函数区域，**后合并的一案负责 rebase 对齐**；需求面无交叉（供给管依赖、预检管入口）。若该案先落地，本 SPEC tasks 相应步骤直接在其插入点后追加；若本 SPEC 先落地，预留注释锚点。

## Risks / Trade-offs

- **D1 漏检**（复合命令、非 node 运行时）：接受——漏检走既有探活兜底，比误杀好；规则表可持续扩。
- **D2 mtime 粒度**（同纳秒内改回原内容）：理论竞态，实际 admin 修正必跨秒，接受；selfcheck 失败不写记录，下轮自动重证。
- **D3 boot.log 增长**：每轮 truncate，单轮上限无界（服务自身输出）——验证实例生命周期短（分钟级），接受；后续需要时加 size cap。
- **D4 双 findings 文件**（scenario_static_findings.json 与 contract_findings.json 并存）：命名空间隔离比混表干净，注入段各自独立，接受。

## Migration Plan

纯增不改既有语义：契约正确的项目每轮多一次毫秒级检查；契约错误的项目从「整轮空转」变「预检 fail-fast」。无配置新增、无 schema 变更、存量契约零迁移。selfcheck.json / boot.log / contract_findings.json 均为运行时产物（.fenix/ 下不入库）。

## Open Questions

（无——D5 合并顺序问题按「后合并者 rebase」约定处理，无需用户决策。）
