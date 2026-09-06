## Context

behavior.md §6 权威:GET /api/config 结构(user/project 级区分)、llm 空对象兜底(adaptConfig 已实现)、链编辑器结构(可排序多行+角色级缺省)、collectConfigData 的合并回退语义(三级回退,v2 由 buildConfigPayload 承担)、POST /api/config 请求体。全局约束:成功 toast 5s 窗口。

## Goals / Non-Goals

- Goals: 加载回显、修改保存、回读一致;链校验(validateChain)拦截不完整链;编辑期间 SSE 不打断
- Non-Goals: 主题切换(v2 首版仅 dark,页签渲染只读说明,设计 §4)

## Decisions

- **初始值经 service 预载**:config-loader adaptor 调 adaptConfig 并写 window.__configSnapshot;form data 绑定 service 数据域
- **提交合并**:api.requestAdaptor 内调 buildConfigPayload(api.data, window.__configSnapshot, defaults)——表单空/NaN 由快照回退(计划 Task 10 Step 3)
- **编辑豁免**:config 页不挂 onEvent sse:* 监听即可豁免;但桥仍在广播——确认 reload 动作只由监听方触发,故无需桥侧改动
- **链编辑器**:input-array sortable,每行角色 select+模型名;validate 调 window.Adapters.validateChain

## Risks / Trade-offs

- AMIS form 提交数据域与 api.data 的合并方式(requestAdaptor 可用性)需实测;若受限退路:submit 事件动作里先 custom script 组 payload 再 ajax
