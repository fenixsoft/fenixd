# dashboard 配置写面与受控 Radio 的两条工程结论（下载源自选实现，2026-11-28）

## 1. 用户级 config.yaml 写面：未管段也要走 _CONFIG_WRITE_LOCK

- 设置页既有配置写单源：`core/dashboard/data/config_admin.py` `write_config`（公开函数持 `_CONFIG_WRITE_LOCK` 委派 `_*_locked`）——**整文件读-改-写**（mkstemp + `_CONFIG_HEADER_COMMENT` 回写 + fsync + os.replace），只合并受管键白名单，未管段原样保留。
- 新增非受管段写入（本例 `update.mirror`，引擎语义不进设置页受管键体系）时**不得自起 yaml 写面**：必须同锁，否则与设置页保存并发时两个整文件重写互覆盖（读-改-写竞态丢段）。落地形态：`config_admin.write_update_mirror`（公开持锁 → `_write_update_mirror_locked`），守卫与原子写惯例照抄 write_config；校验语义单源留在引擎（`core/self_update.py normalize_mirror`），dashboard 只落盘不重复校验。
- 测试缝：写端 patch `core.dashboard.data.USER_CONFIG_PATH`（门面属性），读端 patch `core.self_update.USER_CONFIG_DIR`——两端指同一 tmp 文件即可做 round-trip。

## 2. 受控 Radio.Group 的「纯 UI 选择态」必须独立 state

- antd Radio.Group 受控 value 从数据推导（本例：命中预设 id→预设 / 非空未命中→custom / 空→official）时，「选自定义但不落盘」的中间态**不能只靠 onChange 设草稿**——value 仍被推导值顶回，Radio 视觉不选中、条件渲染的输入框永远不出现。
- 解法：独立 `customActive` state 并入推导链首位（`customActive ? 'custom' : derived`）；预设点选时 `setCustomActive(false)`。真机 playwright 点选即暴露（snapshot 显示 `[active]` 而非 `[checked]`），纯代码审查难发现。

## 附：本功能的生效链与实测口径

- 生效链：保存 → `~/.fenix/config.yaml update.mirror` → 下一次「一键更新」编排受理时读配置（`self_update_apply` ctx.config.mirror）→ 制品/sha256 下载 URL 前缀替换（API 检查永不走镜像）。无需重启。
- 镜像实测与边界（ghfast.top 推荐/社区镜像易死/无防篡改）见 `docs/help/13-self-update.md`「配置 update.mirror 走大陆镜像」节，不在此重复。
