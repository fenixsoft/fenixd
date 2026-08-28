# Tasks: improve-failover-model-mapping-ui

## 1. 链模型映射（spec-chain-model-mapping，design D1/D2/D3）

- [x] 1.1 yaml 加载规范化：provider 元素 str|对象 → (provider, model|None) 内部二元组；元素模型解析顺序 元素>角色级>providers 条目；补解析矩阵单测（str/list/对象/混合/三级回退/全空）
- [x] 1.2 _validate_agent_models 规则替换：删角色级非空要求，改逐元素可解析检查（ERROR 含元素下标，不阻塞）；补单测（缺角色级通过 / 下标注明 / 空链通过）
- [x] 1.3 get_agent_model_assignment 输出逐元素 (provider, model)；agent_runner provider_marker 含 model；switch 日志 model_changed 留痕；补单测（跨模型切换两例 / 同模型无标记）

## 2. Dashboard 后端（spec-dashboard-chain-editor，design D4/D5）

- [ ] 2.1 config GET 接口对 agents.models.<role>.provider 输出规范化链 JSON（含解析后 model 供回显）；补往返单测（三形态读取一致）
- [ ] 2.2 config_patch 保存路径：表单整体替换角色条目、序列化规则（单行无元素 model→str，否则数组）、应用前校验失败返回 400 不落盘；补单测（退化字符串 / 400 拒绝 / 已有链不被覆写）

## 3. Dashboard 前端（app.js）

- [ ] 3.1 分配区改造为可排序行编辑器（provider 下拉 + model 输入 + 增删/上移/下移），加载回显三形态；手动冒烟：读-改-存-重载一致
- [ ] 3.2 保存对接 2.2 序列化与 400 错误 toast；手动冒烟：非法 provider 名保存被拦截且原配置完好

## 4. 回归与核验

- [ ] 4.1 全量 pytest 通过（重点 test_agent_runner、config、dashboard data 相关及新增用例），无既有用例回归
- [ ] 4.2 对照两个 capability spec 的全部 Scenario 逐条核对实现覆盖并记录结论
- [ ] 4.3 config.yaml 增补三种形态示例的文档注释（str / 字符串数组 / 对象数组）
