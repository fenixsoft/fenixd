# 手工触发修复

<!-- knowledge: capability=code-fix-manual-trigger rev=1
     sources=spec/archive/2026-09-27-add-code-fix-manual-trigger -->

质量页签「立即自动修复」：信号文件触发 + 整链授权 + 判定结果回链。

## 规则

### 触发信号
- `POST /api/code-review/fix-run?project=<name>`（形态对齐既有 `POST /api/code-review/run`）：向目标项目原子写入 `.fenix/code_fix_request.json` 触发信号（`O_CREAT|O_EXCL` 独占创建，payload 含 `source: "dashboard"` 与 `created` UTC 时间戳），由 daemon 主循环消费；项目不存在 → 404。
- 信号文件已存在（并发第二次 POST，或上一信号尚未被消费）→ 409 明确文案，不覆盖已有信号。
- 目标项目 daemon 未运行（stopped）或未受 supervisor 托管（unmanaged）→ 分别 400 / 409 前置拦截，不写信号。

### 整链授权
- daemon 消费信号时以授权形态调用 `CodeFixOrchestrator.checkpoint()`：绕过「自动修复代码问题」总开关（`enabled`）投递一批，且授权覆盖整条自驱动链——授权旗标 `manual_authorized` 持久化在 fix-progress.json 随链身份传播，批收尾后无旁路参数的 checkpoint 凭「链 live（running=true）且旗标为真」越过 enabled 守卫继续投递，直至 open 条目清零或链终止。
- 授权旗标在链终态（idle / blocked / failed）清除；收尾链的授权不外溢到新链。
- checkpoint 其余守卫全部保留：单飞（already_running）、无 open 条目（no_open_items）、失败保留集合、回归契约 fail-closed（不因手动触发放宽）。
- live 链撞 enabled 守卫（开关被中途关闭且无授权旗标）时落终态进度（`running=false` / `phase=blocked` / `reason=disabled`），不得静默保持 `running=true`。

### 判定结果反馈
- daemon 消费后把判定结果原子写入 `.fenix/code_fix_request_result.json`：`{request_created, triggered, reason, message, finished_at}`；`request_created` 回链信号文件的 `created` 时间戳，`message` 为面向用户的人类可读中文文案。
- 判定为被拒时（含 orchestrator 未装配、checkpoint 内部异常）同样落结果文件并给出明确 reason，不静默丢弃信号。
- 只读端点 `GET /api/code-review/fix-run-result?project=<name>` 返回该文件内容，缺失返回缺省态，不得 500。
- 前端仅当结果 `request_created` 与本次触发返回的 `requested_at` 一致时才视为本次结果，陈旧残留结果不得当作本次反馈。

### 前端按钮
- 质量页签（QualityTab）动作按钮组「立即自动修复」：点击调用 fix-run，受理后轮询 fix-run-result（带超时上限），按结果以 message 成功/警告回显；按钮有 pending 门控防连点，触发流程中呈 loading 态。
- 轮询超时兜底：超时上限内未读到匹配结果时给出「请稍后在进度卡片或 daemon 日志确认」类提示，按钮退出 loading。
- 触发成功后由既有自动修复进度卡片（2s 轮询）接管进度展示，无需额外操作。

## 溯源

- 2026-09-27 2026-09-27-add-code-fix-manual-trigger — 新建本页：fix-run 信号端点与消费方前置守卫、授权粒度为整链（旗标随链传播、终态清除）、结果文件回链与时间戳匹配、前端按钮与超时兜底。
