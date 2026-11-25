# Tasks: add-auto-update

## Deliverables

```yaml
- path: core/self_update.py
  kind: new
- path: core/self_update_apply.py
  kind: new
- path: bin/fenix_update.py
  kind: new
- path: tests/test_self_update.py
  kind: new
- path: tests/test_self_update_apply.py
  kind: new
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/pages/activities/index.tsx
  kind: modify
- path: .fenix/config.user.template.yaml
  kind: modify
- path: docs/install.md
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: docs/help/11-self-update.md
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 更新引擎 core/self_update.py（检查与状态面）

- [ ] 1.1 新建 core/self_update.py：读取用户级 `~/.fenix/config.yaml` 的 `update:` 段（`enabled` 默认 true / `interval_hours` 默认 24 / `mirror` 默认空），复用既有 core/config.py 的配置加载与 deep-merge 行为，键缺失/类型非法时回退默认值且不抛异常
- [ ] 1.2 实现本地版本解析：框架版本读制品根 `VERSION`（缺失 → 形态标记 source，函数返回结构化结果含形态）；dsh-plugins 版本按「制品根 VERSION 优先、否则 link: 目录名 `dsh-plugins-<tag>` 正则解析」双源；版本字符串用手写语义化数值 tuple 比较函数（`1.2.10 > 1.2.9`，非数字段安全降级字符串比较），零第三方依赖
- [ ] 1.3 实现 releases/latest 远端查询：`GET https://api.github.com/repos/<owner>/<repo>/releases/latest`（repo 地址从既有 remote 配置/常量解析），匿名先行，HTTP 401/404 时回退凭证腿（先 gh CLI `gh auth token`，失败再 git credential helper，只读使用、不落盘 token）；单次查询带超时；解析 `tag_name` 与 tar.gz/zip 资产下载 URL，`mirror` 非空时替换下载 URL 前缀（API 域名不替换）
- [ ] 1.4 实现检查编排与状态落盘：结果写 `~/.fenix/update/status.json`（框架与插件各自的当前版本/远端版本/检查时刻/形态/更新可得性/最近失败原因），原子写（临时文件+rename）；并发用同目录 lock 文件（O_EXCL 创建 + 陈锁超时清扫）；每次检查/应用向 `~/.fenix/update/audits.jsonl` 追加一行审计（来源、目标版本、结果、原因、耗时）
- [ ] 1.5 实现周期检查入口 `run_scheduled_check()`：`update.enabled` 为 false 时直接返回；按 status.json 里上次检查时刻与 interval_hours 判断是否到期；检查失败静默记录原因并按退避延迟下次检查，绝不抛出告警
- [ ] 1.6 新建 tests/test_self_update.py：版本解析（含 VERSION 缺失 source 形态、目录名解析、tuple 比较）、双腿查询回退（mock HTTP 层）、status.json 原子写与 lock 互斥、审计追加、enabled=false 跳过；网络交互全部 mock，不触真实 GitHub
- [ ] 1.7 在 daemon 周期任务注册处挂接 `run_scheduled_check()` 只读周期任务（低频、失败自吞、不影响既有调度链），保持 daemon 主链路零行为变化

## 2. 应用编排 core/self_update_apply.py + CLI

- [ ] 2.1 新建 core/self_update_apply.py 分离编排进程入口：提供 `spawn_detached()`（POSIX setsid+double-fork、Windows DETACHED_PROCESS/CREATE_NEW_PROCESS_GROUP）把编排子进程脱离触发方进程组，触发方立即返回「已受理」；编排全程进度/结果写 `~/.fenix/update/status.json`
- [ ] 2.2 实现框架更新编排前半段：下载 release tar.gz（mirror 前缀替换后 URL）+ sha256 校验（资产旁 sha256 文件，缺失则资产名拼 `.sha256` 双形态兼容）→ 解压到框架根同级 `fenixd-update-staging-<ts>/` → 按 scripts/package.sh 既有完整性断言清单逐项核验（VERSION/schemas/vendor/floorplan/dashboard dist/dsh-bundle dist 等，缺一即失败进回滚）
- [ ] 2.3 实现在飞 run 预检与 apply 互斥：编排开始前读 STATE/运行状态，存在在飞 run → 记录状态并拒绝（不换装）；框架级 `~/.fenix/update/apply.lock`（O_EXCL+陈锁清扫）保证并发触发串行化
- [ ] 2.4 实现三段式换装：停 daemon（Linux systemd user unit stop / Windows NSSM stop，服务名经既有 hosting 链解析；未服务化场景跳过停步并在结果注明）→ 旧根 rename `<原名>.old-<ts>` → staging rename 为框架根（路径不变）→ 起 daemon；每步完成即更新 status.json 阶段字段
- [ ] 2.5 实现失败回滚与幂等恢复：任一步失败 → `.old-<ts>` rename 回原名 → 起 daemon → status 记失败与失败阶段；编排启动时检测残留 staging/`.old-*` 目录与状态文件，按记录续走或回滚（幂等恢复）；成功换装后清理上一代 `.old-*`（仅保留一代）
- [ ] 2.6 实现 dsh-plugins 更新编排：下载 zip（同 1.3 双腿鉴权与 mirror）+ sha256 校验 → 解压旧插件目录同级新版本目录 → 枚举 `~/.dsh/profiles/`（排除 desktop）中 link: 指向旧目录的 fenix 插件，逐 profile `dsh plugin remove` + `add link:<新目录>/<插件>` 确定性重注册 → 逐插件核验 exports 指向文件存在；desktop profile 检出降级为结果内文档指引；非 fenix 插件零触碰；插件与框架更新相互独立、单边失败不阻断另一边
- [ ] 2.7 新建 bin/fenix_update.py CLI：`check|apply|status` 三个子命令与引擎共用同一实现（`python3 bin/fenix_update.py check` 同步检查、`apply` 触发分离编排并退出、`status` 打印 status.json 摘要），退出码区分成功/无更新/失败
- [ ] 2.8 新建 tests/test_self_update_apply.py：staging 校验清单断言、三段式与回滚的状态机推进（停/起 daemon 与 rename 全部注入 fake）、在飞 run 拒绝、apply.lock 互斥、幂等恢复（残留 staging/.old 场景）、插件重注册（`dsh` CLI 调用 mock，desktop 排除、非 fenix 插件不碰）、CLI 三子命令退出码；全程临时目录沙箱，不触真实框架根

## 3. Dashboard API 与运维页展示

- [ ] 3.1 core/dashboard/server.py 新增三个路由：`GET /api/update/status`（读 status.json，缺文件返回 never-checked 形态）、`POST /api/update/check`（同步单次检查并回写状态，复用引擎）、`POST /api/update/apply`（apply.lock 冲突或编排进行中返回 409，否则 spawn 分离编排返回受理）；错误路径带可读 message，风格对齐既有路由
- [ ] 3.2 core/dashboard/static/src/pages/activities/index.tsx 运维页新增更新卡（或页签，按既有页签布局密度选择形态）：展示框架/插件当前版本、远端版本、检查时刻、形态标识、「检查更新」「一键更新」按钮、进行中进度与终态（成功/失败+原因）；按钮态与 409 响应联动禁用；SSE/轮询刷新复用页面既有数据加载模式
- [ ] 3.3 手动验证：本地起 dashboard，检查无更新场景（版本持平）、检查失败场景（mock 不可达）、apply 进行中重复触发 409 场景的接口行为与 UI 呈现

## 4. 配置模板与文档

- [ ] 4.1 .fenix/config.user.template.yaml 增补 `update:` 段注释文档（enabled/interval_hours/mirror 三键：含义、默认值、生效方式、关闭后仅停周期检查），保持「只注释不固化默认值」纪律，不改动既有键
- [ ] 4.2 docs/help/09-config.md 全键分组表补 `update:` 三键行（默认值/范围/生效方式）
- [ ] 4.3 docs/install.md 新增「更新」章节：自动更新工作方式（周期检查→提示→确认应用）、CLI 用法（fenix_update.py check|apply|status）、源码形态用户的 git pull 提示、desktop profile 手动半步说明、版本门冲突时的 `allow-version --accept-risk` 指引、回滚副本（`.old-<ts>`）手动恢复方法
- [ ] 4.4 新建 docs/help/11-self-update.md 排障 runbook：status.json 字段解读、常见失败原因（限流/私库无凭证/Windows 占用/在飞 run 拒绝）与处置、私库凭证前置配置、更新中断后半换装态的人工恢复步骤、审计文件位置

## 5. 收尾验证

- [ ] 5.1 跑通新增两个测试文件与既有 tests/ 全量回归无新增失败；`python3 -m py_compile` 通过 core/self_update.py、core/self_update_apply.py、bin/fenix_update.py
- [ ] 5.2 dashboard 前端构建通过（core/dashboard/static/dist 产物重建成功，构建报错清零）
- [ ] 5.3 端到端冒烟（本地 sandbox）：以临时目录伪造旧版本框架根 + 假 release 资产，走 `apply` 全链（下载→校验→换装→回滚注入失败→恢复），status.json 与 audits.jsonl 各阶段记录完整
