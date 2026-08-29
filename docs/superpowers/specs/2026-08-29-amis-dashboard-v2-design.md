# Dashboard AMIS 重构设计(app.js → AMIS 6.13.0 JSON DSL)

日期:2026-08-29
状态:已与用户逐节确认

## 1. 背景与目标

`core/dashboard/static/app.js`(2946 行)以字符串模板 + morphdom + 10 余个全局变量实现全部前端,扩展成本高。目标:用 AMIS 6.13.0 的 JSON DSL 重构全部功能,主要内容以 JSON 表达,仅 AMIS 不支持的部分嵌入 HTML+JS 补全。

已确认的关键决策:

| 决策点 | 结论 |
|---|---|
| SSE 通道 | 保留现有 `/api/stream`,新增桥接层触发 AMIS 组件刷新 |
| SDK 引入 | vendor 到 `static/v2/`(零依赖内网工具,不依赖外网) |
| 功能对齐 | 功能等价、形态可变(右键菜单→行内下拉、React 时间轴→AMIS Timeline 等) |
| 验收 | Playwright 自动化验收,全绿后人工过一遍再替换 |
| 并存策略 | 注册 `/v2/` 前缀,老 app.js 保持可用,验收通过后替换 `/` 指向 |

## 2. 架构总览

```
core/dashboard/static/
├── app.js / style.css / vendor/   ← 现状保持不动(主入口)
└── v2/                            ← 新增,纯前端增量
    ├── index.html                 ← 引 sdk.css + sdk.js + app.js + bridge.js
    ├── sdk.js / sdk.css           ← AMIS 6.13.0 官方构建产物
    ├── app.js                     ← hash 路由 env + embed 初始化
    ├── adapters.js                ← responseAdaptor 数据适配纯函数
    ├── bridge.js                  ← SSE 桥 custom 组件
    └── pages/                     ← 每视图一个 JSON 文件
        ├── overview.json          ← 概览
        ├── project.json           ← 项目 SPEC 列表
        ├── spec-detail.json       ← SPEC 详情
        ├── config.json            ← 配置页
        └── activities.json        ← 运维记录
```

- **后端零改动**:server.py:231 的静态 fallback(含防穿越校验)自动服务 `/v2/*`;现有 `/api/*` 全部复用,响应用 AMIS `responseAdaptor` 适配。
- **入口隔离**:`/` 仍是老 app.js,`/v2/` 是新版。替换 = 把 `/` 指向 v2 index 的单独小提交。
- **hash 路由**:JSSDK 默认 pathname 路由;移植官方 `examples/app/index.jsx` 的 createHashHistory + path-to-regexp 示例(约 100 行),支持参数路由 `/spec/:project/:name`、`/config/:project`。
- **config 页签深链**:tabs `defaultKey: "${query.tab}"` 从 URL query 读。

## 3. SSE 桥与数据流

```
EventSource /api/stream ──► bridge.js(App 壳级 custom,常驻)
                              │ 按 evt.type 映射广播(500ms 节流,移植自老 app.js)
                              ▼
        sse:state / sse:detail / sse:alerts / sse:refresh / sse:admin_activities
                              │ actionType: broadcast(跨页面、跨弹窗可达;renderer-event.ts 对 broadcast 不校验 scoped)
                              ▼
        各视图 JSON 声明 onEvent 监听 → actionType: reload → 按 componentId 重拉 API
```

- 桥组件必须放 **App 壳级**(header 或 asideBefore):页面切换会销毁旧页面(App.tsx 以 `key: activePage.id` 重新 render),壳级才不随路由反复重建 EventSource。
- 低频视图的 SSE 事件仅触发 reload,不做前端增量合并;增量逻辑保留在服务端 API 响应中。
- **例外**:run 事件流弹窗不走路由刷新,独立 custom 组件自管 EventSource + watch 订阅。

参考语法(源码佐证:BroadcastAction.ts:51、renderer-event.ts:455-460):

```js
// bridge.js — App 壳级 custom 组件
{
  type: 'custom',
  onMount: (dom, data, onChange, props) => {
    const es = new EventSource('/api/stream');
    es.onmessage = e => {
      const evt = JSON.parse(e.data);   // 节流后
      props.onAction(e, {
        actionType: 'broadcast',
        args: { eventName: 'sse:' + evt.type },
        data: evt
      }, {});
    };
  }
}
```

```jsonc
// 任意页面 — 按名监听刷新
{
  "type": "service", "id": "spec-list", "api": "/api/specs?project=${params.project}",
  "onEvent": {
    "sse:state":  { "actions": [{ "actionType": "reload", "componentId": "spec-list" }] }
  }
}
```

## 4. 各视图迁移映射

| 现有功能 | v2 实现 | custom |
|---|---|---|
| 概览页(5 统计块 + 项目卡片网格) | Grid + Card;启停删按钮事件动作(http + confirm) | 否 |
| SPEC 列表(8 列,生命周期序 + 关键词/状态/类型过滤) | CRUD sortable columns + filter 表单;生命周期序由 adapters.js 排序后输出 | 否 |
| fix- 前缀树形分组 | responseAdaptor 把扁平 specs 构建 `children` 嵌套树,table 原生树行 | 适配器 |
| 右键菜单(呼叫 Admin/调优先级/删除) | 行内 dropdown 按钮 | 否 |
| error 子行 + hover Why 提示 | 行展开模板 + 点击懒加载 tooltip API(去掉 200ms hover) | 否 |
| SPEC 详情(验证卡/进度/任务清单 + 4 页签) | Tabs;时间轴用 AMIS Timeline;场景结果 Table;Bug Table;截图 Image 网格 + 放大 | 否 |
| 运行记录弹窗(SSE 增量 + 粘性滚动 + token 合并) | Dialog 内嵌 custom 组件 | **是** |
| 文档弹窗(proposal/design/tasks) | Dialog + Tabs `mountOnEnter` 懒加载 | 否 |
| Admin 处置弹窗(等待态→5s 兜底轮询→解析 admin_run_id→实时流→409) | 复用 run 流 custom 组件,状态机并入其中 | 并入 |
| 配置页(LLM Provider 卡片/env KV、Agent 链编辑器、并行度、审批、主题) | Form + input-array(链,可拖拽排序)+ combo(Provider env KV)+ radio/number;链完整性校验用 form validate | 否 |
| 告警横幅(顶部 + 展开列表 + 标记已处理) | 壳级 banner + Dialog 列表 + http 动作 | 否 |
| 运维记录页(时间线 + 跨项目页签) | Timeline + Tabs | 否 |
| 主题切换 | AMIS dark 主题(embed 参数);v2 首版仅 dark | 否 |

## 5. custom JS 清单(全部"AMIS 不支持"的边界)

1. **app.js 中 hash 路由 env**(约 100 行):移植官方示例,含 params/query 解析。
2. **bridge.js SSE 桥**(约 150 行):App 壳级 custom,500ms 节流。
3. **run 流 custom 组件**(约 250 行):运行记录弹窗 + Admin 处置状态机共用。自管 EventSource、POST/DELETE `/api/runs/<id>/watch?cid=`、增量追加、粘性滚动、thinking_tokens 合并、409 处理、关闭清理。
4. **adapters.js 数据适配**(约 100-150 行):API 响应 → AMIS 格式的纯函数(specs 树构建、字段映射、状态排序)。可单独 node 单测。

合计约 600-700 行 JS(老版 2946 行);其余视图全部 JSON 文件。

## 6. 后端 API 复用清单(不新增、不修改)

GET:`/api/projects`、`/api/overview`、`/api/specs?project=`、`/api/specs/<spec>`、`/api/runs/<run_id>?tail=`、`/api/alerts`、`/api/admin-activities`、`/api/config`、`/api/spec-doc?doc=`、`/api/stream`(SSE)、`/screenshots/...`
POST:`/api/config`、`/api/spec-error-clear`、`/api/spec-priority`、`/api/spec-delete`、`/api/spec-admin-invoke`、`/api/alerts/<id>/handled`、`/api/alerts/clear`、`/api/runs/<id>/watch`、`/api/projects/<name>/start|stop`
DELETE:`/api/runs/<id>/watch`、`/api/projects/<name>`

SSE 事件:`hello{cid}`、`state{project,specs,details}`、`detail{spec,data}`、`run_meta`、`run_events{run_id,events[,reset]}`、`refresh`、`alerts`、`admin_activities`(均默认 message 帧,`type` 字段区分;25s 心跳注释帧)。

AMIS 期望的响应格式通过 embed 的 `responseAdaptor` 全局适配(或各 api 处局部适配),不改服务端。

## 7. 测试与验收

- **单测**:adapters.js 纯函数用 node 跑(现有 API 响应样本作 fixture)。
- **Playwright 自动化**(`tests/v2/`):覆盖列表排序过滤、树形分组、详情页签、三弹窗、配置保存回显、告警处理、SSE 实时刷新(触发 watcher 文件变化断言 UI 更新)、深链定位。老版并存期间同一脚本对 `/` 与 `/v2/` 双跑对比关键断言。
- **通过标准**:脚本全绿 → 用户人工过一遍 → 独立小提交把 `/` 指向 v2 → 脚本对 `/` 复跑确认。
- 开发期用 AMIS `schema.json`(sdk 附带)对 JSON 配置做校验,弥补 SDK 模式无 TS 类型的短板。

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| sdk.js 体积(1-2MB)入仓 | 可接受;一次性 vendor,内网工具无 CDN 依赖 |
| JSON 配置错误运行期才暴露 | 开发期 schema.json 校验 + Playwright 全功能回归兜底 |
| run 流大数据量表格性能 | run 流用 custom 组件尾部追加(只保留 tail 300 条),不用 AMIS 表格渲染全量 |
| broadcast 链路故障(升级 AMIS 时) | 链路已有源码级佐证(BroadcastAction.ts / renderer-event.ts);bridge.js 内加连通性自检,事件未触发刷新时 console 显式告警 |
| 验收期发现 AMIS 缺口 | 并存策略兜底:老版不动,缺口可先用形态可变原则调整,实在不行局部 custom 补全 |

## 9. 不做的事(YAGNI)

- 不改后端任何代码(包括 API 响应格式)。
- 不做 light 主题(v2 首版仅 dark)。
- 不迁移 React vendor 中的 marked/React 组件(时间轴换 AMIS Timeline,markdown 用 AMIS 原生渲染)。
- 不保留 hover 200ms 懒加载特技(改点击加载)。
- 不做替换期的双版开关 UI(路径切换即可)。
