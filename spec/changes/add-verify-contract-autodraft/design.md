# 设计：验证契约自主起草（verify-contract-autodraft）

## Context

`.fenix/verify.yaml` 三段式契约（prepare/serve/ready）自 add-verify-contract 机制落地以来只能由人类编写；`core/pm_engine/verification.py` 的 `_ensure_app_reachable` 在契约缺失且 `commands.start` 无效时返回「无 serve 配置……退回 plan 修复」note，走打回 plan 路径——plan 修不了基建，确定性死局只能烧轮次等 admin 升级。2026-09-07 notes-standalone-sync 事故实证：Administrator 有能力起草高质量契约（fenix-desktop 样本），缺的是制度化触发通道与自证门。

既有可复用资产：`verify_contract.py` 的 `run_prepare_steps` / `probe_ready`（含鉴别力自检）/ `StaticVerifyServer` / `CommandVerifyServer`；admin_monitor 的信号记录通道（未 escalated 记录 → 转信号、标记、直接唤起 Administrator）与 D2 同 spec 节流；Administrator 既有的「重置 spec 状态」「git 清理/提交」权限。

## Goals / Non-Goals

**Goals**
- 验证撞上契约缺失/损坏时框架自主恢复：路由信号化 → admin 起草 → 三段自证 → 提交 → spec 复位重验证。
- 自证门防「写个文件就算完」；起草失败带草稿升级，人类只做判断。

**Non-Goals**
- 不做巡检主动预生成、不做跨项目模板库（契约项目特定）。
- 不加配置开关与 Dashboard UI（行为只在本来必然卡死的路径生效）。
- 不改纯 cli 场景集路径与 prepare 失败（构建坏）的既有打回语义。
- 自证证「契约声明自洽」（三段可执行），不证「场景能过」——产品质量仍由验证链裁决。

## Decisions

**D1 路由信号化 = 复用 admin 信号通道，新增信号类型。**
`_ensure_app_reachable` 的三分支（契约不存在 / commands.start 占位符 / 契约解析失败）改为：返回签名不变（`(reachable, user_blocked, note)`），检测点直接写一条 `verify_contract_missing` 信号记录（SIGNAL 形态，携带 spec、项目根、场景 kind 集、`parse_error` 标注），note 改为「已派发 Administrator 起草验证契约」类文案（不再含「退回 plan 修复」）。admin_monitor 既有「未 escalated 记录 → 唤起」机制照常消费，D2 节流约束同 spec 重复信号。
备选被否：note 哨兵前缀由上层翻译（字符串协议脆弱）；扩展返回元组（改全部调用点，回归面大）。立即派发不等 4 次失败计数：基建缺口重试零收益，信号记录本身就是一次性行为，节流已防风暴。

**D2 自证入口 = `core/verify_contract.py` 新增 `validate_contract(project_root) -> ValidateResult` + `bin/fenix_verify_contract.py` 薄 CLI。**
validate 复用 run_prepare_steps / probe_ready / 两类 Server：逐段执行 prepare → 启 serve → 探 ready（含鉴别力自检）→ 停 serve，返回各段通过与否与错误详情；退出码全通 0。Administrator 在草稿上运行 CLI，全通才把文件落位 `.fenix/verify.yaml`（草稿先写临时路径，防半成品被 `load_verify_contract` 当有效契约）。
备选被否：让 admin 手拼 python -c 调内部函数（易错、无稳定契约）。

**D3 起草手册落点 = `agents/administrator.md` 权限清单加一条 + 起草流程节；信号 detail 注入上下文。**
权限条目措辞即边界：生成/修正 `.fenix/verify.yaml`（缺失即生成、明显失效可修且留痕、有效契约一律不碰）。手册内容：输入源（config `project.type`/`description`、package.json scripts、dist/build 目录探测、`core/verify_contract.py` docstring 模板）、流程（草稿临时路径 → CLI 自证 → 落位 → git 提交 → spec 复位 ready → 2 轮上限 → escalate 附草稿）。信号 detail 由 prompt_builder 的 administrator 动态段注入（既有困境信号通道）。
注意：agents/*.md 为项目源副本，改后无需同步动作（fenixd 即主树）。

**D4 「有效契约」判定 = 可解析 + serve 段合法。**
validate 函数输出 `valid: bool`（YAML 可解析、serve.kind ∈ static/command 且对应必填字段非空）。Administrator 任务入口先跑 valid 判定：valid → 「契约有效、无需起草」结案（对齐权限边界）；invalid → 修正路径。serve 缺省但纯 cli 场景集合法的场景由验证引擎的 kind 反推处理，不在本机制范围。

**D5 收尾复用既有权限。**
契约 git 提交（随仓库提交是契约的既有语义；fenix-desktop 存量未提交样本在 SPEC 验收阶段补提交）；spec 复位 ready 用 Administrator 既有「重置/修复 spec 状态」权限；处置记录走既有 disposition 模板，修正动作记 `actions_taken`（含 diff 摘要）。

## Risks / Trade-offs

- [admin 起草质量不稳、烧 token] → 自证门硬性拦截 + 2 轮上限 + escalate 附草稿；起草是项目级一次性投资。
- [起草成 static 但项目需要后端（api 场景）] → 手册明确：场景集含 api 场景时 serve MUST 用 command 形态（full-stack 先例：CommandVerifyServer）；自证通不过自然拦住。
- [多 spec 同时撞缺失 → 信号风暴] → 同 spec 节流（既有 D2）+ 同项目契约只起草一次（首个信号处理后其余 spec 重验证时直接受益）。
- [validate 在主树执行 prepare 动主树产物] → 契约 prepare 的既有语义即「验证前主树构建」，无新增风险；worktree 作用域（`verify.static_scope=worktree`）是运行时配置，validate 只证声明自洽，主树跑通即声明成立。
- [信号写入点在验证热路径上] → 写入是既有信号通道的普通记录操作（json 追加），无锁竞争面（既有 admin_alerts 写入同模式）。

## Migration Plan

无存量迁移：行为只替换「必然卡死」路径，存量项目零感知。回滚 = revert 对应提交，回到打回 plan 旧行为。fenix-desktop 未提交契约在验收阶段补提交。

## Open Questions

无——触发时机（被动）、权限边界（缺失生成/失效可修/有效不碰）、执行模式（full）均已在需求澄清阶段与用户确认。
