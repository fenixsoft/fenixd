# 验证预检门
<!-- knowledge: capability=verify-preflight-gate rev=1 sources=spec/archive/2026-09-18-add-verify-preflight-gate -->

场景执行前的两道机械预检与启动错误留痕：serve 入口存在性 spawn 前拦截、契约 mtime 变化后消费期轻量自证、boot.log 进告警证据。

## 现行规则

- serve 命令入口存在性预检：`serve.kind=command` 的两条路径（serving worktree 与主树兜底）在启动 serve.cmd 进程前机械解析脚本入口路径并校验存在性——可执行名为 `node`（含 npx/tsx/bun 等脚本型运行时）时，第一个非 flag 参数视为入口路径，按 cmd 的 cwd 解析为绝对路径。
- 入口缺失即失败：入口文件不存在时不 spawn、不执行任何验证场景，验证链路立即失败，错误信息含缺失路径全文与同目录确定性候选（如同名 `.js` 存在时提示），并产生 `verify_contract_missing` 信号（description 注明「入口存在性预检失败」）呼叫 Administrator；report.json 不产生、场景执行数为 0。
- 保守放行：无法解析出入口路径（管道、`&&` 复合命令、shell 内建等）时跳过预检放行，走既有启动与探活路径，零误杀；入口存在时预检零开销放行。
- 契约消费期轻量自证：验证管线消费契约前按 `.fenix/verify.yaml` mtime 判定——mtime 晚于上次自证记录（per-project 持久化于 `.fenix/verify-serving/contract_selfcheck.json`）时执行，否则跳过。自证内容为 serve 段合法性（kind 枚举、static 模式 root 存在、command 模式 cmd 非空）与 ready 探针鉴别力自检（复用 `probe_ready`）；不重复执行 prepare 构建。自证失败按契约错误处理（`verify_contract_missing` 信号 + 验证失败），不进入场景执行；自证通过记录 mtime 后放行，后续轮次零开销。
- boot.log 落盘与进证据：`_ensure_app_reachable` 兜底 spawn 将子进程 stderr 捕获至 `.fenix/verify-serving/<spec>-boot.log`（覆盖写）；探活最终失败时 blocked 告警的 error/evidence 附 boot.log 尾部（≤2KB）；实例正常启动时 boot.log 照常落盘不影响判定。

## 溯源

- 2026-09-18 add-verify-preflight-gate（spec/archive/2026-09-18-add-verify-preflight-gate） — 新增 spawn 前入口存在性预检、契约 mtime 变化后的消费期轻量自证与 boot.log 证据链（「Cannot find module」类启动即死错误此前对 admin 不可读，浪费整轮探活超时）
