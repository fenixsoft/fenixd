# dsh 通道切换与回切运行手册

本手册覆盖把 agent 执行通道从 `claude` 切换到 `dsh`（DeepSeek 官方 CLI）的完整运维路径：切换步骤、回切步骤、故障处置与真实验收执行指引。适配层架构背景见 ADR-271（`spec/knowledge/adr/ADR-271-pluggable-agent-harness.md`）与母设计文档（`docs/superpowers/specs/2026-10-13-multi-harness-adapter-design.md`）。

本手册是依赖链第四环（`spec/changes/dsh-primary-acceptance-switch/`）的交付物。依赖链前三环：

| 环 | SPEC | 交付 |
|---|---|---|
| SPEC-1 | `add-harness-adapter-layer` | `core/agent_runner/harness/` 协议层（protocol/claude_adapter/one_shot） |
| SPEC-2 | `add-fenix-dsh-bundle` | dsh-bundle（工具映射/模型 patch/假端点 fixtures） |
| SPEC-3 | `add-dsh-adapter-integration` | `dsh_adapter.py`（spawn/在飞判定/事件投影/可观测性三件套） |

**边界**：本手册与验收链路不翻转任何缺省值。`agent.harness` 缺省值是否由 `claude` 翻转为 `dsh` 由用户依据验收报告裁决（见文末报告模板第六节）；翻转本身属后续一次性微变更。

## 版本兼容表

| 组件 | 钉定版本 | 说明 |
|---|---|---|
| dsh CLI | `0.2.0-rc.2` | 版本白名单钉在 `core/agent_runner/harness/dsh_adapter.py` 的 `DSH_VERSION_WHITELIST`（随本表走代码，不做配置键） |
| fenix-dsh-bundle | 与 dsh 运行时同步升版 | 升级 dsh 必须同步升版 Bundle 并重测（`npm install` + 全量冒烟） |
| Node.js | 18+ | dsh 运行时 |

## 一、切换步骤（claude → dsh）

### 1. Bundle 安装

按 `dsh-bundle/README.md` 安装段执行（三步，幂等可重跑）：

```bash
# 1) Bundle 目录装依赖（npm 自动安装精确版 peer）
cd <repo>/dsh-bundle && npm install

# 2) 以 link: 形态挂入自定义 profile（DSH_HOME 隔离部署示例）
DSH_HOME=$DSH_HOME dsh --profile fenix --from-default-profile headless   # 首次创建 profile
DSH_HOME=$DSH_HOME dsh plugin --profile fenix add "link:<repo>/dsh-bundle"
# 并确认 $DSH_HOME/profiles/fenix/package.json 的 dsh.profile.bundles 含 "fenix-dsh-bundle"

# 3) 验证挂载
DSH_HOME=$DSH_HOME dsh --profile fenix --dump-config | grep fenix
```

**检查点**：`--dump-config` 输出可见三条 insert 与各覆盖条目。若只见 `fenix-model-config` 相关段而**无 `headless-runner` 段**，Bundle 未挂成——headless 加载器会无限等待（见故障处置 3.4）。

### 2. 配置切换

在项目 `.fenix/config.yaml` 中配置（两个键均为热载：每轮 dispatch 时 `resolve_adapter_from_config` 重新解析，改完下轮 run 即生效，无需重启 daemon）：

```yaml
agent:
  harness: dsh          # 合法值 claude | dsh（单源：core/agent_runner/harness/__init__.py）
  dsh_profile: fenix    # 缺省 fenix（Bundle README 约定名）
  # dsh_home: /path     # 可选；缺省空 = 继承进程环境。DSH_HOME 隔离部署由此键指定
```

### 3. 健康检查确认

```bash
# 通道级健康门（版本白名单 + Bundle 挂载探测），三条命令任一即可：
python3 -c "from core.agent_runner.harness import resolve_adapter; \
resolve_adapter('dsh', {'agent': {'harness': 'dsh'}}).check_health(); print('OK')"

# 或走验收脚本的 accept 自检预演（含凭据/健康门/claude 基线 CLI 全项，零真实调用）：
python3 bin/dsh_acceptance.py accept

# 或无凭据假端点冒烟（三车道全链，~10 秒）：
python3 bin/dsh_acceptance.py smoke
```

**检查点**：三条均应成功且无 stderr 报错。此后 daemon 的每轮 dispatch 都会在前置段自动执行 `check_health()`——健康门不过该轮 fail-fast 换道处置，不会带病 spawn。

## 二、回切步骤（dsh → claude）

### 1. 配置回切

```yaml
agent:
  harness: claude
```

同样热载生效。**在飞 run 不受影响**：每个 run 的 adapter 在 dispatch 时解析并持有，在飞的 dsh run 会以 dsh 通道继续跑到收口，不会被配置切换打断——这是既有排水语义（planned-restart-drain 同源思路：配置切换只影响后续 dispatch，不截断在飞进程）。

### 2. 排水确认

需要立即清空在飞 dsh run 时（如 Bundle 故障需要止血），按规划性重启排水语义处置：

```bash
# 观察在飞：dashboard active_runs 或进程树
ps -ef | grep "dsh.*headless" | grep -v grep

# 温和路径：等在飞 run 自然收口（run_timeout_seconds 兜底），期间新 run 已走 claude
# 急迫路径：规划性重启（supervisor SIGTERM → 排水窗口 → 重启；窗口 agents.run_drain_max_seconds，缺省 60s）
```

**检查点**：配置回切后新派发的 run 的 run jsonl 首行 `harness` 字段应回到 `claude`（`ls <project>/.fenix/runs/` 最新文件首行）。

### 3. Bundle 卸载（可选，仅在彻底弃用 dsh 时）

```bash
DSH_HOME=$DSH_HOME dsh plugin --profile fenix remove fenix-dsh-bundle
```

`agent.harness: dsh` 而 Bundle 未挂载时，dispatch 前置健康门会 fail-fast（check_health 报 Bundle 挂载探测失败并附修复指引），不会静默回退 claude——回切请务必改配置，不要只卸 Bundle。

## 三、故障处置

### 3.1 版本漂移（dsh 升级后健康门拒绝）

**症状**：`check_health()` 报版本白名单不符（如 `dsh 版本 0.2.1 不在白名单 ("0.2.0-rc.2",)`）。

**处置**：白名单是设计决策（design D5：钉版本防事件流 schema 漂移），不做配置豁免。按序操作：

1. 查看 dsh-bundle README 版本兼容表是否已发布配套升版；有 → 升级 Bundle（`cd dsh-bundle && npm install`）并同步升白名单（改 `DSH_VERSION_WHITELIST`，属代码变更走 SPEC）。
2. 无配套版本 → 回退 dsh：`npm install -g @deepseek-ai/dsh@<白名单版本>`。
3. 临时止血：`agent.harness: claude` 回切（热载），等升版就绪再切回。

### 3.2 429 同刻叠峰（真实模型限流）

**症状**：真实验收（`accept --go`）多车道并发时撞 provider 限流；特征是失败集中在同一时刻窗（如每日网络断供窗口、整点配额重置）。

**处置**：

1. 429 处置属 provider 链层既有机制（circuit/failover），验收车道超时不豁免限流失败——`accept --go` 证据里 `error` 带 429 形态的，先核对 provider 链配置（`llm.providers` 多路 failover）再重跑。
2. 错峰：避开已知断供窗口（本仓部署每日 04:30 前后有网络断供窗口先例）重跑 `accept --go`。
3. 假端点冒烟（smoke）不依赖真实凭据，429 与它无关——smoke 失败按产品缺陷排查。

### 3.3 投影异常（事件投影计数/坏事件非零）

**症状**：run_metrics 里 projection 计数异常——`bad_events` 三分类（`json_parse_failed`/`unknown_type`/`over_limit_truncated`）任一非零，或 `events_received_unknown` 增长。

**处置**：

1. 先取原始事件 dump 旁路对账：`<project>/.fenix/runs/<run_id>.dsh-events.jsonl`（投影层的输入真相源）。
2. `unknown_type` 非零 → dsh 版本事件 schema 漂移（新事件类型未入词表）：核对 dsh 版本是否仍在白名单，漂移即回 3.1 处置。
3. `json_parse_failed` 非零 → 事件流截断/污染：单发偶发可重跑观察；连续复现按产品缺陷立案（附 dump 旁路文件）。
4. 投影观测是旁路职责（计数失败不阻断投影），投影异常本身不判 run 失败，但验收判定（`evaluate_agent_lane`）会 fail-loud——验收报告第二节会如实呈现。

### 3.4 健康检查失败 / headless 挂起

**症状**：`check_health()` 报 Bundle 挂载探测失败；或 dsh headless 进程起后无事件产出直至 run 超时。

**处置**：

1. `--dump-config` 无 `headless-runner` 段 → Bundle 未挂成，回第一节步骤 1 重装。已知形态：bundles 缺 headless-runner 注入时 headless 加载器 `await` 永等（无限挂起），run 只能靠 `run_timeout_seconds` 超时收割。
2. `dsh` 不在 PATH → `npm install -g @deepseek-ai/dsh@<白名单版本>`（accept 自检的修复指引同此）。
3. 残留进程组清理：验收脚本超时兜底已做进程组两段式收割（SIGTERM→SIGKILL）；手工兜底 `pkill -f "dsh.*headless"` 后核对 `ps` 清零。

## 四、真实验收执行指引

真实全链验收（真实模型调用）**由用户发起**，agent 只完成预演与信号落位（`.fenix/todo.md` 人工队列）。执行命令：

```bash
# 预演（零真实调用；自检全绿才继续）
python3 bin/dsh_acceptance.py accept

# 真实执行（人工显式 --go；自检未过会拒绝执行）
python3 bin/dsh_acceptance.py accept --go
```

前置条件（`accept` 自检项，缺一会列缺失项+修复指引）：

| 检查项 | 要求 |
|---|---|
| dsh 可用 | PATH 命中且版本在白名单 |
| provider 链凭据 | `llm.providers` 至少一项 baseurl+apikey 齐备（值全程脱敏） |
| dsh 健康门 | 版本白名单 + Bundle 挂载探测通过 |
| claude CLI | PATH 命中（基线车道用；可用 `--no-claude-baseline` 跳过） |
| 临时夹具可写 | 系统临时目录可创建可删除 |

预计耗时：4 车道（claude 基线 implementer + dsh implementer/verifier/judge）× 单车道 timeout 900s 上限，实测通常 10 分钟内；报告落 `.fenix/verify-evidence/dsh-primary-acceptance-switch/dsh-acceptance-real-*`。

夹具为即测即弃（临时目录 + 唯一前缀 `dshacc-<时间戳>-<随机>`，finally 自动清理含 runs 产物）。手工清理兜底（仅在脚本异常中断且带 `--keep` 调试时需要）：

```bash
# 1) 按唯一前缀清夹具目录（前缀见 accept/smoke 输出 meta.prefix）
rm -rf /tmp/dshacc-*          # 粗清：本机临时区内全部验收夹具
# 2) 核对 ~/.dsh 无夹具残留
ls ~/.dsh | grep dshacc       # 应无输出；有则按前缀删除对应 profile/sessions 项
# 3) 核对真实项目注册表零污染：验收夹具从不写注册表（进程内构造隔离），如见
#    .fenix/registry 出现 dshacc- 前缀条目属异常，按孤儿实例流程清退
```

## 五、验收报告模板

脚本 `accept --go` 产出的报告与下述模板逐段同构（`render_report_md`）；假端点 smoke 报告同形，但第四节标注假端点证据栏。**翻转决策只认真实证据**——假端点证据与真实模型行为差异须以 `accept --go` 产出复核。

```markdown
# dsh 通道验收报告（accept）

- 生成时间：<UTC ISO8601>
- 夹具前缀：`dshacc-<ts>-<rand>`（即测即弃，已清理）
- 判定：**PASS/FAIL**（fail-loud：任一检查不过即 FAIL）

## 一、各车道终态
| 车道 | 终态 | 在飞判定 | turns | session | 耗时(s) |
|---|---|---|---|---|---|
| claude-implementer（基线） | result | ✓ | <n> | 有 | <s> |
| implementer | result | ✓ | <n> | 有 | <s> |
| verifier | result | ✓ | <n> | 有 | <s> |
| judge | returncode=0 | ✓ | - | - | <s> |

## 二、投影计数与坏事件统计
| 车道 | final 收到 | 投影各类型 | 坏事件（解析失败/未知类型/超限截断） |
|---|---|---|---|
| implementer | ≥1 | {"session":1,"tool_call":<n>,...} | 0/0/0 |
| verifier | ≥1 | {...} | 0/0/0 |
| judge | -（one-shot 通道不落投影） | - | - |

## 三、usage 降级情况
| 车道 | usage_source | input | output | cost_usd |
|---|---|---|---|---|
| implementer | available/降级形态 | <n> | <n> | <n or null> |
| verifier | ... | ... | ... | ... |
| judge | -（judge 通道不落 run usage） | - | - | - |

## 四、耗时对比 claude 基线
| 车道 | dsh(s) | claude(s) | 倍率 |
|---|---|---|---|
| implementer | <s> | <s> | <ratio> |
（基线不可用时本节标注 **unavailable** + 原因，不伪造对比结论）

## 五、产物硬门结果
| 车道 | 结果文件 | result gate selfcheck |
|---|---|---|
| implementer | `<worktree>/.fenix-run-result.json` | PASS |
| verifier | ... | PASS |
| judge | -（judge 通道无结果文件产物） | - |

## 六、默认值翻转决策申请（用户裁决项）

> 本段为**决策申请**，不是决策。`agent.harness` 缺省值是否由 `claude` 翻转为
> `dsh` 由用户依据本报告裁决；翻转属后续一次性微变更（config 缺省值 +
> ADR-271 补记），不在验收链路自动化范围内。

- 建议：<证据齐备，可进入真实验收或由用户裁决翻转 / 存在失败项，不建议翻转>
- 影响面：<耗时对比见第四节；假端点证据与真实模型行为差异需以真实证据复核>
```

## 六、交叉引用

- ADR-271 可插拔 harness 抽象：`spec/knowledge/adr/ADR-271-pluggable-agent-harness.md`
- 母设计文档（多 harness 适配层总设计）：`docs/superpowers/specs/2026-10-13-multi-harness-adapter-design.md`
- SPEC 依赖链：`spec/changes/add-harness-adapter-layer/`（SPEC-1 协议层）→ `spec/changes/add-fenix-dsh-bundle/`（SPEC-2 Bundle）→ `spec/changes/add-dsh-adapter-integration/`（SPEC-3 DshAdapter）→ `spec/changes/dsh-primary-acceptance-switch/`（本 SPEC：验收与切换运维）
- 验收脚本：`bin/dsh_acceptance.py`（fixture/smoke/accept 三模式；测试 `tests/test_dsh_acceptance.py`）
