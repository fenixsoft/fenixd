# 任务清单：验证契约自主起草（verify-contract-autodraft）

## Deliverables

```yaml
- path: core/verify_contract.py
  kind: modify
- path: bin/fenix_verify_contract.py
  kind: new
- path: core/pm_engine/verification.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: agents/administrator.md
  kind: modify
- path: tests/test_verify_contract_autodraft.py
  kind: new
- path: /root/fenix-desktop/.fenix/verify.yaml
  kind: reference
```

## 1. 契约校验入口（基础设施，先行）

- [ ] 1.1 `core/verify_contract.py` 新增 `validate_contract(project_root)`：接收契约路径或项目根，逐段执行 prepare（复用 `run_prepare_steps`）→ 启 serve（static/command 两形态复用既有 Server 类）→ ready 探针（复用 `probe_ready` 含鉴别力自检）→ 停 serve；返回逐段结果与错误详情，同时输出 `valid` 判定（YAML 可解析且 serve 段合法，供 D4 权限边界判定）
- [ ] 1.2 新增 `bin/fenix_verify_contract.py` 薄 CLI：以项目根（或契约路径）为参数运行同一校验，逐段输出结果，全通退出码 0
- [ ] 1.3 校验单测：健康夹具契约三段全通过（exit 0）；serve root 指向不存在目录、prepare 脚本失败、ready 探针超时各自非 0 退出并输出对应段错误；SPA fallback 无鉴别力探针判失败

## 2. 路由信号化（verification.py）

- [ ] 2.1 `_ensure_app_reachable` 三分支（契约不存在 / `commands.start` 占位符 / 契约解析失败被按无契约回退）改为写 `verify_contract_missing` SIGNAL（`AdminStore.append`，形态参照既有 `verify_uniform_failure`：携带 spec、项目根、场景 kind 集、解析失败标 `parse_error`），note 文案改为「已派发 Administrator 起草验证契约」，不再含「退回 plan 修复」
- [ ] 2.2 回归保护：prepare 失败（构建被实现破坏）路径维持打回 plan 原状，断言不产生 `verify_contract_missing` 信号
- [ ] 2.3 `core/admin_monitor.py` 确认新 signal_type 走既有「未 escalated 记录 → 唤起 Administrator」通用消费路径与同 spec 节流（D2）；若需类型分支（如 recommended_action 定向）则补最小分支
- [ ] 2.4 路由单测：三类契约缺口各自产生信号且 spec 不被打回；信号携带 spec/kind 集/parse_error 标注

## 3. admin 起草职责与手册

- [ ] 3.1 `agents/administrator.md` 权限清单新增「生成/修正 `.fenix/verify.yaml` 验证契约」条目，边界写死：缺失即生成、明显失效可修正且处置留痕（diff 摘要）、可解析且 serve 段合法的有效契约一律不碰
- [ ] 3.2 `agents/administrator.md` 起草流程节：输入源（config `project.type`/`description`、package.json scripts、dist/build 目录探测、`core/verify_contract.py` docstring 模板）→ 草稿写临时路径 → `bin/fenix_verify_contract.py` 自证 → 全通才落位 `.fenix/verify.yaml` → git 提交 → spec 复位 ready → 2 轮上限 → `escalate=true` 附草稿全文与逐段失败证据
- [ ] 3.3 权限边界测试：对含有效契约的夹具运行起草任务入口时以「契约有效、无需起草」结案且文件 mtime/内容不变；失效契约修正路径的处置记录含 diff 摘要

## 4. 收尾链路与存量

- [ ] 4.1 起草收尾演练：夹具项目上验证「契约落盘 → git 提交 → spec 状态复位 ready」全链路可达（复位走既有 state_machine 权限），daemon 重验证使用新契约
- [ ] 4.2 存量补提交：fenix-desktop 项目 admin 手写的 `.fenix/verify.yaml`（reference，跨仓库运维动作）git 提交，作为机制首个实战样本
- [ ] 4.3 全量回归：`tests/test_verify_contract_autodraft.py` 及既有验证链相关测试（test_pm_engine_dispatch_fixes、test_pm_recovery、test_admin）全绿
