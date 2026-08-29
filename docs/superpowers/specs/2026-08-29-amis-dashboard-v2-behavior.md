# Dashboard v2 行为规格(AMIS 重构实施者信息源)

日期:2026-08-29
配套设计文档:`docs/superpowers/specs/2026-08-29-amis-dashboard-v2-design.md`
本文是老版前端(app.js 2946 行)的**行为规格**,字段名一字不差;实施者以本文 + 设计文档为唯一信息源。

---

## 0. SSE 协议(所有实时行为的基础)

端点 `GET /api/stream`(HTTP/1.1 chunked,长连接)。所有事件均为**默认 message 帧**(无 `event:` 命名行),JSON 在 `data: ` 中,以 `type` 字段区分。25s 无事件发心跳注释帧 `: ping`。

| type | payload | 语义 |
|---|---|---|
| `hello` | `{type, cid}` | 连接首帧;`cid` 是后续 run watch 订阅凭证 |
| `state` | `{type, project, overview, specs, details}` | STATE.md/日志变化。`specs` 是**数组**(与 GET /api/specs 的 specs 同形);`details` 是 `{specName: specDetail}` 对象 |
| `detail` | `{type, project, spec, data}` | 单 SPEC 文件变化;`data` 为完整 specDetail |
| `run_meta` | `{type, project, run_id, status}` | run 状态转换(running→done/error) |
| `run_events` | `{type, project, run_id, status, events[, reset]}` | 被订阅 run 的增量事件;`reset:true` 表示文件被截断/轮转,须重新拉尾部 |
| `refresh` | `{type}` | 2s 周期心跳(daemon 状态/新项目发现),概览需跟随重拉 |
| `alerts` | `{type, project, summary}` | 告警变化(标记已处理/新告警后广播) |
| `admin_activities` | `{type, project}` | admin_alerts.json 变化(轻量通知,前端自行重拉) |

run 增量订阅协议:
- 注册:`POST /api/runs/<run_id>/watch?project=<p>&cid=<cid>` → `{ok: true}`
- 注销:`DELETE /api/runs/<run_id>/watch?project=<p>&cid=<cid>`
- cid 必须来自当前 SSE 连接的 hello 帧;SSE 断线重连后 cid 变化,须用新 cid 重新注册未关闭的 watch
- 只读 `/api/runs/<id>` REST 一次(tail),之后靠 run_events 增量

老版前端消费规则(app.js:180-228 摘要,即桥接层必须复刻的语义):
- `state`:overview 视图 → 节流重拉;project 视图且 `msg.project` 匹配 → 直接用 `msg.specs` 重渲染;spec 视图 → 优先用 `msg.details[currentSpec]`,无则回退 REST 重拉;其余 project 不匹配忽略
- `detail`:仅 spec 视图且 project+spec 匹配时用 `msg.data` 重渲染
- `run_meta` → 节流重拉;`refresh` → 仅 overview 视图节流重拉
- `run_events` → 弹窗打开且 run_id 匹配时增量追加
- `alerts` → 重拉横幅;activities 视图同时重拉
- `admin_activities` → admin 弹窗打开且 project 匹配时重拉解析端点
- **节流**:概览/refresh 触发的重拉有 500ms 前缘节流(app.js:172-178),`config` 视图不整页重绘(表单编辑中)

---

## 1. API 响应字段表

### GET /api/projects → `{projects: [...]}`

每项(server.py:271-285 + data.py:1111-1146):
```jsonc
{
  "name": "fenixd",              // str
  "path": "/root/fenixd",        // str
  "daemon": "running"|"stopped",
  "spec_count": 5,               // int
  "status_counts": {"drafted": 1, "done": 2, ...},  // 状态名→数量
  "task_done": 12, "task_total": 30,
  "problems": 1,                 // error 非空且状态非 done/pushed 的 SPEC 数
  "active_runs": 2,
  "scenario_count": 15,
  "updated": 1710000000.0,       // STATE.md mtime(浮点秒);不存在为 0
  "discovered": true,            // 自动发现(非显式注册)
  "exists": true                 // false 时仅有 name/path/discovered/exists/daemon/error 字段,error="项目路径不存在"
}
```

### GET /api/overview → `{projects: [...], totals: {...}}`

`projects` 与 /api/projects 同形(data.py:1353-1378)。`totals`:
```jsonc
{"spec_count": 0, "task_done": 0, "task_total": 0, "problems": 0, "active_runs": 0,
 "status_counts": {...}}
```

### GET /api/specs?project=<name> → `{project: <name>, specs: [...]}`

每项(data.py:1149-1173):
```jsonc
{
  "name": "add-admin-invoke-dialog",
  "status": "drafted|ready|implementing|implemented|testing|verified|bug-found|blocked|done|pushed",
  "priority": 3,                 // int 1-9,可能为 null
  "created": "2026-08-20T...",   // ISO 字符串,可能为 null
  "updated": "2026-08-21T...",
  "error": "..." | null,
  "task_done": 4, "task_total": 6,
  "verify_done": 1, "verify_total": 3, "verify_error": null,  // verify_progress.error
  "scenario_count": 5,
  "total_duration": 120,         // int 秒,该 spec 全部 run 的 duration_seconds 之和,无 run 为 0
  "latest_run": "impl-xxx-1710" | null,
  "latest_run_status": "running|done|error|empty" | null
}
```
服务端已按 created 倒序排;project 未知/不存在 → `{error: "...", specs: []}`。

### GET /api/specs/<spec>?project=<name> → specDetail(data.py:1310-1350)

```jsonc
{
  "project": "fenixd",           // server.py:317 附加
  "name": "...", "status": "...", "priority": 3, "created": "...", "updated": "...",
  "error": null, "branch": "fenix/xxx", "implementer_run": "...", "tester_run": "...",
  "depends_on": "..." | null,
  "tasks": [ {"title": "1. 分组名", "tasks": [{"done": true, "id": "1.1", "desc": "..."}], "done": 2, "total": 3} ],
  "verify_progress": {"exists": true, "total": 3, "done": 1, "current": "...", "step": null, "error": null},
    // 文件不存在 → {exists: false, total: 0, done: 0, current: ""};损坏 → {exists: true, error: "corrupt", ...}
  "report": {"exists": true, "error": null|"<损坏标记>", "timestamp": "...", "summary": {...}|null},
    // summary: {total, passed, warnings, failed, errors}(report.json 原文)
  "scenarios": [ {"scenario_id": "S1", "description": "...", "status": "pass|warning|fail|error",
                  "assertion_results": [{"type": "...", "label": "...", "pass": true, "message": "", "detail": "", "actual": ""}],
                  "step_results": [{"action": "...", "description": "...", "success": true, "error": "", "message": ""}],
                  "screenshots": ["file.png"]} ],   // 已归一化为文件名
  "bugs": [ {"source": "report", "severity": "major|critical", "scenario_ids": ["S1"],
             "assertion_type": "...", "description": "...", "evidence": "...",
             "screenshots": ["file.png"], "scenario_status": "fail"} ],
  "screenshots": [ {"file": "a.png", "size": 1234, "mtime": "ISO"} ],
  "runs": [ {"run_id": "...", "agent_type": "implementer|verifier|planner|planner-plan|planner-judge|tester|agent",
             "spec": "...", "status": "running|done|error|empty", "duration_seconds": 90,
             "started": "ISO", "file_size": 123} ],   // mtime 倒序
  "verdict": {"exists": true, "status": "结论标题", "status_detail": "状态行",
              "conclusion": "结论段(≤600字)", "summary": {"passed": "0", "failed": "2", "errors": "10",
              "product_bugs": "1", "env_issues": null}},   // 值可能为字符串或 null
  "timeline": [
    {"time": "ISO", "kind": "state", "from": "drafted", "to": "implementing", "reason": ""},
    {"time": "ISO", "kind": "state", "from": "testing", "to": "bug-found", "reason": "验证发现 bug,退回修复"},
    {"time": "ISO", "kind": "run", "run_id": "...", "agent_type": "...", "status": "...", "spec": "...", "duration_seconds": 90}
  ]
}
```
timeline 规则(data.py:1195-1266):按时间升序;连续前向状态节点折叠为一次(首 from→尾 to);回退(带 reason)与运行节点独立且打断折叠;回退节点 reason 优先取 10 分钟内 Agent 记录的 error(截 120 字符),否则按规则兜底(data.py:1182-1192)。回退判定:`_LIFECYCLE_ORDER[to] < _LIFECYCLE_ORDER[from]`,order 表见 data.py:1178-1179(bug-found=2.5)。

### GET /api/runs/<run_id>?project=<p>&tail=<n> → data.py:1009-1038

```jsonc
{"run_id": "...", "exists": true|false, "status": "done|error|running|empty|missing",
 "events": [...最后 tail 条(默认 300,上限 2000)...], "total_events": 1234, "error": {...}|null}
```
`error` 字段为文件中**最后一条** type=error 的事件对象。run 文件不存在 → `exists:false, status:"missing"`。

**事件对象形态**(JSONL 逐行,损坏行降级 `{type:"stderr", line:<原文>}`):
```jsonc
// assistant(LLM 输出)
{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."},
    {"type": "tool_use", "name": "Bash", "input": {...}}]}}
// user(工具结果回传)
{"type": "user", "message": {"content": ["纯文本串...", {"type": "tool_result", "content": "...", "is_error": false}]}}
// 顶层 tool_use / tool_result(亦存在)
{"type": "tool_use", "name": "...", "input": {...}}
{"type": "tool_result", "content": "...", "is_error": false}
{"type": "result", "result": "总结文本", "num_turns": 7}
{"type": "error", "error": "错误信息", "exit_code": 1}
{"type": "stderr", "line": "..."}
{"type": "system", "subtype": "thinking_tokens", ...}   // 逐条 token 统计,需合并
```

### GET /api/spec-doc?project=<p>&spec=<s>&doc=<proposal|design|tasks>

server.py:320-354 + data.py:214-247:
- 成功:`200 {found: true|false, content: "<原文>", project, spec, doc}`(文件缺失也是 200 + found:false)
- doc 非法 → 400;spec 不在 STATE.md / 非 kebab-case → 404

### GET /api/config[?project=<p>] → data.py:1430-1498(read_config) / 1501+(read_effective_config)

```jsonc
{
  "llm": {"providers": [{"name": "...", "baseurl": "...", "apikey": "...", "model": "...", "env": {"K": "V"}}]},
    // 无 llm 键时为 {}(注意:不保证有 providers 数组!老版用 (llm.providers||[]) 兜底)
  "agents": {"models": {"implementer": {"model": "m1"|null,
                                          "provider": [{"provider": "p1", "model": "m2"|null}, ...]},
                          ...},
             "max_concurrent": 2, "run_timeout_seconds": 3600, "max_turns": 300, "daily_run_limit": 50},
  "gates": {"approve_mode": "manual|auto"},
  "scope": "user"|"project",
  "raw_exists": true|false,       // 该作用域 config.yaml 文件是否存在
  "sources": {"llm": "user|project", "agents.models": "...", "agents.max_concurrent": "...",
              "agents.run_timeout_seconds": "...", "agents.max_turns": "...", "agents.daily_run_limit": "...",
              "gates.approve_mode": "..."},   // "project"=本文件显式定义;"user"=继承用户级/默认
  "error": null|"配置文件解析失败: ...",
  "project": "fenixd"             // 仅项目模式附加
}
```
`agents.models` 已由服务端 `ConfigLoader.normalize_agent_models` 规范化(core/config.py:435-473):每角色 `{model: 角色级缺省|null, provider: [{provider, model: 解析后模型|null}, ...]}`。无该角色定义时**键不存在**(前端按 `models[at.key] || null` 处理)。

### GET /api/alerts[?project=<p>](server.py:552-589)

不带 project(跨项目聚合,顶部横幅用):
```jsonc
{"total_unhandled": 2, "projects": [{"name": "...", "unhandled_count": 1, "max_severity": "major", "latest": {...}}],
 "alerts": [ {..单条告警, 附加 "project" 字段..}, ... ]}   // 仅未处理,created 倒序
```
带 project:`{project: "<name>", alerts: [全部记录], summary: {unhandled_count, max_severity, latest}}`。
单条告警字段(app.js:339-356 消费):`{id, project, spec, severity: critical|major|minor, created, description, evidence, action_taken, recommended_action, handled}`。

### GET /api/admin-activities[?project=<p>&spec=<s>](server.py:591-621 + data.py:74-137)

不带 project:`{projects: [{name, activities: [...]}, ...]}`(每项目分组,记录附加 project 字段)。
带 project:`{project, spec, activities: [...]}`。
activity 记录字段(app.js:462-492 消费):`{id, kind, admin_run_id, spec, signal_type, summary, actions_taken(=action_taken 兜底), result: resolved|partially-resolved|escalated|failed|pending, status, created, handled: bool, escalation_id: str|null}`。
排序:未处理升级关联(escalation_id 非空)置顶,组内 created 倒序;`?spec=` 过滤在置顶之后。

### 写操作端点响应

| 端点 | 成功 | 失败 |
|---|---|---|
| POST /api/spec-error-clear?project&spec | `{ok:true, project, spec}` | 404(项目/spec) |
| POST /api/spec-priority?project&spec(body `{priority:N}`) | `{ok:true, project, spec, priority}` | 400(缺 priority/越界 1-9)、404 |
| POST /api/spec-delete?project&spec | `{ok:true, project, spec, archived, archive_path}` | 404、409(有进行中运行) |
| POST /api/spec-admin-invoke?project&spec | `{ok:true, project, spec, created}` | 404、409(**已有未消费请求**——前端视为"已在处置中"而非错误) |
| POST /api/alerts/<id>/handled?project | `{ok:true, id}` | 400、404 |
| POST /api/alerts/clear | `{ok:true, cleared:N}` | — |
| POST /api/config[?project] | 读回的最新配置 + `saved:true, scope, path` | 400 `{error}` |
| POST /api/projects/<name>/start\|stop | `{ok:true, session, already, was_running}` | 环境异常也是 200 + `{ok:false, error}` |
| DELETE /api/projects/<name> | `{ok:true, path}` | 400 |

所有错误:`{error: "<msg>"}` + HTTP 状态码。

---

## 2. SPEC 列表行为

### 8 列(app.js:837-845 + specRow:906-956)

1. **状态**:statusPill。STATUS_META 映射(app.js:44-55):drafted=📝草稿/ready=📌就绪/implementing=🔨实现中/implemented=🧪已实现/testing=🔍验证中/verified=✅已验证/bug-found=🐛有Bug/blocked=🛑阻塞/done=🎯完成/pushed=🚀已推送
2. **名称**:fix 子行缩进 `depth*18px` + `🔧 ` 前缀;orphan fix 行加 `orphan-fix` class;单元格带 `data-project`/`data-spec`(hover 提示与右键菜单定位)
3. **优先级**:`P<value>`,null 显示 `P?`
4. **创建时间**:fmtDate(local,"zh-CN");缺失显示 `—`
5. **任务进度**:进度条 + `done/total` + 百分比;颜色:100%=good,≥60%=默认,>0=warn,=0=serious
6. **验证**:`verify_done/verify_total`(verify_total>0),否则 `—`
7. **耗时**:fmtDuration(total_duration)(>0),否则 `—`;格式 `<60秒> / <N分[M秒]> / <H时M分[S秒]>`
8. **文档**:「文档」链接 → 打开文档弹窗(不排序)

整行点击 → 跳转 `#/spec/<project>/<spec>`。

### 状态生命周期排序(app.js:709-712)

```
drafted:0, ready:1, implementing:2, bug-found:2.5, implemented:3,
testing:4, verified:5, done:6, pushed:7, blocked:8    // 未知状态 99
```

### 排序交互(app.js:890-904)

表头点击轮换:新列 → asc;同列 asc → desc;同列 desc → 取消(回默认)。**默认无排序 = created 倒序,缺失排末尾**。排序键取值(app.js:785-796):task=done/total,verify=verify_done,其余直取;缺失值(null/undefined/'')恒排末尾。数字按数值比较,其余 localeCompare。

### 3 个过滤器(app.js:820-829)

- 关键词:`s.name.toLowerCase().includes(q)`(大小写不敏感)
- 状态下拉:精确匹配 `s.status`;选项 = 全部状态 + 10 个 STATUS_META
- 类型:`req` → 隐藏 `fix-` 前缀;`issue` → 仅保留 `fix-` 前缀
- 过滤状态(关键词/状态/类型)跨刷新保持(模块级变量)
- 空态区分:`specs.length===0` → "该项目暂无 SPEC";过滤后为空 → "无匹配的 SPEC"

### fix- 前缀树形分组(app.js:715-814,完整规则)

- `isFix(n)` = `n.startsWith('fix-')`
- **找父**:对 fix 规格,循环剥 `fix-` 前缀:candidate=`fix-fix-a` → 先试 `fix-a`(若在 specs 中,即父),否则继续剥 `a`。第一个存在于 specs 中的祖先即父(防护:最多剥 20 层)
- **顶层行** = 非 fix 规格 + orphan fix(任何祖先都不在 specs 中的 fix)
- orphan fix 作为深度 1 的独立树放在**所有顶层树之后**,orphan 标记=true;其下仍可挂更深层的 fix 子规格
- **排序**:顶层(含 orphan 根)按当前排序键排;子行在各自父下也按同一排序键排;`pushTree` 递归展开多层(fix-fix-* 挂 fix-*,fix-* 挂基名)
- **error 子行**:`s.error` 非空时主行后追加 `colspan=8` 的信息子行:`信息` badge + error 文本 + 「清除」按钮(app.js:944-954)
- 行数据缺失(byName 中无)不渲染

---

## 3. 运行记录弹窗(runmodal)

打开来源:时间轴 run 节点「查看运行记录」按钮(带 runId);或时间轴状态节点(带 `{from,to,reason}`,静态内容,无 watch)。

### 拉取与订阅流程(app.js:1596-1672)

1. 打开:标题=runId;清空缓冲;`GET /api/runs/<id>?project=<p>&tail=300`
2. 响应处理:`modalEvents = d.events;modalTotal = d.total_events ?? events.length`
3. `isRunLive(status)` = `status==='running' || status==='empty'`(app.js:1585-1587)
4. live → `POST /api/runs/<id>/watch?project=<p>&cid=<cid>` 订阅;非 live → `DELETE .../watch` 注销
5. 弹窗关闭/切换 run → 注销旧 watch

### SSE 增量(app.js:1618-1635)

- `run_events` 且 `run_id` 匹配:`events.concat(msg.events)`;`total_events = msg.total_events ?? len`
- `msg.reset===true` → 注销 watch + 重新拉完整尾部(重新订阅)
- run 结束(`!isRunLive(msg.status)`)→ 注销 watch

### 渲染规则(app.js:1471-1497)

- **thinking_tokens 合并**(`collapseThinkingTokens`,app.js:1472-1487):连续的 `type==='system' && subtype==='thinking_tokens'` 事件合并为 1 条,首条保留,`_merged` 记条数;渲染时 `system` 事件显示 `（合并 N 条）`(N>1)
- 渲染最后 **300** 条(`events.slice(-300)`)
- `status==='error' && d.error` 时,先渲染 error 事件再渲染普通流
- 尾部显示 `共 <total> 条事件`
- **粘性滚动**(app.js:1589-1594):更新前 `scrollHeight - scrollTop - clientHeight < 80`(距底 80px 内)→ 更新后自动滚到底;用户上翻时不拽回

### 事件渲染(app.js:1418-1469,每类事件的确切输出)

- **assistant**:text 块拼 markdown 渲染(截 8000 字符);tool_use 块 → `🔧 <code>name</code> + JSON.stringify(input).slice(0,600)`;都无 → JSON.stringify(ev).slice(0,300)
- **user**:content 中字符串拼 markdown(截 3000);tool_result 块 → `（错误）` 前缀(is_error)+ content.slice(0,400),错误态加 class
- **tool_use**:`🔧 <code>name</code> + input JSON(600)`
- **tool_result**:is_error → `（错误）`+tool-error class;content.slice(0,400)
- **result**:`🏁 <md(result).slice(0,4000)>（turns: N）`
- **error**:`💥 <error>（exit_code: N）`
- **stderr**:`⚠ <line>`
- **system**:`⚙ 系统: <subtype>（合并 N 条）`
- 未知:JSON.slice(0,300)

### Markdown 渲染管线(app.js:1258-1281)

vendored marked(v18,gfm+breaks),自定义 renderer:
- **html 渲染器一律转义原始 HTML**(防注入):`__r.html = (tok) => esc(tok.text)`
- **link 仅放行 http/https/mailto**,其余输出转义文本;合法链接 `<a href target=_blank rel=noopener>`
- parse 失败 → 整体 esc 纯文本兜底

---

## 4. Admin 处置弹窗(adminrec)状态机

状态变量(app.js:1682-1684):`modalAdminSpec = {project, spec, inProgress} | null`(null=关闭)、`modalAdminRunId`(null=等待态)、`modalAdminPoll`(5s 轮询定时器)。

### 打开(app.js:1702-1727)

来源:SPEC 行右键菜单「呼叫 Admin 介入」:
1. `POST /api/spec-admin-invoke?project&spec`
2. **2xx** → `openAdminInvokeDialog(project, spec, inProgress=false)`;**409** → `inProgress=true`,弹窗顶部显示「ℹ 已有处置进行中」提示行;**其他错误** → 仅 toast,不开弹窗
3. 弹窗打开:标题=`<spec> 处置过程`;状态行=`waiting`(⏳ 等待 Administrator 开始处置);body=「等待 Administrator 开始处置…」
4. 立即调 `fetchAdminActivities(project, spec)` 解析;同时 `startAdminPoll()`(5s 兜底轮询)

### 状态转移图

```
[打开] → WAITING(等待态)
   │   ├─ fetchAdminActivities:GET /api/admin-activities?project&spec
   │   │    取 activities[0](已按置顶+时间倒序,首条=优先 pending 其次最新 final)
   │   │    → 状态行 = adminDispPill(latest.status || latest.result) 或 waiting
   │   │    → 若 latest.admin_run_id 存在 → RESOLVED
   │   └─ 5s 兜底轮询重复上述解析(仅 WAITING 态)
WAITING → RESOLVED(admin_run_id 解析成功)
   │    ├─ modalAdminRunId !== runId 才切换;切换时注销旧 watch
   │    ├─ 停止兜底轮询;状态行 = running
   │    └─ fetchAdminRunTail:GET /api/runs/<run_id>?project&tail=300
   │         ├─ live → 状态行=running;注册 watch;渲染事件流
   │         ├─ 非 live → 状态行=adminDispPill(d.status);注销 watch
   │         └─ 404(run 文件被清理)→ 回退 WAITING(清空 runId、重开轮询、重新解析)
RESOLVED → 增量:run_events 且 run_id 匹配
   │      ├─ reset → 注销+重拉尾部
   │      ├─ live → 状态行=running;持续追加
   │      └─ 非 live → 状态行=adminDispPill(msg.status || 'resolved');注销 watch
任意态 → [关闭]:注销 watch + 停轮询 + 清空全部状态
```

### 状态行 pill 映射(ADMIN_DISP_META,app.js:1687-1696)

`pending=⏳处置中 / running=🔨处置中 / resolved=✅已完成 / partially-resolved=⚠️部分解决 / escalated=🚨已升级 / failed=❌失败 / interrupted=⛔已中断 / waiting=⏳等待 Administrator 开始处置`。

### 关键时序细节

- `admin_activities` SSE 事件:弹窗打开且 `msg.project===modalAdminSpec.project` → 重新 fetchAdminActivities(状态行随广播刷新);解析端点失败且尚未定位 run → 状态行回 waiting,**不报错**
- SSE 断线重连:admin 弹窗仍开 → 有 runId 则用新 cid 重订阅 + 重拉解析;等待态则重拉解析
- run 切换(runId 变化):注销旧 watch 再拉新 run
- 等待态兜底轮询:**仅在弹窗打开且 runId 为 null 时进行**,任何时刻解析成功即停
- 弹窗关闭后到达的响应一律丢弃(检查 modalAdminSpec 是否为 null)

---

## 5. Why 提示与 error 清除

### hover Why 提示(app.js:1283-1415)

- 端点:`GET /api/spec-doc?project=<p>&spec=<s>&doc=proposal`
- 触发:hover `.spec-name-cell` 200ms 后;数据懒加载 + 三态缓存(键 `project│spec`,值 `{status: loading|done|empty, promise?, html}`):
  - `found:false` 或 proposal 无 `## Why` 段 → **负缓存**(empty),不再请求
  - 请求失败**不缓存**,下次 hover 重试
  - loading 态复用进行中的 promise
- Why 段提取(`extractWhy`,app.js:1291-1307):匹配 `/^##\s+why\s*$/i` 行到下一个 `^##\s` 行之间,trim 后为空视为无;提取结果是 markdown 子串,走 mdRender 渲染
- 交互:点击/滚动立即关闭;视口翻转定位(下方放不下翻上方,右溢出左移)
- v2 形态可变:设计已改为「点击懒加载 tooltip API」,但**缓存与负缓存语义应保留**

### error 清除(app.js:962-988)

- `POST /api/spec-error-clear?project=<p>&spec=<s>`
- 成功:立即从 DOM 移除该行信息子行(不等 SSE),再触发一次列表刷新兜底
- 失败:按钮禁用 + 「清除失败」文案 2s 后恢复

---

## 6. 配置页数据流

### 5 个页签与值域

1. **🤖 LLM Provider**(tab=llm-provider):providers 卡片列表。字段:name/baseurl/apikey(password)/model/env(KV 行,**仅收键值都非空的行**)。可增删卡片
2. **🧩 Agent 模型分配**(tab=agent-models):5 角色(implementer=Implementer(执行)/planner-plan=Planner Plan(生成场景)/planner-judge=Planner Judge(判定结果)/verifier=Verifier(旧版验证)/administrator=Administrator(运维))。每角色:角色级默认模型(独立输入框)+ 可排序多行链(每行:provider 下拉 + model 输入 + 上移/下移/删除)
3. **⚡ 并行度设置**(tab=parallel):max_concurrent(min1,默认2)/ max_turns(min1,默认300)/ run_timeout_seconds(min60,step60,默认3600)/ daily_run_limit(min0,默认50)
4. **🚪 审批模式**(tab=approve):radio manual(默认)/auto
5. **🎨 界面风格**(tab=theme):localStorage(fenix.theme),**不进入保存路径**

### 链编辑器数据规则(app.js:2215-2291)

- 载入:`models[at.key]` 规范化为 `{model: 角色级缺省, provider: [{provider, model}]}`;provider 形态归一化(str→`{provider: str, model: ''}`),过滤 provider 为空的行
- **回显保真**:行绑定 provider 名不在 providers 列表时,仍把该值注入 select 选项(否则回显为空)
- 行 model 输入框占位:`roleModel ? '留空用角色级缺省 <roleModel>' : '模型名（留空用角色级缺省）'`
- 链序=DOM 顺序;上移/下移交换 DOM 位置;空行(未选 provider)在收集时丢弃

### collectConfigData(app.js:2522-2591)

输出 payload:
```jsonc
{
  "llm": {"providers": [{name, baseurl, apikey, model, env?}]},   // 空值字段省略;env 空对象省略
  "agents": {"models": {"<role>": {"provider": [{provider, model}]}
                                  (+ "model": roleModel 当非空)},
             "max_concurrent": N, "max_turns": N, "run_timeout_seconds": N, "daily_run_limit": N},
  "gates": {"approve_mode": "manual|auto"}
}
```
- **数字回退**(`numOr`,app.js:2558-2565):输入空/NaN → 回退 `lastConfigData.agents.<key>`(已加载快照);快照也没有才用领域默认(2/300/3600/50)。防止只编辑一个字段时把其它字段重置为硬编码默认
- 角色仅在有链行或角色级 model 非空时输出

### 保存校验(app.js:2593-2635)

对每个有链行的角色:每行满足 `model || roleDefault || providerDefaults[provider]`(provider 的默认模型)其一,否则该角色缺模型。存在缺失 → 阻止保存,横幅错误:`❌ 保存失败：<角色名列表> 无可用模型（角色级缺省与逐行模型均为空，且 Provider 也无默认模型）。`

### 保存流程(app.js:2593-2701)

- URL:项目模式 `POST /api/config?project=<p>`,用户模式 `POST /api/config`
- 成功:横幅 `✅ 配置已保存并写入 <path>，重启 daemon 后生效`;**静默刷新** lastConfigData 快照(不重绘表单/横幅);横幅 4s 后自动隐藏
- 失败:横幅 `❌ 保存失败：<error>`
- 视图区分:scope=user 时标题「配置管理 · 用户级」+「继承自用户级」badge(sources[key]==='user');raw_exists=false 显示「⚠ 配置文件尚不存在,保存后创建」

### tab 深链

`#config/<project>?tab=<tabid>` 或 `#config=<project>&tab=<tabid>`;tab 值域:`llm-provider|agent-models|parallel|approve|theme`。进入页面直接激活对应页签。

---

## 7. 告警横幅与运维记录

### 告警横幅(app.js:272-368)

- 数据:`GET /api/alerts`(跨项目聚合);`total_unhandled===0` → 隐藏
- 条数=`total_unhandled`;最高严重度 pill(critical>major>minor);摘要=最新一条(顶部)的 `[project] description||action_taken`
- **默认展开**列表;重建时保留展开状态
- 每条:severity pill + project/spec 徽标 + 时间 + 描述 + 证据/处置/建议 + 「标记已处理」按钮(`POST /api/alerts/<id>/handled?project=<p>`,需 project+id 均非空)
- 顶部:「清理所有事件」按钮(confirm 后 `POST /api/alerts/clear`)
- SSE `alerts` → 重拉横幅;activities 视图同时重拉

### 运维记录页(app.js:370-493)

- 数据:`GET /api/admin-activities[?project=<p>]`
- 跨项目模式:页签栏 = 「全部」+ 各项目名(按名排序,带条数);页签状态跨刷新保持;页签失效(项目消失)回退「全部」
  - 「全部」:按项目分段(section),每段标题 `<name> N 条`
  - 某项目:仅该项目卡片
- 单项目模式:标题「运维记录 · <project>」,副标题 `N 条 Administrator 处置记录 · 未处理升级置顶高亮`
- 卡片(app.js:462-492):时间 + project/spec/signal_type 徽标 + result pill(RESULT_META:resolved=✅已解决/partially-resolved=⚠️部分解决/escalated=🚨已升级/failed=❌失败/pending=⏳处置中)+ `handled===false` 时「需人工决策」pill + 「标记已处理」按钮(用 escalation_id 调 handled 端点);body 优先 summary,无 summary 降级 `（无叙述总结）处置：… · 结果：…`
- SSE `admin_activities` → activities 视图节流重拉

---

## 8. 路由与深链

hash 路由(app.js:95-125,decodeURIComponent 后 split):

| hash 模式 | 视图 | 解析 |
|---|---|---|
| `#overview`(或空/未知) | overview | 默认 |
| `#project/<name>` | project | project=name |
| `#spec/<project>/<spec>` | spec | 都 encode |
| `#config[/<project>][?tab=<t>]`、`#config=<project>[&tab=<t>]` | config | 等号形式兼容;tab 正则 `/[?&]tab=([\w-]+)/`,project 需剥离 tab 参数 |
| `#activities[/<project>]` | activities | 无 project = 跨项目聚合 |

行为细节:
- `nav(hash)`:同 hash 也强制 route()
- route():更新顶栏 active 态 → load 当前视图数据 → loadAlerts()
- 顶栏项目下拉:一次拉 /api/projects 填充(选项名后缀「(自动)」= discovered);切换项目保持视图类型(spec 详情降级到该项目 SPEC 列表;project/spec/overview → project 视图)
- 切换视图时保持滚动位置(load 回调 scrollTo)
- load 带 seq 防竞态(过期响应丢弃)
- API 错误 → 错误横幅 + 保留上次 HTML 缓存(`main._lastHtml`)

---

## 9. v2 需保留的非功能性约定

- **toast 时长**:成功 5s / 错误 6s(app.js:84 注释:菜单关闭等交互占约 3s,过短会被断言捕获前移除)——Playwright 验收依赖此窗口
- **光标/交互语义**:SPEC 行点击跳详情(事件内 stopPropagation 的按钮除外:文档链接/清除按钮/卡片操作区)
- **删除 SPEC 的乐观 DOM**:老版成功后立即移行,SSE 最终一致;v2 用 reload 实现等价效果即可,但**不得在重拉前让已删行继续可见超过一次刷新周期**
- **主题**:v2 首版仅 dark(embed theme 参数),localStorage 机制不再需要
- **project= 参数**:所有 spec 级端点都要求 `?project=`(get_run_events/watch/spec-doc/error-clear/priority/delete/admin-invoke/config)
- **encodeURIComponent**:所有拼 URL 的 project/spec/run_id 参数(现存代码统一处理,含中文/特殊字符的 spec 名)
- **tail 上限**:run tail 服务端 clamp 到 2000;前端固定 300
- **自动刷新豁免**:config 视图编辑中不整页重绘(v2 中表单编辑期间的 SSE reload 需要等效豁免或仅在保存后 reload)
