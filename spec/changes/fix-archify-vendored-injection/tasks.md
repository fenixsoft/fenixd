## Deliverables

```yaml
- path: core/dashboard/routes/architecture_routes.py
  kind: modify
- path: tests/test_dashboard_architecture_api.py
  kind: modify
- path: docs/help/08-dashboard.md
  kind: modify
- path: vendor/archify/SKILL.md
  kind: reference
```

## 1. 后端：vendored 依赖与提示词注入

- [ ] 1.1 `core/dashboard/routes/architecture_routes.py` 删除安装链路：常量
      `SKILL_INSTALL_TIMEOUT_SECONDS`/`ARCHIFY_INSTALL_CMD`/`ARCHIFY_INSTALL_CMD_TEXT`
      与函数 `_archify_skill_paths()`/`_skill_installed()`/`_ensure_archify_skill()`
      及相关注释全部移除；新增 `_vendored_skill_root()`（
      `Path(__file__).resolve().parents[3] / "vendor" / "archify"`，脱离 cwd 依赖）与
      `_skill_ready()`（`SKILL.md` 存在且非空）；生成线程前置完整性检查，缺失/为空判
      `failed` 且错误文案注明 vendored 包缺件属部署损坏、对照 `vendor/archify/
      VENDORED.md` 恢复，MUST NOT 触发任何安装动作
- [ ] 1.2 `_build_prompt()` 注入 vendored SKILL.md 指引原文（读
      `_vendored_skill_root()/SKILL.md`）并前置说明包根绝对路径（指引中相对路径均
      相对包根解析；可用 `node bin/archify.mjs validate …` 本地校验、无网络）；删除
      「请使用 archify skill」措辞；五项形态约束/输出路径/`ARCHIFY_DONE` marker 协议
      保持不变；整条生成链路派生的唯一外部进程为 claude
- [ ] 1.3 更新 `tests/test_dashboard_architecture_api.py`：删除安装超时/安装失败文案
      两类用例，新增——vendored `SKILL.md` 缺失判 `failed` 且文案含「部署损坏」语义
      并未发起安装 / 提示词含 SKILL.md 原文特征与包根路径 / fake Popen 断言全程唯一
      外部进程为 claude（无 npx）；fake Popen 按 `cmd[0]` 分发 + 布防门控先例不变；
      同步清理只服务旧探测/安装机制的测试装置：`_arm_skill()`/`_disarm_skill()` 布防
      与 fake Popen 的 npx 分支（`npx_returncode`/`npx_raise` 参数）随之移除/改写；
      「vendored 缺件」用例经 monkeypatch `_vendored_skill_root()` 指向临时空目录构造，
      MUST NOT 增删/改写真实 `vendor/archify/` 下任何文件
- [ ] 1.4 跑通新用例与既有 `tests/test_dashboard_architecture_api.py` 家族及
      dashboard 路由测试家族（`tests/test_dashboard_*.py`）全绿，记录 pytest 退出码 0
- [ ] 1.5 `docs/help/08-dashboard.md`「项目架构」分面改写：正文「挂 archify skill」
      改为 vendored 注入语义；失败排查段删除自动安装/120 秒/人工安装命令描述，改为
      「skill 随库分发无需安装、生成零网络依赖，报缺件属部署损坏对照 VENDORED.md 恢复」，
      保留 1800 秒超时与 daemon 重启中断说明
- [ ] 1.6 核验 vendored 包在位（spec「上游许可声明随包保留」场景的验收锚点，只读）：
      `vendor/archify/SKILL.md` 存在且非空，`LICENSE`、`THIRD_PARTY_NOTICES.md`、
      `VENDORED.md` 在位，且 VENDORED.md 溯源表含上游仓库、快照 commit、MIT 许可与
      剔除项（`test/`）；MUST NOT 改动包内容
