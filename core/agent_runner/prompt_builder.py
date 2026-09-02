"""prompt_builder.py — PromptBuilder：Agent 提示词构建（refactor-core-packages 阶段 1）。

准纯函数组件：_build_prompt + 各 section（legacy/冻结/交互契约/复核/裁决驳回）。
文件读取时机等价（design D3 规则 5）：不缓存、不提前读取——每次调用按原路径
读取 .fenix/ 现场文件。跨域依赖（state_machine/project_root/验证进度读取等）
经门面回引 self._pm，不在本组件持有状态。
"""

import json


class PromptBuilder:
    """Agent 提示词构建器（门面 AgentRunner 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

    def _build_prompt(self, spec_name: str, agent_type: str, detail: dict | None = None) -> str:
        """Build the claude CLI prompt for the Agent.

        detail: 可选。administrator 分支接收困境信号 dict。
        """
        spec_dir = f"openspec/changes/{spec_name}"

        if agent_type == "implementer":
            prompt = (
                f"You are the Fenix Implementer Agent. Your job is to implement the SPEC "
                f"located at {spec_dir}/.\n\n"
                f"1. Read {spec_dir}/proposal.md, {spec_dir}/design.md, and {spec_dir}/specs/\\*.md "
                f"to understand what needs to be built.\n"
                f"2. Read {spec_dir}/tasks.md and identify the next unchecked task.\n"
                f"3. Implement that task. Write actual production code, not stubs.\n"
                f"4. Run the project's tests after implementation. Fix any failures.\n"
                f"5. Commit your changes with message: [fenix] {spec_name}: <task description>\n"
                f"6. Mark the task as complete in tasks.md (- [x])\n"
                f"7. If all tasks are done, write a file .fenix-run-result.json with: "
                f'{{"status": "success", "spec": "{spec_name}", "summary": "<brief summary>"}}\n'
                f"8. If you encounter an error you cannot fix after 3 attempts, write "
                f".fenix-run-result.json with: "
                f'{{"status": "error", "spec": "{spec_name}", "error": "<description>"}}\n\n'
                f"## 交互契约（interaction-contract，强制，add-interaction-contract-and-per-assert-triage）\n"
                f"- 凡你实现为**可交互形态**的元素（按钮/链接样式卡片/可点击行/表单控件），"
                f"其行为 MUST 在对应 SPEC 中有定义，或在任务书中显式声明「纯展示、不可交互」。\n"
                f"- 两者皆不满足时，MUST 在 .fenix-run-result.json 增设 `findings` 数组登记"
                f"「待裁决交互」条目（元素、现状、建议行为），不得静默保留可交互外观：\n"
                f'  "findings": [{{"type": "pending-interaction", "element": "<元素标识>", '
                f'"current": "<现状>", "suggestion": "<建议行为>"}}]\n'
                f"- 已声明纯展示的元素即合规，收工守卫不因此拦截。\n\n"
                f"IMPORTANT: Do NOT modify STATE.md directly. The daemon handles that."
            )
            # 上轮 error 上下文注入（add-implementer-deliverable-gate D4）：
            # 重派 run 携带上次缺件清单，agent 无需重新考古即知补什么。
            prev_error = ""
            try:
                entry = self._pm.state_machine.read_one(spec_name) or {}
                prev_error = (entry.get("error") or "") if isinstance(entry, dict) else ""
            except Exception:
                prev_error = ""
            if prev_error:
                prompt += (
                    f"\n\n## Previous run error (context for this attempt)\n"
                    f"The previous implementation attempt failed and was re-dispatched. "
                    f"Use this to focus your work — do NOT repeat the same gap:\n"
                    f"\n{prev_error}\n"
                )
            # 恢复重派遗产上下文注入（add-recovery-legacy-check 2.1/2.2）：
            # 仅当该 spec 有在册遗产时追加，无遗产则不注入（prompt 与现状逐字节一致）。
            legacy_section = self._build_legacy_section(spec_name)
            if legacy_section:
                prompt += legacy_section
            return prompt
        elif agent_type == "verifier":
            progress_path = self._pm.project_root / ".fenix" / "verify-progress" / f"{spec_name}.json"
            # 结构化报告（与 verify_engine 产物同位置，Dashboard 场景/缺陷列表数据源）
            report_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / "report.json"
            )
            # 断点续跑（verifier-checkpoint-resume spec）：读取上次 attempt 的进度文件，
            # 存在且 done>0 时把断点信息注入提示词，让新 agent 从 done+1 场景继续，
            # 不再从头重跑。文件缺失 / done==0 / JSON 损坏 → 不注入、全新开始，损坏文件
            # 移除以免污染后续 attempt。
            breakpoint_section = ""
            progress = self._pm._read_verify_progress(spec_name)
            if progress is not None:
                total = progress.get("total")
                done = progress.get("done") or 0
                current = progress.get("current") or ""
                if isinstance(done, int) and done > 0:
                    initial_done = done
                    start_scenario = done + 1
                    breakpoint_section = (
                        f"\n⚠️ RESUME CHECKPOINT (断点续跑) — 你是从上次中断处续跑的验证 Agent。\n"
                        f"上次验证进度：total={total}, done={done}, 上次进行中的场景: '{current}'\n"
                        f"指令：\n"
                        f"  1. 跳过已完成的 {done} 个场景，从第 {start_scenario} 个场景开始执行\n"
                        f"     （场景总数保持 {total} 不变，不要重新数；已完成的场景视为已通过）。\n"
                        f"  2. 首次写入进度时直接写 done={initial_done}（不要重置为 0），"
                        f"之后每完成一个场景将 done 递增 1 并更新 current。\n"
                        f"  3. 直至 done 达到 {total}，写入 done={total} 与最终结果。\n"
                        f"  4. 不要重复执行已完成场景的截图/报告，但需确保本次从断点起的场景全部真实在\n"
                        f"     浏览器中跑通（DOM snapshot 文本验证）。\n\n"
                    )
            return (
                f"You are the Fenix Verifier Agent. Independently verify the SPEC at {spec_dir}/.\n\n"
                f"CRITICAL: You MUST test in a REAL browser/user environment.\n"
                f"Code analysis alone = INCOMPLETE = FAILURE. Use playwright-cli for web projects.\n\n"
                f"WORKFLOW — write progress to {progress_path} at EVERY step:\n"
                f"  Step 0: Write done=0, current='初始化: 读取SPEC'\n"
                f"  Step 1: Read specs, count scenarios. Write total=N.\n"
                f"  Step 2: Build and START the project in its real runtime.\n"
                f"    Web: npm run dev, open in browser via playwright-cli.\n"
                f"    Extension: npm run build, load in Chrome (if possible) or npm run dev.\n"
                f"  Step 3: MANDATORY click-through UI regression test — test EVERY panel:\n"
                f"    - Quick Links: CLICK '+', fill form, SUBMIT → verify new link appears in grid\n"
                f"    - Notes: CLICK '+', type note, SAVE → verify note appears in list\n"
                f"    - Stock: TYPE 'sh600036', CLICK 'add' → verify stock appears in list\n"
                f"    - Calculator: TYPE '2+3', ENTER → verify '5' result is visible and readable\n"
                f"    - Email: CLICK settings, add account → verify form works\n"
                f"    After EACH interaction, TAKE SCREENSHOT as evidence.\n"
                f"    If any button click produces NO visible result = BLOCKING BUG.\n"
                f"  Step 4: Test scenarios ONE BY ONE as a REAL USER.\n"
                f"    USE PLAYWRIGHT-CLI: navigate, click, type, scroll, take screenshots.\n"
                f"    After EACH scenario, increment done and write progress.\n"
                f"    Format: {{\"total\": N, \"done\": D, \"current\": \"scenario description\"}}\n"
                f"  Step 4: Test edge cases (empty input, long input, resize, rapid clicks).\n"
                f"  Step 5: Write {spec_dir}/verification-report.md with screenshots.\n"
                f"    Also write {report_path} — structured report.json（Dashboard 的\n"
                f"    场景/缺陷列表数据源，全部场景执行完毕后一次写入，MUST exist before\n"
                f"    you finish）:\n"
                f"    {{\n"
                f'      "spec": "{spec_name}",\n'
                f'      "timestamp": "<ISO8601 当前时间>",\n'
                f'      "summary": {{"total": N, "passed": P, "warnings": W, "failed": F, "errors": E}},\n'
                f'      "scenarios": [\n'
                f'        {{"scenario_id": "s1", "description": "场景描述",\n'
                f'          "status": "pass | fail | error | warning",\n'
                f'          "assertion_results": [{{"type": "step", "pass": true, "message": ""}}],\n'
                f'          "screenshots": ["/绝对路径/证据截图.png"]}}\n'
                f"      ]\n"
                f"    }}\n"
                f"    status 判定: pass=全部断言与步骤通过; fail=断言/步骤失败(产品缺陷);\n"
                f"    error=不可测或环境故障(非产品缺陷); warning=仅视觉或第4层断言差异。\n"
                f"    每个真实执行的场景都必须出现在 scenarios；summary 计数与 scenarios 一致；\n"
                f"    fail/error 场景在 assertion_results 中给出未通过断言（含凭证 message）。\n"
                f"  Step 6: All pass → write .fenix-run-result.json: "
                f'{{"status":"verified","spec":"{spec_name}","bugs":[]}}\n'
                f"  Step 7: Bugs found → write .fenix-run-result.json: "
                f'{{"status":"bug-found","spec":"{spec_name}","bugs":[...]}}\n\n'
                f"  Step 8: CLEANUP — 验证结果已写出后，主动清理本次验证创建的临时资源，"
                f"不要留给用户打扫:\n"
                f"    - 删除自己为本次验证复制/创建的 mock、临时或测试项目目录"
                f"（如 /tmp/fenix-verify-*、/tmp/verify-* 等本次新建的目录）\n"
                f"    - 终止自己为本次验证启动的 mock/辅助服务器进程\n"
                f"    - 删除自己创建的临时脚本与临时产物文件\n"
                f"    - 保留：verification-report.md、{report_path}、.fenix-run-result.json、"
                f"{progress_path}，以及 verify worktree 自身\n"
                f"    - 禁止删除被测项目内的任何文件（含 worktree 内的报告与结果文件）\n"
                f"    - 清理失败或文件被占用时跳过即可，不得阻塞结果上报、不得误删项目文件\n\n"
                f"MANDATORY: Write progress after EVERY step and EVERY scenario.\n"
                f"MANDATORY: Use playwright-cli for browser testing. NO shortcuts.\n"
                f"MANDATORY: If you cannot start the REAL project, report it as a failure.\n"
                f"IMPORTANT: Do NOT Read image/screenshot files (.png/.jpg) — 当前模型不支持图像输入，"
                f"读图会被 hook 拦截；截图仅作为证据文件保存到报告，验证用 DOM snapshot 文本。\n"
                f"IMPORTANT: Do NOT modify STATE.md."
                f"{breakpoint_section}"
            )

        elif agent_type == "planner-plan":
            scenarios_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / "test_scenarios.json"
            )
            result_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / ".fenix-run-result.json"
            )
            # fix-replan-feedback-injection：验收退回时把上一轮错误清单直接内联进
            # prompt——此前只写 REPLAN_FEEDBACK.md 靠 agent 自觉去读，实测 planner
            # 会无视（退回重跑的错误与上轮一字不差，纯烧 0.27h/$）。内联后想不看都难。
            replan_section = ""
            replan_fb_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / "REPLAN_FEEDBACK.md"
            )
            if replan_fb_path.exists():
                try:
                    fb_text = replan_fb_path.read_text(encoding="utf-8")[:3000]
                    replan_section = (
                        f"\n## ⚠️ 上一轮场景验收未通过（MANDATORY：逐条修复后再输出）\n\n"
                        f"{fb_text}\n\n"
                        f"上述错误清单来自验收器，必须在本轮输出中全部修正；"
                        f"若沿用上一轮场景文件原样重写，验收将再次拒绝并消耗重排预算。\n"
                    )
                except OSError:
                    pass
            return (
                f"你是 Fenix Planner Agent。你的任务是将 SPEC 文档转化为结构化的浏览器测试场景。\n\n"
                f"{replan_section}"
                f"## 步骤\n"
                f"1. 读取 {spec_dir}/proposal.md, {spec_dir}/design.md, {spec_dir}/specs/*.md\n"
                f"2. 分析所有功能点，为每个功能生成至少一个测试场景\n"
                f"3. 将生成的场景保存到 {scenarios_path}\n"
                f"4. 将运行结果写入 {result_path}（绝对路径，与场景文件同目录，"
                f"不要写别处）："
                f'{{"status":"plan-ready","spec":"{spec_name}"}}\n\n'
                f"## 场景覆盖规则\n"
                f"- 功能正向路径：每个SPEC功能点的完整操作流程\n"
                f"- 异常路径：空输入、超长输入、特殊字符\n"
                f"- 交互流程：多步骤操作序列，验证中间状态\n"
                f"- 回归点：操作后状态与操作前对比\n"
                f"- 空状态：列表/面板在无数据时的显示\n"
                f"- 删除/撤销：删除操作后的状态验证\n\n"
                f"## 真实云端端到端场景（同步/云端/数据隔离相关 SPEC 必须）\n"
                f"- 对「同步 / 云端存储 / 上传下载 / 数据加密 / 数据隔离」相关 SPEC，"
                f"必须生成至少一个「真实创建用户 → 解锁 → 点击下载」的端到端场景，"
                f"触发真实云端请求（腾讯云 COS）。\n"
                f"- 这类场景用 no_auth_error 断言「无签名/认证错误」，用于捕获"
                f"数据加解密/签名正确性 bug（纯 UI 断言无法覆盖）。\n"
                f"- 约束：只做「下载」（读取云端，安全），不做「上传」（避免污染真实云端数据）。\n"
                f"- 示例步骤：seed 清空用户与同步键 → 创建用户（密码 test-password-123）→ "
                f"解锁 → 点击「下载云端数据」→ 断言 no_auth_error。\n\n"
                f"## 选择器规范\n"
                f"- 优先使用 data-testid 属性\n"
                f"- 其次使用语义选择器：button[name=\"提交\"], input[placeholder=\"搜索\"]\n"
                f"- 避免使用：第n个子元素、绝对路径\n"
                f"- 若被测页面使用 AMIS 组件库（如 fenixd Dashboard，dark 主题）：\n"
                f"  AMIS 实际渲染类名带主题前缀 dark-，**不存在** .amis-Form-* 这类类名，"
                f"臆测组件库类名会导致选择器全部超时。已实测验证的选择器：\n"
                f"  - Select 下拉控件：.dark-SelectControl（页面内有多个时用 >> nth=N，"
                f"顺序与 filter 配置的 body 数组一致）\n"
                f"  - Select 下拉选项：.dark-Select-option:has-text('<选项文本>')\n"
                f"  - dropdown-button 的二级菜单项渲染在 portal 弹层 "
                f".dark-PopOver.dark-DropDown-popover 中，**不在** .dark-DropDown.is-opened "
                f"容器内——定位菜单项用 .dark-DropDown-popover >> text=<菜单项文本>，"
                f"不要嵌套在 .dark-DropDown.is-opened 内查找（元素不存在必超时）\n"
                f"  - crud 表格行：**不存在** .amis-Sheet-row / .amis-Table-row，行是普通 "
                f"<tr>（主题类 dark-Table-table-tr）——定位行用 tbody tr（或 "
                f"tbody tr >> nth=N），行内按钮用 tbody tr >> nth=0 >> button:has-text('<文本>')\n"
                f"  - Dialog：根节点 .amis-dialog-widget 存在；关闭按钮是 "
                f".amis-dialog-widget [class*='Modal-close']（**不存在** .amis-Dialog-close）；"
                f"标签页项是 .amis-dialog-widget [class*='Tabs-link']:has-text('<页签名>')"
                f"（**不存在** .ant-tabs-tab）\n"
                f"  - Select 选项点击后下拉立即关闭并可能触发 URL 参数同步（页面跳转），"
                f"选择后的断言应指向列表行/结果区，**不得**再断言选项本身可见\n"
                f"- 自建壳应用的侧边栏导航 href 来自壳的路由表（如 app.json 的通用 url："
                f"#/config、#/activities），**不含**项目名等路径参数——不得臆测 "
                f"#/config/<project> 形式的链接\n"
                f"- 组件库类名属于 CSS 类选择器豁免：使用前必须先查阅被测页面源码确认真实"
                f"渲染结构，不得臆测\n\n"
                f"## navigate URL 规范（验收硬约束，违反即退回 plan）\n"
                f"- fenixd 是通用软件开发框架，被测应用可能是任何软件：navigate 路径"
                f"**必须来自被测应用的真实源码**，不得臆测。生成场景前先阅读被测应用的"
                f"路由/入口定义代码（服务端路由表、页面注册、框架路由配置等——不同"
                f"框架形式不同），确认每个目标路径真实存在，并在场景 description 末尾"
                f"标注出处（文件:行号）供审计。\n"
                f"- navigate 步骤的 value 必须是**绝对 URL**：http:// 或 https:// 开头，"
                f"含主机与端口（主机与端口以验证运行实例实际启动的为准，路径来自源码证据）。\n"
                f"- 相对路径（如 \"/dashboard\"）或源码中查无出处的路径会被拒收。\n"
                f"- 若 {scenarios_path} 同目录存在 REPLAN_FEEDBACK.md，必须先读取："
                f"那是上一轮场景未通过验收的反馈，逐条修正后重新输出全部场景。\n\n"
                f"## 断言规范（每个场景至少包含）\n"
                f"- 1个 element_visible（操作结果可见）\n"
                f"- 如涉及点击：1个 no_click_interception（点击不被拦截）\n"
                f"- 如涉及输入：1个 text_match（输入内容正确）\n"
                f"- 如涉及表单：1个 element_enabled（提交按钮状态正确）\n\n"
                f"## 对话框处理（window.confirm/alert/prompt）\n"
                f"- 点击若触发 window.confirm 等浏览器对话框，必须显式处理，否则被默认 dismiss 会误判：\n"
                f"  - 确认场景：在触发对话框的 click 步骤加 \"dialog\": \"accept\"，"
                f"或在 click 前加一步 {{\"action\": \"dialog\", \"value\": \"accept\"}}\n"
                f"  - 取消场景：同理用 \"dismiss\"\n"
                f"- 示例：{{\"action\": \"click\", \"target\": \".user-chip\", "
                f"\"dialog\": \"accept\", \"description\": \"点击切换并确认\"}}\n\n"
                f"## no_click_interception 时机规范\n"
                f"- 只在「即将点击某元素」前断言该元素不被遮挡；一旦打开 modal/overlay，"
                f"其覆盖的底层按钮被遮挡是正常交互，不得再对其断言 no_click_interception。\n\n"
                f"## 弹窗/对话框关闭后的断言规范（时序）\n"
                f"- 若某操作（如点击「保存」「取消」）会关闭弹窗/对话框，则关闭之后"
                f"弹窗内元素已从 DOM 移除，**不得再断言弹窗内元素**（如输入框的值）。\n"
                f"- 应改为断言弹窗外持久 DOM 的交互结果（如面板主体区的文本/元素），"
                f"或在触发关闭的操作**之前**断言弹窗内输入框的值。\n"
                f"- 示例：输入地点 → 点「保存」（弹窗关闭）→ 断言面板天气区文本，"
                f"而非断言弹窗内输入框。\n\n"
                f"## seed 数据规范\n"
                f"- seed 写入的 localStorage 值必须是目标键的合法格式：base64 键"
                f"（如 fenix:sync:persisted-key）必须使用合法 base64，不得使用 "
                f"\"some-base64-key\" 这类占位符。\n\n"
                f"## 输出JSON格式\n"
                f'[\n'
                f'  {{\n'
                f'    "id": "kebab-case-unique-id",\n'
                f'    "description": "中文场景描述",\n'
                f'    "depends_on": ["前置场景ID"],\n'
                f'    "steps": [\n'
                f'      {{"action": "navigate", "value": "https://..."}},\n'
                f'      {{"action": "click", "target": "[data-testid=\'add-btn\']", "description": "点击添加按钮"}},\n'
                f'      {{"action": "type", "target": "[data-testid=\'title-input\']", "value": "测试标题"}},\n'
                f'      {{"action": "click", "target": "[data-testid=\'submit-btn\']", "description": "提交表单"}}\n'
                f'    ],\n'
                f'    "assertions": [\n'
                f'      {{"type": "element_visible", "selector": ".result-item", "label": "新增项可见"}},\n'
                f'      {{"type": "text_match", "selector": ".result-item .title", "expected": "测试标题"}},\n'
                f'      {{"type": "no_click_interception", "selector": "[data-testid=\'add-btn\']"}},\n'
                f'      {{"type": "no_console_error"}}\n'
                f'    ],\n'
                f'    "visual_baseline": "scenario_id_baseline"\n'
                f'  }}\n'
                f']\n\n'
                f"支持的断言类型: element_visible, element_count, element_not_exist, "
                f"element_focused, element_enabled, no_click_interception, no_overlap, "
                f"in_viewport, z_index_order, text_match, text_contains, attribute_match, "
                f"no_console_error, no_network_error, no_auth_error, dom_structure, no_overflow, alignment\n\n"
                f"支持的操作类型: navigate, click, type, clear, select, scroll, wait, dialog, seed, mock_api\n"
                f"（click 步骤可携带 \"dialog\": \"accept\" | \"dismiss\" 处理浏览器对话框）\n"
                f"## 外部 API 场景规范（真实网络请求 / mock）\n"
                f"- 涉及外部 API 真实请求的场景（如 open-meteo 天气、时间服务器），在场景 JSON "
                f"顶层声明 \"external_net_errors_ok\": true，表示允许 no_console_error 过滤 "
                f"net::ERR_ 等网络层错误（测试环境不可达属环境因素，非产品缺陷）；"
                f"签名/认证类错误仍严格失败。\n"
                f"- 若需离线完整验证外部 API 请求→解析→渲染链路，可在场景 steps 中加入 "
                f"mock_api 步骤：{{\"action\": \"mock_api\", \"target\": \"https://api.open-meteo.com/**\", "
                f"\"value\": \"{{\\\"current\\\": ...}}\"}}（target 为 URL 模式，value 为 JSON 响应体；"
                f"注意 Playwright glob 中 `*` 不匹配 `/`，多段路径需用 `**`，引擎会自动把结尾 "
                f"`/*` 补成 `/**`）。mock 注册在 page 上，reload/导航后仍保留；仅作用于当前场景。\n\n"
                f"{self._scenario_freeze_section(spec_name)}"
                f"{self._interaction_contract_section(spec_name)}"
                f"{self._triage_recheck_section(spec_name)}"
                f"IMPORTANT: 当前模型不支持图像输入——不要 Read 图片/截图文件（会被 hook 拦截），"
                f"截图仅作为证据文件。\n"
                f"IMPORTANT: Do NOT modify STATE.md."
            )

        elif agent_type == "planner-judge":
            report_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / "report.json"
            )
            result_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / ".fenix-run-result.json"
            )
            return (
                f"你是 Fenix Planner Agent。你的任务是分析验证引擎的测试报告，判定验证是否通过，"
                f"并对每个非 PASS 场景产出强制分类与结构化证据。\n\n"
                f"## 步骤\n"
                f"1. 读取 {report_path}\n"
                f"2. 按照判定规则分析每个断言结果\n"
                f"3. 聚合同类型失败，避免重复报告\n"
                f"4. **裁决证据分类（强制，add-verdict-evidence-taxonomy）**：对 {report_path} 中\n"
                f"   每一个 `status` 为 `fail`/`failed`/`error`/`warning` 的场景条目，在原位\n"
                f"   补充 `classification` 字段（四选一，见下方定义）与 `evidence` 字段（结构化\n"
                f"   证据，见下方格式），并把增强后的完整 report.json **覆盖写回** {report_path}\n"
                f"   （保持其它字段不变，仅对 FIT 场景增量写入 classification/evidence）。\n"
                f"   同时对每个非 PASS 场景补充 `assertion_triage` 数组——逐断言归因（强制，\n"
                f"   add-interaction-contract-and-per-assert-triage，格式见下方）。\n"
                f"   ⚠️ 本步 MUST 对全部非 PASS 场景补齐，缺一不可——缺分类、证据或逐断言\n"
                f"   归因会导致框架校验失败并重试裁决。\n"
                f"   ⚠️ 若 report.json 中已存在 classification/evidence（上一轮裁决残留），\n"
                f"   仍 MUST 逐场景核对 assertion_triage 是否齐全，缺则补齐后覆盖写回——\n"
                f"   不得因部分字段已存在而判定「无需改写」。\n"
                f"5. 将运行结果写入 {result_path}（绝对路径，与场景/报告文件同目录，"
                f"不要写别处）\n"
                f"6. 写入 {spec_dir}/verification-report.md（人类可读的验证报告）\n\n"
                f"## 判定规则\n\n"
                f"### 第1-2层断言失败 → 一定是Bug\n"
                f"元素不存在、不可见、点击被拦截、重叠等。直接记录，不需要额外判断。\n\n"
                f"### 第3层断言失败 → 大概率是Bug\n"
                f"文字不匹配、属性错误、DOM结构错误。除非有明显理由（如SPEC允许动态内容），否则记为Bug。\n\n"
                f"### no_auth_error 特判（真实云端端到端场景）\n"
                f"- 出现「签名验证失败」「InvalidAccessKeyId」「SignatureDoesNotMatch」等"
                f"密钥/签名错误 → 产品 Bug（密钥派生或加解密正确性问题）。\n"
                f"- 仅网络不可达（超时、连接失败、DNS 错误），且无上述密钥/签名关键词 → "
                f"环境问题，不记为产品 Bug，报告中标注「网络环境不可达，无法验证」。\n\n"
                f"### no_console_error 外部 API 网络错误特判\n"
                f"- 断言结果含 `filtered_network` 字段且 `errors` 为空 → 该断言通过："
                f"涉及外部 API 的场景已声明豁免，net::ERR_ 等网络层错误按环境因素过滤，"
                f"不记为 Bug。\n\n"
                f"### 断言时序特判（弹窗/对话框关闭后查询弹窗内元素）\n"
                f"- 断言失败原因为「元素随弹窗/对话框关闭而从 DOM 移除」（如 Locator 超时、"
                f"evaluate 找不到节点），且同场景其他功能性断言通过 → 判为断言时序问题"
                f"（测试场景设计缺陷，classification=test-defect），不记为产品 Bug；报告中标注「断言时序问题：应在"
                f"交互前校验或改断言弹窗外持久 DOM」。\n"
                f"- 典型模式：点击「保存」后弹窗立即关闭，后续仍断言弹窗内输入框的值。\n\n"
                f"### 第4层断言失败 → 需结合上下文\n"
                f"- SSIM低于阈值：检查是否为动态内容区域（时间戳/随机推荐）。是→忽略，不是→Bug。\n"
                f"- 元素溢出：检查是否在预期视口尺寸内。是→忽略，不是→Bug。\n\n"
                f"### 聚合规则\n"
                f"- 同一场景同一类型的失败 → 合并为1个Bug\n"
                f"- 同一元素在多个场景中同一类失败 → 标记为\"系统性问题\"\n"
                f"- 3个以上场景出现相同root cause → 只报1个Bug，标注影响范围\n\n"
                f"## 裁决分类与证据（强制，add-verdict-evidence-taxonomy）\n\n"
                f"### 分类定义（classification 取值限四选一）\n"
                f"- `product-bug`：根因是产品缺陷——断言/功能失败由被测产品代码导致。\n"
                f"  ⚠️ 禁止映射为 `warning`（产品缺陷不得悬置）。\n"
                f"- `test-defect`：根因是测试用例自身错误（选择器失效、断言时序、幻觉\n"
                f"  testid、场景设计缺陷）。同样 MAY → failed（不悬置为 warning）。\n"
                f"- `flaky`：不稳定、重试可过的场景（非根因性失败）。MAY → warning。\n"
                f"- `env`：环境/基础设施问题（应用不可达、网关抖动、网络环境不可达、\n"
                f"  测试环境配置缺失）。MAY → warning。\n\n"
                f"### 分类-状态映射约束（design D3，框架采纳处会强制重写）\n"
                f"- `product-bug` / `test-defect` MUST 映射为场景 `status=failed`；\n"
                f"  若你给了 `warning` 但分类是 product-bug/test-defect，框架会强制改为\n"
                f"  `failed` 并在报告标注「已修正」——请在裁决时直接给对。\n"
                f"- `flaky` / `env` MAY 映射为 `warning`（不阻塞），但也可标记 failed。\n"
                f"- 禁止 `product-bug` 映射为 `warning`。\n\n"
                f"### evidence 结构（每个非 PASS 场景 MUST 提供，至少含一项）\n"
                f"```json\n"
                f'  "evidence": {{\n'
                f'    "failed_assertions": [\n'
                f'      {{"type": "element_visible", "selector": ".result-item",\n'
                f'       "expected": "可见", "actual": "元素不存在"}}\n'
                f'    ],\n'
                f'    "screenshots": ["<截图相对或绝对路径>"],\n'
                f'    "first_failed_step": "步骤3: 点击提交按钮后无响应"\n'
                f'  }}\n'
                f"```\n"
                f"- `failed_assertions`：从场景 assertion_results 中摘取未通过断言\n"
                f"  （type/selector/expected/actual）；\n"
                f"- `screenshots`：证据截图路径列表（取自场景 screenshots）；\n"
                f"- `first_failed_step`：首个失败步骤的中文描述。\n"
                f"三者至少提供其一，且 `failed_assertions` 与 `screenshots` 优先从既有数据摘取。\n\n"
                f"### assertion_triage 逐断言归因（强制，add-interaction-contract-and-per-assert-triage）\n"
                f"```json\n"
                f'  "assertion_triage": [\n'
                f'    {{"assertion": "no_click_interception .dark-Card button 停止",\n'
                f'     "classification": "test-defect",\n'
                f'     "evidence": "选择器含臆测类名，元素从未存在（DOM snapshot 佐证）"}}\n'
                f'  ]\n'
                f"```\n"
                f"- 每个非 PASS 场景 MUST 对其**每一条失败断言**单独给出一条归因：\n"
                f"  `assertion`（断言内容：type + selector/expected）、`classification`\n"
                f"  （四选一，与场景分类定义一致）、`evidence`（该断言的证据/理由，非空）。\n"
                f"- 场景级豁免（不记产品 Bug）仅当该场景**全部失败断言**均被单独归类为非\n"
                f"  product-bug 时成立；任一断言归类 product-bug → 场景 MUST `failed`，\n"
                f"  不得整体豁免（v2-overview-page 事故：6 个失败场景被整体豁免放行，\n"
                f"  掩盖了卡片跳转缺失的真实缺陷）。\n"
                f"- 校验器会核对条目数与失败断言数、归类取值与证据非空——缺失或漏条目\n"
                f"  会触发裁决重试。\n\n"
                f"### .fenix-run-result.json 格式\n"
                f'{{\n'
                f'  "status": "verified" | "bug-found",\n'
                f'  "bugs": [\n'
                f'    {{\n'
                f'      "severity": "critical" | "major" | "minor",\n'
                f'      "scenario_ids": ["场景ID列表"],\n'
                f'      "assertion_type": "断言类型",\n'
                f'      "description": "Bug的清晰中文描述",\n'
                f'      "root_cause": "推断的根因",\n'
                f'      "evidence": {{...}}\n'
                f'    }}\n'
                f'  ],\n'
                f'  "summary": "验证总结"\n'
                f'}}\n\n'
                f"{self._scenario_freeze_section(spec_name)}"
                f"{self._triage_recheck_section(spec_name)}"
                f"{self._verdict_rejection_section(spec_name)}"
                f"IMPORTANT: Do NOT modify STATE.md."
            )

        elif agent_type == "fast-track":
            progress_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / f"{spec_name}.json"
            )
            scenarios_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / "test_scenarios.json"
            )
            result_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / ".fenix-run-result.json"
            )
            return (
                f"You are the Fenix Fast-Track Agent. You implement AND verify the SPEC at "
                f"{spec_dir}/ in a single run, in the SAME context and worktree.\n\n"
                f"## PHASE 1 — Implement\n"
                f"1. Read {spec_dir}/proposal.md, {spec_dir}/design.md, {spec_dir}/specs/\\*.md, "
                f"{spec_dir}/tasks.md.\n"
                f"2. Find the next unchecked task (`- [ ]`) and implement it — production code, not stubs.\n"
                f"3. Run the project's tests; fix failures (max 3 fix rounds per task).\n"
                f"4. Commit each task: `[fenix] {spec_name}: <task description>`.\n"
                f"5. Mark the task complete in tasks.md (`- [ ]` → `- [x]`).\n"
                f"6. Repeat until ALL tasks are done — do NOT stop after one task.\n\n"
                f"## PHASE 2 — Design verification scenarios\n"
                f"1. Write the scenario set to {scenarios_path} using the Planner scenario JSON schema "
                f"(array of {{id, description, steps, assertions, ...}}; see schema below).\n"
                f"2. Write {progress_path}: {{\"total\": N, \"done\": 0, \"current\": \"scenario-design\"}}.\n\n"
                f"## PHASE 3 — Execute scenarios (REAL environment)\n"
                f"1. Start the application in the worktree (npm run dev etc.). Use playwright-cli — "
                f"code analysis alone = FAILURE.\n"
                f"2. Execute each scenario one by one; after each, increment done in {progress_path} "
                f"and take screenshots as evidence.\n"
                f"3. Do NOT read image files — assert via DOM snapshot text.\n\n"
                f"## PHASE 4 — Adjudicate & write result\n"
                f"1. For every non-passing scenario, classify: product-bug | test-defect | flaky | env, "
                f"and attach structured evidence (failed_assertions / screenshots / first_failed_step).\n"
                f"2. Verdict: verified if no product-bug remains; else bug-found.\n"
                f"3. Write the unified result file (root of the worktree) `.fenix-run-result.json`:\n"
                f'{{\n'
                f'  "status": "success",\n'
                f'  "spec": "{spec_name}",\n'
                f'  "mode": "fast-track",\n'
                f'  "summary": "<brief summary>",\n'
                f'  "implementation": {{"deliverables": ["core/foo.py"]}},\n'
                f'  "verification": {{\n'
                f'    "scenarios": [\n'
                f'      {{\n'
                f'        "scenario_id": "s1",\n'
                f'        "description": "场景描述",\n'
                f'        "status": "pass|fail|error|warning|exempt",\n'
                f'        "assertion_results": [{{"type": "step", "pass": true, "message": ""}}],\n'
                f'        "screenshots": ["/绝对路径/证据截图.png"],\n'
                f'        "evidence": {{"failed_assertions": [...]}},\n'
                f'        "classification": "product-bug|test-defect|flaky|env"\n'
                f'      }}\n'
                f'    ],\n'
                f'    "verdict": "verified|bug-found",\n'
                f'    "bugs": [{{"severity": "critical|major|minor", "scenario_ids": [...], '
                f'"description": "...", "root_cause": "..."}}]\n'
                f'  }}\n'
                f'}}\n'
                f"4. If verdict is bug-found and you still have fix budget, fix in the SAME context, "
                f"re-run affected scenarios, re-adjudicate, and overwrite the result file.\n"
                f"5. If fix budget is exhausted and bugs remain, still write the file with "
                f'verification.verdict="bug-found" — the daemon escalates to full mode.\n'
                f"6. Also write {scenarios_path} AND {result_path} into the verify-progress dir "
                f"(scenario set must persist so a later full-mode verifier can reuse it).\n\n"
                f"## Guards (MANDATORY, the daemon enforces them)\n"
                f"- Zero-change guard: claiming success with zero new commits AND zero Edit/Write tool "
                f"calls = treated as failure and re-dispatched.\n"
                f"- Deliverable gate: every deliverable path you write in your commits must exist on "
                f"the branch; missing deliverables block the run.\n"
                f"- Fix budget: in-run fix rounds count against `agents.impl_run_budget`; budget "
                f"exhausted with remaining bugs → automatic upgrade to full mode.\n"
                f"- Do NOT modify STATE.md — the daemon owns it.\n\n"
                f"## 交互契约（interaction-contract，强制，add-interaction-contract-and-per-assert-triage）\n"
                f"- 凡你实现为**可交互形态**的元素（按钮/链接样式卡片/可点击行/表单控件），"
                f"其行为 MUST 在对应 SPEC 中有定义，或在任务书中显式声明「纯展示、不可交互」。\n"
                f"- 两者皆不满足时，MUST 在 .fenix-run-result.json 增设 `findings` 数组登记"
                f"「待裁决交互」条目（元素、现状、建议行为），不得静默保留可交互外观：\n"
                f'  "findings": [{{"type": "pending-interaction", "element": "<元素标识>", '
                f'"current": "<现状>", "suggestion": "<建议行为>"}}]\n'
                f"- 已声明纯展示的元素即合规，收工守卫不因此拦截。\n"
                f"## 场景 JSON schema（Phase 2 输出）\n"
                f'[\n'
                f'  {{\n'
                f'    "id": "kebab-case-unique-id",\n'
                f'    "description": "中文场景描述",\n'
                f'    "steps": [\n'
                f'      {{"action": "navigate", "value": "https://..."}},\n'
                f'      {{"action": "click", "target": "[data-testid=\'add-btn\']", "description": "点击添加按钮"}}\n'
                f'    ],\n'
                f'    "assertions": [\n'
                f'      {{"type": "element_visible", "selector": ".result-item", "label": "新增项可见"}},\n'
                f'      {{"type": "no_console_error"}}\n'
                f'    ]\n'
                f'  }}\n'
                f']\n\n'
                f"Supported assertion types: element_visible, element_count, element_not_exist, "
                f"element_focused, element_enabled, no_click_interception, no_overlap, in_viewport, "
                f"z_index_order, text_match, text_contains, attribute_match, no_console_error, "
                f"no_network_error, no_auth_error, dom_structure, no_overflow, alignment\n"
                f"Supported action types: navigate, click, type, clear, select, scroll, wait, dialog, "
                f"seed, mock_api\n"
                f"{self._scenario_freeze_section(spec_name)}"
                f"{self._interaction_contract_section(spec_name)}"
                f"IMPORTANT: Do NOT read image files. Do NOT modify STATE.md."
            )

        elif agent_type == "administrator":
            sig = detail or {}
            sig_spec = sig.get("spec") or spec_name
            sig_type = sig.get("signal_type") or "unknown"
            severity = sig.get("severity") or "major"
            description = sig.get("description") or ""
            evidence = sig.get("evidence") or ""
            recommendation = sig.get("recommended_action") or ""
            dash_script = f"{self._pm.project_root}/.fenix/bin/fenix_dashboard.py"
            # fix-admin-run-blocks-mainloop D3：处置状态文件按 run 实例分离，
            # 写入路径由 run_administrator 注入 signal；缺失时回退旧全局路径
            # （仅影响绕过 run_administrator 的直接构建，正常链路必然注入）。
            disp_path = (sig.get("disposition_path")
                         or f"{self._pm.project_root}/.fenix/admin_disposition.json")
            return (
                f"You are the Fenix Administrator Agent — 运维角色，"
                f"负责处置 Agent 无法自行脱困的困境。\n\n"
                f"## 困境信号\n"
                f"- 类型: {sig_type}\n"
                f"- spec: {sig_spec}\n"
                f"- 严重度: {severity}\n"
                f"- 描述: {description}\n"
                f"- 证据: {evidence}\n"
                f"- 建议处置: {recommendation}\n\n"
                f"## 你的高级权限（自主处置，无需询问）\n"
                f"- 杀死进行中的 Agent 子进程（先 ps 确认归属再操作）\n"
                f"- 需要重启 fenixd 时：写 .fenix/restart_request 文件（内容随意），"
                f"supervisor 会负责重启；【不要】直接 kill daemon——daemon 是你的宿主进程，"
                f"kill 它会连带杀死你，导致重启和处置记录都丢失\n"
                f"- git 清理：worktree prune / stash / reset / commit / 分支管理\n"
                f"- 直接修改 Fenixd 自身代码（当前已在主树）并提交\n"
                f"- 发起新的 SPEC（创建 openspec/changes/<name>/ 并更新 STATE.md）\n"
                f"- 重置/修复 spec 状态（将卡死 spec 更新为 ready/blocked 并清空陈旧字段）\n"
                f"- 运维跨项目 Dashboard 服务（见下方运维手册）\n"
                f"- 修正错误的验证基础设施文件：检查并修复 "
                f".fenix/verify-progress/<spec>/test_scenarios.json 的协议/URL/断言等"
                f"基础设施性错误（如 https 访问纯 HTTP 服务、端口错误、失效模板）"
                f"— 这属验证基础设施修正而非产品开发\n\n"
                f"## Dashboard 服务运维手册\n"
                f"- 脚本: python3 {dash_script}（bin/fenix_dashboard.py），默认端口 8787\n"
                f"- 【探活】必须双重校验：/api/projects 返回含 \"projects\" 字段的 JSON "
                f"且首页返回 200；仅检查 HTTP 200 会误判（SPA fallback 对任意路径返回 200）\n"
                f"- 【常驻启动】未运行时使用 tmux 常驻："
                f"tmux new-session -d -s fenix-dashboard \"python3 {dash_script} --serve\"，"
                f"随后轮询探活至就绪（约 1 秒）；tmux 常驻不受你的子进程退出影响\n"
                f"- 【注册监控】python3 {dash_script} --add-project <项目根目录>；"
                f"【列表】--list-projects；【停止】tmux kill-session -t fenix-dashboard\n"
                f"- 若你处置期间发现 dashboard 已退出/未监听，恢复常驻是你的职责"
                f"（探测 → 重启 → 注册）\n\n"
                f"## 铁律\n"
                f"1. 只处置困境，不开发功能、不实现 SPEC 需求。\n"
                f"2. 先只读诊断（日志/STATE.md/进程/run 转录），确认根因再动手。\n"
                f"3. 所有处置动作留痕（在处置记录中说明）。\n"
                f"4. 持久化优先：完成诊断后【先】写一次 {disp_path}"
                f"（含初步结论与计划动作），再执行破坏性动作；任何时刻被杀都不丢处置记录。\n"
                f"5. 若确实无法自主处置（需人类决策、连续失败、不可逆操作），"
                f"将 escalate 置为 true 并给出 recommended_action。\n\n"
                f"## 完成后\n"
                f"把最终处置记录写入 {disp_path}（当前目录即主树），"
                f"覆盖之前的初步记录。其中 summary 字段为必填：人类可读的 Markdown "
                f"叙述（JSON 内换行转义为 \\n），【必须】按以下固定模板组织，"
                f"四个二级标题缺一不可，顺序固定：\n"
                f"```\n"
                f"## 诊断结论\n"
                f"**一句话定性（是/非产品缺陷、根因类别）。** 随后展开：问题是什么、"
                f"为什么发生、关键证据是什么。\n\n"
                f"## 处置时间线\n"
                f"1. 动作一（含证据/留痕位置）；2. 动作二；……（按实际顺序编号，"
                f"每步可核查，禁止遗漏破坏性动作）\n\n"
                f"## 最终结果\n"
                f"- spec 状态变化（如 blocked → pushed）\n"
                f"- 验证/测试结果（N/N 通过）\n"
                f"- 留痕位置（commit 号、备份目录等）\n\n"
                f"## 对人类的建议\n"
                f"无需介入时写明结论与系统性观察；需介入时给出具体可执行的操作。\n"
                f"```\n"
                f'{{\n'
                f'  "spec": "{sig_spec}",\n'
                f'  "problem": "处理的困境问题",\n'
                f'  "actions_taken": ["动作1", "动作2"],\n'
                f'  "result": "resolved | partially-resolved | escalated",\n'
                f'  "summary": "按上述模板的 Markdown 叙述全文",\n'
                f'  "escalate": true/false,\n'
                f'  "recommended_action": "若升级，给出人类应做的操作"\n'
                f'}}\n'
                f"然后结束，无需额外输出。不要直接编辑 .fenix/admin_alerts.json——"
                f"daemon 会基于你的处置记录写入。\n"
            )


    def _build_legacy_section(self, spec_name: str) -> str:
        """构建 implementer prompt 的「遗产检查」段（add-recovery-legacy-check 2.1）。

        无在册遗产返回空串（2.2：prompt 与现状逐字节一致）。有遗产时追加：
        - 遗产 worktree 绝对路径、分支名
        - 现场 ``git status --short`` 脏文件快照（截断 50 行）
        - 只读约束（不得在遗产内工作，已物理隔离为新 worktree）
        - 收编 / 弃用自主决策要求与响应格式（含 ``salvaged from <branch>`` 标注）

        worktree_manager 缺失（测试/未初始化）时安全返回空串。脏文件快照采集失败
        时降级为「（无法读取快照）」，不阻断注入。
        """
        wm = getattr(self._pm, "worktree_manager", None)
        if wm is None or not hasattr(wm, "get_legacy"):
            return ""
        legacy = wm.get_legacy(spec_name)
        if not legacy:
            return ""
        path = legacy.get("path", "")
        branch = legacy.get("branch", "")
        dirty_snapshot = self._legacy_dirty_snapshot(path)
        return (
            f"\n\n## ⚠️ RECOVERY LEGACY (遗产检查 — 你是从死亡 run 的恢复重派)\n"
            f"\n"
            f"上一次实现 run 在死亡前留下了未提交的半成品 worktree，被保留为「遗产」"
            f"供你参考与收编（框架不担保其内容正确性，决策权在你）。\n\n"
            f"### 遗产位置\n"
            f"- 路径（只读参考，绝对路径）: `{path}`\n"
            f"- 分支名: `{branch}`\n\n"
            f"### 脏文件快照（git status --short，继承自上轮未完成的工作）\n"
            f"```\n{dirty_snapshot}\n```\n\n"
            f"### 边界约束（务必遵守）\n"
            f"- 遗产 worktree 为**只读参考**：你只能在其中 inspect（cat / git log / git diff），"
            f"**不得**在其中执行任何写操作（不要 Edit/Write/commit）。\n"
            f"- 你当前的工作目录是**全新的** worktree（与现状一致，物理隔离），所有新工作"
            f"都必须在你自己的 worktree 内进行。\n"
            f"- 不要把遗产 worktree 作为你的工作目录，也不要在其中继续开发。\n\n"
            f"### 你的决策权（二选一，框架不强加）\n"
            f"inspect 遗产后，自行决定：\n"
            f"1. **收编 (salvage)**：若遗产中的半成品有价值，把对应文件内容复制进你自己的"
            f" worktree、适配后提交，并在提交信息中注明来源分支，格式：\n"
            f"   `[fenix] {spec_name}: <改动> (salvaged from {branch})`\n"
            f"   ——便于事后溯源，且验证链会照常全量验收你的产出（收编不豁免测试）。\n"
            f"2. **弃用 (discard)**：若遗产为破碎半成品、不值收编，从你自己的干净状态重做，"
            f"并在最终产出说明中注明弃用理由（无强制格式，一句话即可）。\n\n"
            f"### 响应格式要求\n"
            f"在你的任务书响应中明确声明本次选择了哪条路径：\n"
            f"- 收编：列出你从遗产移植的文件与其来源分支 `{branch}`；\n"
            f"- 弃用：简述弃用理由。\n"
            f"若未使用遗产（首次实现 / 遗产已被兜底回收），本段不会出现，正常实现即可。\n"
        )


    def _legacy_dirty_snapshot(self, wt_path: str) -> str:
        """现场采集遗产 worktree 的 ``git status --short`` 脏文件清单，截断 50 行。

        采集失败（worktree 已不存在等）返回降级提示串，不抛出异常。
        """
        import subprocess as _sp
        try:
            res = _sp.run(
                ["git", "-C", str(wt_path), "status", "--short"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return "（无法读取遗产快照）"
        if res.returncode != 0:
            return "（无法读取遗产快照）"
        lines = res.stdout.splitlines()
        if not lines:
            return "（无脏文件，遗产已干净提交）"
        if len(lines) > 50:
            lines = lines[:50] + [f"... 其余 {len(lines) - 50} 个文件省略"]
        return "\n".join(lines)


    def _scenario_freeze_section(self, spec_name: str) -> str:
        """构建场景集冻结约束段（add-verify-scenario-freeze / design D1-D2）。

        修复轮（``_verify_fail_rounds > 0`` 或 tasks.md 含「## 验证修复」）时注入
        持久化集与「仅新增范围可追加、删减须理由」约束；首轮验证返回空串（不约束）。

        纯本地确定性读取（core.verify_scenarios），不触发 LLM。
        """
        try:
            from core.verify_scenarios import (
                load_scenario_set, is_repair_round,
                read_verify_fix_section, declares_new_delivery,
            )
        except Exception:
            return ""
        entry = None
        try:
            entry = self._pm.state_machine.read_one(spec_name)
        except Exception:
            entry = None
        if not is_repair_round(self._pm.project_root, spec_name, entry):
            return ""
        persisted = load_scenario_set(self._pm.project_root, spec_name)
        if persisted is None or not persisted.scenarios:
            return ""
        fix_section = read_verify_fix_section(self._pm.project_root, spec_name)
        extended = declares_new_delivery(fix_section)
        ids = "、".join(s.id for s in persisted.scenarios)
        lines = [
            "",
            "## 验证场景集冻结（修复轮约束，add-verify-scenario-freeze）",
            "",
            f"- 你处于**修复轮**：必须复用持久化场景集，不得重新膨胀场景面。",
            f"- 持久化集共 {len(persisted.scenarios)} 个既有场景（第 "
            f"{persisted.round} 轮稳定），MUST 全部覆盖：{ids}",
        ]
        if extended:
            lines.append(
                "- 修复段声明了**新增交付范围**：仅允许为该新增范围追加场景，"
                "新增场景在 JSON 顶层用 ``added_in_round`` 标注本轮轮次；"
                "非该范围的场景不得新增。"
            )
        else:
            lines.append(
                "- 修复段**未声明新增交付范围**：MUST NOT 新增任何场景"
                "（修复轮不扩容，design D2）。"
            )
        lines.append(
            "- 移除既有场景 MUST 在场景对象上用 ``remove_reason`` 字段给出理由"
            "（如对应功能已按任务书移除）；无理由的缺场景将被确定性校验器以"
            "持久化集补齐（等效于忽略你的删减），验证报告标注。"
        )
        lines.append("")
        return "\n".join(lines)


    def _interaction_contract_section(self, spec_name: str) -> str:
        """构建交互契约约束段（add-interaction-contract-and-per-assert-triage 1.2）。

        从 SPEC 文档声明式提取可交互候选（design D1 首版模式）；检出候选时注入
        覆盖要求与 ``covers`` / ``declared_display`` 元数据登记规范。未检出候选
        返回空串（prompt 与现状逐字节一致，与 legacy-section 同型）。
        """
        try:
            from core.interaction_contract import collect_spec_candidates
            candidates = collect_spec_candidates(self._pm.project_root, spec_name)
        except Exception:
            return ""
        if not candidates:
            return ""
        lines = [
            "",
            "## 交互契约（interaction-contract，强制，add-interaction-contract-and-per-assert-triage）",
            "",
            "- 页面中渲染为**可交互形态**的元素（按钮/按钮组/链接样式卡片/可点击行/"
            "表单控件）MUST 至少对应一个交互场景（点击/操作后的可观察结果断言），"
            "或在元素定义处声明「纯展示、不可交互」。",
            "- 本 SPEC 检出的可交互候选（声明式首版模式）：",
        ]
        for c in candidates:
            note = "（SPEC 已标注纯展示）" if c.declared_display else ""
            lines.append(f"  - `{c.raw}`（{c.source}:{c.line}）{note}")
        lines += [
            "- 产出场景时，在场景对象上用 ``covers`` 字段登记该场景覆盖的元素标识"
            "（如 \"covers\": [\"dark-Card--link\"]）。",
            "- 无法生成交互场景的元素（纯展示），在任一场景对象上用 "
            "``declared_display`` 登记（如 \"declared_display\": [\"btn-x\"]）。",
            "- 契约校验器会确定性 diff 候选集与场景集：既无覆盖又无声明的元素会"
            "导致场景验收失败并退回重排（含链接样式卡片——v2-overview-page 事故的"
            "复发点）。",
            "",
        ]
        return "\n".join(lines)


    def _triage_recheck_section(self, spec_name: str) -> str:
        """构建优先复核注入段（add-verdict-evidence-taxonomy D5）。

        读取 pm_engine 落盘的 ``.fenix/verify-progress/<spec>/triage_recheck.json``
        （连续 2 轮 warning 的场景清单），注入 planner prompt 的「优先复核」清单，
        与 scenario-freeze 的基准集注入同一接入点（纯本地确定性读取，不触发 LLM）。
        文件缺失 / 为空 → 返回空串（不约束）。
        """
        recheck_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "triage_recheck.json"
        )
        if not recheck_path.exists():
            return ""
        try:
            data = json.loads(recheck_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        if not isinstance(data, list) or not data:
            return ""
        ids = "、".join(str(s) for s in data if s)
        if not ids:
            return ""
        return (
            "\n\n## 优先复核清单（warning 收敛升级，add-verdict-evidence-taxonomy）\n"
            f"- 以下场景连续 2 轮验证均为 warning，被标记为「优先复核」：{ids}\n"
            "- 你必须优先重新执行这些场景，甄别其根因究竟是真实产品缺陷（应改判 "
            "classificatio=product-bug 并 failed）还是确属 flaky/env（可维持 warning）。\n"
            "- 切勿继续无限悬置为 warning；若确为产品缺陷，必须在本次裁决中如实分类并 failed。\n"
        )


    def _verdict_rejection_section(self, spec_name: str) -> str:
        """构建裁决驳回注入段（verdict-rejection-retry：重试幂等陷阱修复）。

        读取 pm_engine 落盘的 ``.fenix/verify-progress/<spec>/verdict_violations.json``
        （上一轮裁决被确定性校验驳回的违规明细），注入 judge prompt，告知重试
        judge 具体缺口。文件缺失/为空 → 返回空串（首轮裁决不注入）。
        """
        rejection_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "verdict_violations.json"
        )
        if not rejection_path.exists():
            return ""
        try:
            data = json.loads(rejection_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        if not isinstance(data, list) or not data:
            return ""
        lines = [
            "\n\n## ⚠️ 上一轮裁决已被校验驳回（强制修复，verdict-rejection-retry）\n"
            "- 你现在看到的是重试裁决：上一轮写回的 report.json 未通过框架确定性校验，"
            "违规明细如下：\n"
        ]
        for v in data:
            if isinstance(v, dict):
                lines.append(
                    f"  - 场景 `{v.get('scenario_id')}`（status={v.get('status')}）："
                    f"{v.get('reason')}\n"
                )
        lines.append(
            "- ⚠️ report.json 中已存在的 classification/evidence（上一轮残留）"
            "不代表裁决合规——缺失的 `assertion_triage` 逐断言归因同样是强制字段。\n"
            "- 你 MUST 对全部非 PASS 场景补齐缺口（含逐断言 assertion_triage）后"
            "覆盖写回 report.json，不得因部分字段已存在而判定「无需改写」。\n"
        )
        return "".join(lines)
