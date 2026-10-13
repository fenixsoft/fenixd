
## 2026-10-13
### 知识真相源
- [ ] knowledge-distill 重试：归档 2026-10-13-evo-admin-orphan-effect-evidence-expansion — run 失败: claude 进程非零退出（exit=1）；stderr 尾部: [claude-code:unrecognized_model] {"model":"glm-5.3-flash[1M]","query_source":"sdk"}
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 13 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

### dsh 真实全链验收执行请求（dsh-primary-acceptance-switch，人工队列）
- **请求**：执行 dsh 通道真实全链验收（真实模型调用，属人工运维门控动作，agent 仅完成预演与登记，实际执行由用户发起——参照 restart_request 信号范式）
- **执行命令**：`python3 bin/dsh_acceptance.py accept --go`（先跑 `python3 bin/dsh_acceptance.py accept` 预演确认自检全绿）
- **前置条件**：① dsh 在 PATH 且版本在白名单（`0.2.0-rc.2`）；② Bundle 已挂载（`dsh --profile fenix --dump-config` 可见 headless-runner 段，详见 dsh-bundle/README.md 安装段）；③ `llm.providers` 至少一项 baseurl+apikey 齐备；④ claude CLI 在 PATH（基线车道；可 `--no-claude-baseline` 跳过）；⑤ 避开已知 429/断供窗口（每日 04:30 前后）
- **预计耗时**：4 车道（claude 基线 implementer + dsh implementer/verifier/judge）× 单车道 900s 上限，实测通常 10 分钟内
- **产物**：`.fenix/verify-evidence/dsh-primary-acceptance-switch/dsh-acceptance-real-*`（五段证据报告 + 决策申请段）；报告模板见 docs/help/dsh-harness-runbook.md 第五节
- **agent 预演记录**：2026-10-13 accept 预演自检全绿（5/5 项：dsh 可用 / provider 链凭据 7 个 / dsh 健康门通过 / claude CLI 命中 / 临时夹具可写），dry-run 计划输出正常，全程零真实模型调用
- **裁决提醒**：验收报告第六节「默认值翻转 claude→dsh」为用户裁决项，翻转属后续一次性微变更，不在自动化链路
