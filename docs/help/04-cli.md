# CLI 操作手册

Fenix 提供 8 个 `/fenix-*` 斜杠命令（skill）与若干 `bin/` 辅助脚本。前者覆盖日常使用的完整动线（从提出需求、查看状态到最终审批），后者是支撑这些命令与 daemon 的底层工具。本章逐个讲解每个命令的用途、触发方式与产出。

## /fenix-* skill

### /fenix-new — 提出需求、创建 SPEC

想提出新需求时使用。既可以显式输入 `/fenix-new <需求描述>`，也可以只用自然语言描述你想构建的东西，Claude Code 会自动启用这个 skill。命令执行时先与你澄清需求，随后依次生成 proposal（需求背景）、design（详细设计）与 tasks.md（任务清单），创建 `spec/changes/<name>/` 目录并把 SPEC 置为 `drafted`。最终产出一份完整的 SPEC 文档集，以及 STATE.md 中对应的条目。

```
/fenix-new 我要做一个用户认证功能
```

### /fenix-prototype — UI 原型确认环

想在 SPEC 起草前先确认界面意图时使用；/fenix-new 判定需求涉及大范围界面改动时，也会提议进入这个环（是否出原型由你决定）。命令用项目的真实组件库生成「真组件、假数据」的高保真单文件 HTML 原型（组件库不可用时降级为纯 HTML/CSS 仿样，并显式标注「视觉参照、无约束力」），经 fenix dashboard 伺服到浏览器，你点选区块批注意见，agent 在会话内修订迭代，直至你明示认可。批准后原型入库为该 SPEC 的 UI 真相源（`specs/<spec>/prototype/`），对后续实现与评审产生约束力。

```
/fenix-prototype 为即将立项的列表页需求出一张原型
```

### /fenix-setup — 初始化与启动

第一次在项目上启用 Fenix 时使用。命令检查 Python/Git/systemd（以及 claude CLI、PyYAML）依赖是否就绪，创建 `.fenix/` 目录与配置、生成 `.fenix/config.yaml`（幂等运行 fenix-init 生成或补齐完整工程骨架，已初始化的项目也会补缺失项，无需单独执行初始化命令），最后启动 fenixd daemon。跑完之后你就得到了一个可运行的 Fenix 环境。

```
/fenix-setup
```

### /fenix-status — 状态面板

想快速了解项目整体进展时使用。命令读取 STATE.md 与 daemon 状态，输出一句话总结加各 SPEC 状态表，让你一眼看清当前是全部完成、进行中、卡住还是 daemon 已停止。输出内容详细完整，不输出 ASCII 装饰横幅。

```
/fenix-status
```

### /fenix-approve — 审批与推送

SPEC 完成验证进入 `done` 后使用。命令引导你审阅已完成的 SPEC，人工确认后执行 git push 推送远程仓库，状态随之从 `done` 流转到 `pushed`。这是 Fenix 中**唯一的人工门禁点**；是否走人工由 `.fenix/config.yaml` 的 `gates.approve_mode` 控制：`manual` 为人工审批，`auto` 则自动推送跳过确认。

### /fenix-dashboard — Web Dashboard

想用图形界面监控时使用。命令解析框架目录后启动（或复用已有）dashboard 进程，把当前项目注册进去，最后输出一个可直接粘贴到浏览器的访问 URL（`http://localhost:<port>`）。

### /fenix-process — 查看 SPEC 进展

想追踪某个 SPEC 的详细进展时使用。命令读取该 SPEC 的 tasks.md 勾选进度、fenixd 时间线与工作区状态，汇总成一份进展报告。

```
/fenix-process my-feature
```

### /fenix-archive — 归档已完成的 change

SPEC 走完全生命周期后使用。命令把 `spec/changes/<name>/` 目录移动到 `spec/archive/YYYY-MM-DD-<name>/`，归档产物自动 git 提交，并把该 change 的 STATE.md 条目迁出至 `.fenix/STATE.archive.md` 归档清单，完成后输出归档后的目录位置。

## bin/ 辅助脚本

| 脚本 | 用途 |
|------|------|
| `fenix_dashboard.py` | Dashboard 统一入口（--serve Web / --tui 终端 / --add-project 注册） |
| `fenix_spec.py` | 原生 SPEC 生成 CLI（提供 new change/status/instructions 子命令，输出 JSON，供 fenix-new 调用） |
| `fenix_process.py` | 查看指定 SPEC 的详细进展 |
| `fenix_session.py` | 查询项目运行状态与 systemd unit 名（`running`/`path`/`unit`；tmux 会话名体系已退役，`name` 子命令拒绝并指引） |
| `migrate_to_systemd.py` | tmux 承载存量部署 → systemd unit 一次性搬迁编排（缺省 dry-run 预演，`--execute` 真切换为人工步骤） |
| `fenixd_supervisor.py` | daemon 托管入口（框架守护进程由 supervisor 托管，systemd unit 拉起） |
| `fenix_cli.py` | SPEC 运维子命令集：`promote`（晋升草稿）/ `reflow`（verified 回炉复位 ready）/ `activate`（手工激活待激活 SPEC）/ `review`（重新评审），均支持 `--project <path>` |
| `fenix_status.py` | 项目状态一句话总结 + 各 SPEC 状态表（`/fenix-status` 的底层实现） |
| `fenix_verify_contract.py` | 校验 verify.yaml 契约形态（prepare/serve/ready 与场景集 kind 的自动反推匹配） |
| `ocr_review.py` | 收尾代码质量审查入口（`verify.impl_code_review` 开启后由实现者调用的 ocr 封装） |
| `run_full_suite.py` | 全量回归唯一有界入口（主机级锁 + 超时控制；周期回归与手动触发共用，勿裸跑 `pytest tests/`） |
| `fenix_archive.py` | 归档已完成的 change 到 archive 目录 |
| `launch-chrome-extension.js` | 启动 Chrome 扩展（验证用） |
| `test_for.py` | 验证辅助脚本 |
| `fenix_detect_artifacts.py` | 构建产物路径纯本地探测（默认输出候选 JSON，`--write` 幂等写入 `.fenix/config.yaml`；/fenix-setup 探测产物路径一步调用） |
| `dsh_acceptance.py` | dsh 通道一键验收（`fixture` 夹具 / `smoke` 假端点冒烟 / `accept` 真实验收三模式，证据判定 fail-loud） |
| `analyze_run_latency.py` | 历史 run 转录批量延迟分析（API 往返样本直方图，p90 降序，长尾 run 排前） |
| `probe_prompt_cache.py` | 网关前缀缓存能力探针（两轮带 cache_control 请求，判定缓存命中可复用性） |
| `fixture_scheduling_showcase.py` | scheduling-showcase 验证夹具供给（verify.yaml prepare 步骤用，幂等重建/基线写回） |
| `gen-route-map.py` | 路由地图生成器参考实现（本仓 dashboard 的 API/SPA 路由地图，generator 协议示例） |

### 托管态（managed / unmanaged / stopped）

daemon 的唯一合法启动路径是经 `fenixd_supervisor.py` 托管（`/fenix-setup` 第 7 步与
Dashboard 项目页「启动」均以此方式拉起）。承载手段为 systemd unit
`fenixd-<项目名>-<哈希>.service`（`systemctl enable --now`，`Restart=on-failure`
崩溃自动拉回、开机自启），daemon 是 supervisor 的子进程，systemd 监督对象是
supervisor 不是 daemon；supervisor 检测 `.fenix/restart_request` 后 SIGTERM daemon 并
自动拉起，承担唯一的重启职责。停止语义为「写 `.fenix/stop` + SIGTERM daemon → supervisor
收口退出」，不再直接杀 daemon；unit 已安装时走 `systemctl stop --no-block` +
≤30s 轮询 + 快照补杀收口。看现场：`journalctl -u <unit>`（supervisor 日志另见
`.fenix/logs/supervisor.log`）。

daemon 运行状态分三态：

| 托管态 | 判定 | 含义 |
|--------|------|------|
| `managed` | supervisor 与 daemon 均在运行 | daemon 受 supervisor 托管，restart_request / 审批推送等文件信号有消费方 |
| `unmanaged` | 有 daemon 进程但无 supervisor | 裸 daemon（存量项目未经托管），文件信号无人消费——需经 Dashboard 项目页「安装托管」或 `/fenix-setup` 恢复托管 |
| `stopped` | 两者皆无 | daemon 未运行 |

## full 模式 vs fast-track 模式选择

SPEC 立项时（/fenix-new）按四维标准评估复杂度，Agent 给出明确的模式建议、由你确认后写入 SPEC 的 `.spec.yaml` `mode` 行；daemon 按声明的模式分派车道，未写 `mode` 行的存量 SPEC 一律按 `full` 处理：

| 维度 | full 模式 | fast-track 模式 |
|------|-----------|-----------------|
| **影响面** | 跨模块、影响既有流程 | 单点小改动、不触及核心链路 |
| **模块数** | 2+ 模块 / 跨服务 | 1 个模块内 |
| **UI / 迁移** | 含 UI 交互、数据库/配置迁移 | 无 UI、无数据迁移 |
| **预期场景数** | 多（涉及状态机/并发/回归） | 少（≤3 个验证场景） |

评估为简单即建议 fast-track——单个 Agent 一次完成实现与验证，更快更省；评估为复杂则建议 full——多个 Agent 分段实现与独立验证。

## 相关文档

- [快速上手](01-quick-start.md) — 端到端流程实操
- [核心概念与架构](02-concepts.md) — Agent 角色与模式原理
- [关键配置](09-config.md) — gates.approve_mode 等开关
