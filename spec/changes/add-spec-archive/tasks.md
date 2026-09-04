# add-spec-archive — Tasks

## 1. 后端归档能力

- [x] 1.1 `data.py` 新增 `archive_spec(project_root, spec_name)`：终态校验（done/pushed，否则返回错误）、`shutil.move` 到 `spec/archive/YYYY-MM-DD-<name>/`（目标存在报错不覆盖，与 fenix_archive.py 命名规则一致）、返回 `{ok, from, to, error}`；目录缺失返回 found=false
- [x] 1.2 `data.py::spec_summary` 增加 `archived` 字段：STATE.md 有条目且 `spec/changes/<name>/` 不存在 → true；同步检查读文档/任务进度的路径对目录缺失容错（返回空进度不抛异常）
- [x] 1.3 `server.py` 新增 `POST /api/spec-archive` 端点（对齐 spec-freeze 的参数与错误处理），归档成功发项目活动事件（归档动作 from→to）
- [x] 1.4 单测：归档终态成功/非终态拒绝/目标已存在不覆盖/不存在 spec 报错/archived 判定（目录存在、目录缺失、CLI 归档后条目保留）

## 2. 前端手动归档与归档查询

- [x] 2.1 `services/dashboard.ts` 新增 `archiveSpec(project, spec)` 调用新端点
- [x] 2.2 `list.tsx::specMenuItems` 「冻结 Spec」之后插入「归档 Spec」项（done/pushed 启用，其余禁用）；新增确认弹窗 + 成功提示 + 刷新列表；已归档视图下菜单收敛（去掉优先级/冻结/归档项）
- [x] 2.3 过滤区「全部/仅需求/仅问题」右侧新增归档切换 Radio.Group（未归档/已归档，默认未归档），按 `archived` 字段客户端过滤（与 status/type 过滤同层）
- [x] 2.4 v3 构建（`cd core/dashboard/static/v3 && npm run build`）并经 dashboard 手动验证：终态归档成功、非终态置灰、切换视图、CLI skill 归档后界面可见

## 3. 自动归档配置

- [x] 3.1 `core/config.py` 支持 `archive.auto_threshold` 校验（非负整数，非法记日志回落默认 50）
- [x] 3.2 `MiscSettingsPanel` 新增「自动归档阈值」InputNumber（min=0，默认 50，说明含 0=禁用），保存写入配置；非负整数校验
- [x] 3.3 单测：配置校验合法/非法回落、深合并用户级/项目级优先级

## 4. daemon 自动归档执行

- [x] 4.1 归档检查逻辑（data.py 或独立模块）：遍历项目 → 读有效阈值 → 统计终态未归档（done/pushed 且 changes/<name>/ 存在）→ 超 0 且超阈值按 `updated` 升序归档至达标；单条失败跳过并记日志
- [x] 4.2 核对并修正所有「按 STATE.md 条目枚举 changes 目录」的既有路径（pm_engine 调度扫描、verify snapshot 等）对 archived 条目（目录缺失）跳过，列入 diff 自查
- [x] 4.3 `fenixd.py` 主循环挂 `archive_check_ts` 独立计时（300s），异常捕获记日志不中断主循环
- [x] 4.4 单测：超阈值归档最久的/未超阈值不动/0 禁用/单条失败不阻塞/非终态与已归档不计入
- [x] 4.5 集成验证：测试项目构造超阈值终态 SPEC → 300s 内自动归档 → 活动事件出现归档记录；热更新改阈值立即生效

## 验证修复（第 1 轮失败）

- [x] 先复核失败有效性：逐条核对 `spec/changes/add-spec-archive/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [x] 修复后重跑验证确认通过
