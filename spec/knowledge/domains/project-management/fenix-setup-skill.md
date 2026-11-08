# 框架初始化与启动入口

<!-- knowledge: capability=fenix-setup-skill rev=3
     sources=spec/changes/add-systemd-hosting,spec/changes/add-onboarding-init-setup-guidance -->

`/fenix-setup` 是初始化或重启 Fenix 框架的用户入口，覆盖新项目首次接入与既有项目重启。

## 规则

- 流程：检查依赖 → 幂等创建项目骨架（每次都执行 `fenix-init`，白名单 staged 自举与 gitignore 补齐随初始化口径生效）→ 兜底目录结构 → 模型配置检查 → 启动 fenixd daemon。
- 依赖检查覆盖 Python、git、systemd（systemctl 可用性，daemon/dashboard 承载必需）与 Claude Code CLI，缺项先报告再继续。
- 目录骨架创建委托 `fenix-init`（`.fenix/`、`spec/` 骨架、软链接与 `.gitignore` 规则同初始化播种口径）；config 由 fenix-init 渲染，skill 侧只做存在则合并、不存在则跳过。
- 模型配置检查：初始化完成后读取 `.fenix/config.yaml`，探测 `llm.providers` 与 `agents.models` 配置形态，按结果分支指引——未配置：说明所选 harness 的无分配默认档（claude=继承 Claude CLI 会话默认模型；dsh=对称回落 dsh profile 默认档，回落落地前为条件式表述），建议经 Dashboard 设置页或参照 `.fenix/config.template.yaml` 注释示例手工编辑显式分配（provider 与 model 两键必填，该文件已 gitignore、API Key 不入库）；已配置：核对一致性——`agents.models` 各角色引用的 provider 名必须在 `llm.providers` 的 name 列表内（引用未注册 provider 的分配要到派发期才暴露失败），model 名须与网关侧实际可用模型一致（被拒属确定性失败，全链被拒带 [model-chain-unavailable] 标记不自动重派），链形态支持单值/字符串数组/对象数组三种，修改后约 30s 配置热更新生效。
- daemon 启动前先探测既有实例，避免双实例；启动经 systemd unit 承载（`fenixd-<项目名>.service` 生成安装并 `enable --now`），重启场景沿用 daemon 单例保证；启动失败看现场用 `journalctl -u <unit>` 加 `.fenix/logs/` 既有日志文件。
- 含「人工切换步骤」小节：tmux 承载存量部署一次性迁移 systemd（env 候选稿人工审核 → `bin/migrate_to_systemd.py` 先 dry-run 后真切换 → 验收 → 回滚配方），实际切换由人工执行。
- 首跑常见告警解读（三类高频告警的来源与处置，供新手首跑对照）：①白名单文件脱落（whitelist_untracked，major）——新初始化项目已由 init 自举 staged 不会再报，自举上线前初始化的存量/升级项目仍会命中，人工 `git add` 处置；②散件首现（untracked 首现提示，info）——`.claude/agents/` 等框架播种产物已预防性 ignore，新模板项目不再产生；③契约模板态（verify_contract 未裁决提示，info）——实现期属预期，进入验证期前完成裁决即可。
- 幂等：对已完成初始化的项目重复执行不破坏既有状态。

## 代码锚点

- 主实现：`skills/fenix-setup/SKILL.md`（步骤 6b 模型配置检查、「首跑常见告警解读」节）
- 消费方：`fenix-init`（骨架与自举委托目标）

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
- 2026-11-04 add-systemd-hosting（spec/changes/add-systemd-hosting） — 配方 systemctl 化：依赖检查 tmux → systemd（systemctl）、daemon 启动改 unit 承载、看现场 journalctl + 既有日志文件；新增「人工切换步骤」小节（存量 tmux 部署迁移与回滚配方）
- 2026-11-08 add-onboarding-init-setup-guidance（spec/changes/add-onboarding-init-setup-guidance） — 新增模型配置检查步骤（读 config.yaml 分支指引：未配置给显式分配路径、已配置给 provider 注册一致性与模型可用性核对要点）与「首跑常见告警解读」小节（白名单脱落/散件首现/契约模板态三类，来源 + 处置）
