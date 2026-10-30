# 设计：distill-model-name-fallback

## 落点

1. core/knowledge.py:1470-1528（_spawn_and_wait；行号为评审实测，原稿叙事行号已漂移）：SpawnRequest 增加 model 实参，取**新增配置键 `knowledge.model`**——蒸馏车道现状无任何模型配置键（grep `distill_model`/`DISTILL.*MODEL` 仅命中 RUN_TIMEOUT_SECONDS），原稿「沿用既有模型配置」前提不成立；ConfigLoader 增键并按仓库「回退必告警」哲学：未配置/非法/空值回退现行为不传名并告警；:1514-1527 非零退出分支加 stderr 判别（pattern 对照 core/agent_runner/provider_circuit.py:86-89 UNRECOGNIZED_MODEL_TEXT_PATTERNS 裸子串形态，只读复用），命中且未显式传 model（见 R2 收窄）才以裸模型名单次重试。
2. core/knowledge.py:665-686（_register_todo_retry）/1530-1561（_give_up；实测行号）：新增台账龄期扫描助手（解析 todo.md 重试行日期节，与 _register_todo_retry 既有「登记时刻由日期节承载」口径一致），超 24 小时未重试发每日一条提醒。通道指定 AdminStore.append(kind=SIGNAL)（既有先例 core/code_fix.py:3434-3471 _write_switch_cooldown_alert），不发明新通道；同日幂等以 daemon 进程内当日标记承载（daemon 常驻即满足每日至多一条，重启重发至多一条可接受）；扫描挂 daemon 既有周期维护循环触发（R3），dashboard --serve 不接入。
3. core/agent_runner/provider_circuit.py：只读引用其判别 pattern 常量，不改语义。
4. 测试：tests/test_knowledge_distill_resume.py（拒识命中且未显式传名→单次重试成功；重试仍失败只登一次台账；显式传名仍被拒→不重试直接 give_up 且台账注明生效模型名；显式 model 透传断言；knowledge.model 缺省/空值回退不传名并告警；龄期提醒触发与同日幂等）。

## 风险与权衡

- 重试上界一轮 run（RUN_TIMEOUT_SECONDS=1800，core/knowledge.py:137，有界），不会放大失败风暴；但 unrecognized_model 是确定性模型失败（provider_circuit.py:78-85 既有结论：同一模型名再试必然再拒），显式传名落地后重试恒为同因重试——故重试收窄为「首次未显式传名」才触发（R2），传名仍被拒直接 give_up。
- 显式传名后若配置值为空需回退现行为（不传）并告警，避免静默空参。
- 宿主 settings 毒化是环境事实（实测 /root/.claude/settings.json ANTHROPIC_DEFAULT_SONNET/OPUS_MODEL 均为 glm-5.3-flash[1M]），仓内以显式传名隔离；运维侧修复（去掉 [1M] 后缀）作为部署说明记录，不入 repo 代码。显式传名不消除网关侧裸名拒识形态（2026-10-29 活日志 :7935 code-fix 车道裸名 glm-5.3-flash 仍被拒），give_up 台账路径仍须保留。