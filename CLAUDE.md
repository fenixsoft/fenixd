# CLAUDE.md — Fenixd 项目约定

## 临时文件与测试截图

测试生成的截图和其他临时文件，放到 `.history` 目录（已在 .gitignore 中排除，不提交）。

## 知识消费纪律（index-first）

- 接手排查 / 立项 / 实现类任务时，先读 `spec/knowledge/index.md`（知识真相源总目录，按能力域组织）判断相关能力域；命中相关域则下钻 `spec/knowledge/domains/<域>/_domain.md` 与相关能力页后再动手；未命中可跳过，不要为走流程而全量阅读。项目尚无 `spec/knowledge/` 目录时静默跳过。
- 值得沉淀的排查 / 立项结论投递 `spec/knowledge/_inbox/`（回填纪律预告：该目录与消费链路由 SPEC `add-knowledge-inbox-pipeline` 提供）——目录尚不存在时先不投递，也不要自行创建。

## 原型访问地址（FRP 隧道）

- fenix-prototype 生成原型交付评审时，对外访问地址一律使用 `http://home.icyfenix.cn:18787` 代替 `http://127.0.0.1:8787`（frp 隧道透传到本机 dashboard 8787，**纯 HTTP 无 TLS，禁用 https**；路径与 `?proto_round=N` 参数不变），用户免端口转发直接访问。`proto_serve.py` 输出的 127.0.0.1 地址仅作服务器本机自检，MUST NOT 直接交给用户；交付前用该公网地址端到端探测一次（HTTP 200）。