"""family.py — FamilyGovernor：fix 家族治理（谱系解析/家族门/waiver/sibling 修复互斥/族谱爆炸信号/bug-found 打回与人工升级）（refactor-core-packages 阶段 4）。

无状态组件：SPEC 状态全部经门面回引 self._pm.state_machine 落在
STATE.md（design D3 规则 3），本组件不持有实例状态。

"""

from typing import Optional
import json
import os
import re
import sys
import tempfile

# ── 原地打回升级阈值（inplace-bug-repair D2）────────────────────
# _verify_fail_rounds 达到此值时冻结为 blocked，停止自动修复，等待人工裁决。
# 模块常量，不进 config（避免触发「配置项必须带 Dashboard 界面」约束）。
MAX_VERIFY_FAIL_ROUNDS = 3

# fix SPEC 的「终态」状态集：_resolve_fix_spec_name 的递归派生判定与
# _same_root_siblings 的家族宽度/兄弟互斥筛选共用（code-review item
# 757e05f354fd：两处各写字面量后口径漂移——verified 的同根兄弟既被宽度门
# 计为活跃成员（已收敛家族仍可能被 family_explosion 误拦）、又被继续加前缀
# 派生新子代，对同一状态给出相反的在飞判断），抽公共常量防再分叉。
_FIX_SPEC_TERMINAL = ("done", "verified", "pushed")

# fix SPEC 的「在途或终态」状态集：模板写入守卫与幂等重置守卫共用（防两处
# 逐字重复后新增状态漏改导致行为分叉）。与上述状态集的包含关系：本集合 ⊇
# _FIX_SPEC_TERMINAL ∪ 进行中集（testing/implementing），另含
# implemented/blocked——同样不重写模板、不重置。
_FIX_SPEC_IN_FLIGHT_OR_TERMINAL = (
    "implementing",
    "testing",
    "implemented",
    "verified",
    "done",
    "pushed",
    "blocked",
)


class FamilyGovernor:
    """fix 家族治理组件（门面 PMEngine 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

    def _resolve_fix_spec_name(self, spec_name: str):
        """确定本轮 bug 应使用的 fix SPEC 名称。

        规则：
        - fix-{spec} 不存在，或处于可重置状态（drafted/ready/implemented/bug-found）
          → 返回该名称（复用）
        - fix-{spec} 已终态完成（done/verified/pushed）
          → 递归加 fix- 前缀（fix-fix-{spec}、fix-fix-fix-{spec}...），生成新一轮修复
        - fix-{spec} 处于进行中（testing/implementing）
          → 返回 None（重复派发竞态，跳过）
        - 其余任意状态（含 blocked 等）同样复用名称，由调用方幂等守卫决定是否重置
        """
        candidate = f"fix-{spec_name}"
        while True:
            existing = self._pm.state_machine.read_one(candidate)
            if existing is None:
                return candidate
            status = existing.get("status", "")
            if status in ("testing", "implementing"):
                # 已有进行中的 fix SPEC，视为重复派发，跳过
                return None
            if status in _FIX_SPEC_TERMINAL:
                # 上一轮修复已终态完成，本轮是新 bug，递归加前缀
                candidate = f"fix-{candidate}"
                continue
            # 可重置状态（drafted/ready/implemented/bug-found），复用
            return candidate

    def _ensure_fix_spec_files(self, fix_spec_name: str, parent_spec_name: str):
        """为自动生成的 fix SPEC 写入 proposal.md 与 tasks.md。

        fix SPEC 由验证引擎发现 bug 后自动创建，仅写入 STATE.md 是不够的——
        implementer Agent 依赖磁盘上的 proposal.md/tasks.md 才能执行，
        缺失会导致 SPEC 卡在 implementing 状态。此处生成最小可执行的 SPEC 文档。
        """
        spec_dir = self._pm.project_root / "spec" / "changes" / fix_spec_name
        # 目录创建纳入「写盘失败不抛穿」（与下方模板写入同口径）：磁盘满/
        # 权限/非法路径的 OSError 不得穿透 _do_legacy_fix_spec_bug_found。
        try:
            spec_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fix SPEC 目录创建失败 '{fix_spec_name}'（非阻断，派生主链继续）: {e}",
            )
            return

        proposal = (
            f"# Proposal: 修复 {parent_spec_name} 验证发现的缺陷\n\n"
            f"## Why\n\n"
            f"`{parent_spec_name}` 的验证报告发现产品缺陷，导致验证未通过。"
            f"详见 `spec/changes/{parent_spec_name}/verification-report.md` 的「真实产品 Bug」部分。\n\n"
            f"## What Changes\n\n"
            f"第一步必须复核失败场景的有效性（fix-fake-failure-first）："
            f"验证场景自身可能存在断言缺陷（如英文状态字面量 vs 产品中文渲染、"
            f"不存在的选择器、错误的前置数据），伪失败修复应改场景文件而非产品代码。"
            f"复核确认为真实产品 Bug 后，先阅读父 SPEC 的 `verification-report.md`，"
            f"定位每个真实产品 Bug 的根因并修复。\n\n"
            f"## Impact\n\n"
            f"- **代码**：按复核结论修复场景缺陷或真实产品缺陷\n"
            f"- **行为**：修复后，父 SPEC 验证报告中失败的场景应转为通过\n"
        )
        # 收尾任务按仓库形态适配：`npm run build` 与 `scripts/package.sh` 是
        # 早期浏览器扩展项目的收尾流程，对无 package.json 的项目（如纯 Python）
        # 不可执行——仅前端形态写具体命令，其余项目改为中性表述（单测步保留）。
        if (self._pm.project_root / "package.json").is_file():
            closing_tasks = (
                f"## 3. 验证与打包\n\n"
                f"- [ ] 3.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过\n"
                f"- [ ] 3.2 按项目既有测试入口运行单元测试，确认无回归\n"
                f"- [ ] 3.3 执行 `bash scripts/package.sh` 生成最新扩展包\n"
            )
        else:
            closing_tasks = (
                f"## 3. 验证与构建\n\n"
                f"- [ ] 3.1 按项目既有构建/打包流程执行收尾（如有）；无则跳过\n"
                f"- [ ] 3.2 按项目既有测试入口运行单元测试，确认无回归\n"
            )
        tasks = (
            f"# Tasks: 修复 {parent_spec_name} 验证发现的缺陷\n\n"
            f"## 1. 复核失败场景有效性（先于一切修复）\n\n"
            f"- [ ] 1.1 逐条核对 `spec/changes/{parent_spec_name}/verification-report.md` "
            f"中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为/DOM 是否相符；"
            f"断言与产品不符属场景缺陷——修场景文件，不改产品代码；"
            f"确属产品行为不符才进入第 2 步\n\n"
            f"## 2. 修复真实产品缺陷（仅当复核确认为真 Bug）\n\n"
            f"- [ ] 2.1 按 `verification-report.md` 的「真实产品 Bug」定位根因并修复；"
            f"场景缺陷则直接修正场景文件\n\n"
            f"{closing_tasks}"
        )

        # 原子写（tempfile + fsync + os.replace，对齐 _inject_verify_fix_task
        # 同款手法——tasks.md 是任务完成度门禁（_task_completion_blocker 经
        # parse_tasks_md 读取）的关键输入，proposal.md 承载修复动机与边界，
        # 中途崩溃/磁盘满不得留截断文件；临时文件建在 spec_dir 同目录保证
        # os.replace 原子性）
        # 写盘失败不抛穿（code-fix 313e34f89f8c，与 _inject_verify_fix_task 同
        # 口径）：磁盘满/权限等 OSError 若裸抛会穿透 _do_legacy_fix_spec_bug_found
        # 中断本轮状态重置与 _enqueue 主链——WARNING 留痕后返回，派生主链继续。
        try:
            for filename, content in (("proposal.md", proposal), ("tasks.md", tasks)):
                fd, tmp_name = tempfile.mkstemp(
                    prefix=f".{fix_spec_name}.{filename}.",
                    suffix=".tmp",
                    dir=str(spec_dir),
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_name, str(spec_dir / filename))
                finally:
                    if os.path.exists(tmp_name):
                        try:
                            os.unlink(tmp_name)
                        except OSError:
                            pass
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fix SPEC 模板文件写入失败 '{fix_spec_name}'（非阻断，派生主链继续）: {e}",
            )
            return
        self._pm.logger.info("pm_engine", f"Ensured fix SPEC files: {fix_spec_name}")

    @staticmethod
    def _fix_prefix_depth(name: str) -> int:
        """深度：规范名中连续 `fix-` 前缀层数（name 为子 SPEC 名）。

        fix-x → 1；fix-fix-fix-x → 3。非 fix 名 → 0。
        """
        depth = 0
        s = name
        while s.startswith("fix-"):
            depth += 1
            s = s[len("fix-") :]
        return depth

    @staticmethod
    def _fix_strip_all(name: str) -> str:
        """剥除全部连续 `fix-` 前缀，得到家族根名（fix-fix-x → x）。"""
        return (
            name[4 * FamilyGovernor._fix_prefix_depth(name) :] if name.startswith("fix-") else name
        )

    def _family_width(self, child_name: str) -> int:
        """宽度：同根（剥除全部 fix- 前缀后同名）且未完成（非 _FIX_SPEC_TERMINAL 终态）的 fix 子代数量。

        口径依据 STATE 全量 read_all（design D4：不受 ready 清空字段保留策略影响，
        对历史存在的四层命名按现值评估，不追溯惩罚已 done/pushed 祖先）。
        筛选口径复用 _same_root_siblings（code-review item 7a545a2237b1）：
        「同根 + 非终态 + 坏条目防御」只保留一份实现，防宽度门与
        兄弟互斥判定两处口径漂移分叉。
        """
        return len(self._same_root_siblings(child_name))

    @staticmethod
    def _waiver_flag_set(value) -> bool:
        """豁免位字段值的真值判定（豁免位消费原语的锁内判真口径）。"""
        raw = str(value or "").strip().lower()
        return raw in ("true", "1", "yes")

    def _consume_family_waiver(self, spec_name: str) -> bool:
        """消费豁免位：若存在则复位为 False，返回原值。

        「读值 → 判真 → 复位 → 带出原值」收进 state_machine 同一把
        ``.STATE.md.lock`` 临界区（code-review item f7a110bfe0b1）：原先
        「read_one 锁外读值 + update_spec 锁外复位」分持两次锁，
        同父 SPEC 的两个并发 bug-found 处置可都读到 True 并各自放行一个
        子 SPEC（豁免位双花）。改经 ``_mutate_locked`` 锁内回调完成单点
        CAS（bump_counters 同型）：判真与复位基于锁内最新条目，后到方
        读到的是先到方复位后的值、不再二次放行；复位写复用
        ``_apply_updates_entry``（updated 刷新等写语义单点维护，对齐
        admin_actions 的锁内展开范式），落盘后锁外照常留痕
        （``_log_update_applied`` 的「写入必留痕」约定）。
        """
        sm = self._pm.state_machine
        applied: dict = {}

        def _mutate(specs):
            entry = specs.get(spec_name)
            # 非法条目按未持有处置，不写不改不落盘。
            if not isinstance(entry, dict):
                return False, False
            if not self._waiver_flag_set(entry.get("_family_waiver")):
                return False, False
            found = sm._apply_updates_entry(
                specs, spec_name, {"_family_waiver": False}, applied
            )
            return found, found

        consumed = sm._mutate_locked(_mutate)
        if consumed:
            sm._log_update_applied(spec_name, applied)
        return consumed

    def _family_gate_blocked(self, child_name: str) -> bool:
        """越界判定：候选子 SPEC 的深度/宽度是否超过 pm.family 上限。

        深度 > max_depth（默认 3）或 宽度 >= max_width（默认 2，新成员将越界）
        时返回 True。enabled 语义由 config 承载：未配置即采用默认值。
        """
        max_depth_raw = self._pm._get_config("pm.family.max_depth")
        max_width_raw = self._pm._get_config("pm.family.max_width")
        # 非法配置值回退默认并 WARNING 留痕（code-review item 4b349f62101e）：
        # 族谱门是 bug-found 主链路，配置写坏不得中断处置；裸 int() 会把
        # 布尔 True 静默截成 1、小数 2.5 截成 2，配置写坏为 true 时门限被
        # 收紧到 1 且无痕拦截正常派生，故统一经类型守卫归一（bool 显式
        # 排除、非整值拒绝回退缺省，对齐 config._normalize_transient_seconds
        # 的裁决口径）。
        max_depth = self._family_gate_int(max_depth_raw, 3, "pm.family.max_depth")
        max_width = self._family_gate_int(max_width_raw, 2, "pm.family.max_width")
        depth = self._fix_prefix_depth(child_name)
        if depth > max_depth:
            return True
        width = self._family_width(child_name)
        return width >= max_width

    def _family_gate_int(self, raw, default: int, key: str) -> int:
        """族谱门整型配置归一：bool/非整值拒绝回退缺省，回退时 WARNING 留痕。

        裸 ``int()`` 会把布尔 True 静默截成 1、小数 2.5 截成 2（code-review
        item 4b349f62101e）——配置写坏为 ``true`` 时 max_depth/max_width 被
        收紧到 1，族谱门对正常派生直接拦截且无任何留痕。归一口径对齐
        config._normalize_transient_seconds / get_max_same_cause_redispatches
        的既有裁决：bool 显式排除（bool 是 int 子类）、整值浮点（``3.0``）
        按整数接受、非整值（含小数与非数字字符串）回退缺省并告警；
        非有限浮点（YAML ``.nan``/``.inf``）同样回退（code-review item
        bd02b5155058）——``int()`` 对其抛 ValueError/OverflowError；
        None 视为未配置沿用缺省、不留痕。

        正整数下限守卫（code-review item 0ca7cebd251a）：整值 ``< 1``（负数
        或 0）同样回退缺省并告警——负/零上限会让 ``_family_gate_blocked``
        的越界比较对一切 fix 派生恒判拦截（depth 恒 > max_depth、sibling 计数
        恒 >= max_width），自动修复派生链整体停摆且配置侧无痕；与
        get_run_infra_breaker_config 的 ``threshold < 1`` 回退缺省口径看齐。

        巨大 int 拦截（code-review item b981d1dee4d1）：YAML 任意精度大整数
        （如 10**400）或等值数字字符串穿透类型守卫与 ``< 1`` 比较后原样
        返回，max_depth/max_width 被抬到不可达、``_family_gate_blocked`` 对
        一切派生恒判放行，族谱收敛保护静默失效且无留痕——补
        ``abs(val) > sys.float_info.max`` 拦截回退缺省，与
        infra_breaker.threshold / _is_valid_state_number 的巨大 int 裁决
        （code-review item 8c2855513307）对齐。
        """
        if raw is None:
            return default
        normalized = default
        ok = False
        if not isinstance(raw, bool):
            if isinstance(raw, int):
                normalized, ok = raw, True
            elif isinstance(raw, float):
                # 小数拒绝——int() 截断会静默收紧门限（同 item 4b349f62101e）。
                # 非有限浮点（YAML .nan/.inf）在 int() 处抛 ValueError/
                # OverflowError 且不被任何捕获覆盖、穿透族谱门中断
                # bug-found 主链（item bd02b5155058），故先以 is_integer()
                # 短路取整——该谓词对非有限值恒 False（文档口径 finite
                # with integral value），脏值落 WARNING 回退缺省，同构
                # infra_breaker cooldown_minutes 的 isfinite 裁决。
                ok = raw.is_integer()
                if ok:
                    normalized = int(raw)
            else:
                try:
                    normalized, ok = int(str(raw).strip()), True
                except (TypeError, ValueError):
                    pass
        if ok:
            # 巨大 int（YAML 任意精度或等值数字字符串）穿透类型与下限守卫后
            # 原样返回，上限被抬到不可达、族谱门对一切派生恒判放行（code-review
            # item b981d1dee4d1），按 infra_breaker.threshold 的同款裁决以
            # abs(val) > sys.float_info.max 拦截回退缺省，与非法值同口径留痕。
            if abs(normalized) > sys.float_info.max:
                self._pm.logger.warning(
                    "pm_engine",
                    f"配置 {key} 非法（巨大整数会使上限不可达，族谱收敛保护失效）"
                    f": {raw!r}，回退缺省 {default}",
                )
                return default
            if normalized < 1:
                self._pm.logger.warning(
                    "pm_engine",
                    f"配置 {key} 非法（应为正整数，负数/0 会拦截全部 fix 派生）"
                    f": {raw!r}，回退缺省 {default}",
                )
                return default
            return normalized
        self._pm.logger.warning(
            "pm_engine",
            f"配置 {key} 非法（应为整数，布尔/小数/非数字均不合法）"
            f": {raw!r}，回退缺省 {default}",
        )
        return default

    @staticmethod
    def _is_fix_spec(name: str) -> bool:
        """判定 name 是否为 fix SPEC（连续 `fix-` 前缀命名）。"""
        return isinstance(name, str) and name.startswith("fix-")

    @staticmethod
    def _same_root(name_a: str, name_b: str) -> bool:
        """同根判定：剥除全部连续 `fix-` 前缀后同名（design D1 去重依据）。

        fix-fix-x 与 fix-x、fix-x 与 fix-x 同根；fix-x 与 fix-y、fix-x 与 y 不同根。
        """
        if not (FamilyGovernor._is_fix_spec(name_a) and FamilyGovernor._is_fix_spec(name_b)):
            return False
        return FamilyGovernor._fix_strip_all(name_a) == FamilyGovernor._fix_strip_all(name_b)

    def _same_root_siblings(self, spec_name: str) -> list:
        """返回 spec_name 的同根非终态兄弟列表（排除自身，design 守卫一/三）。

        口径：同根（剥除全部 fix- 前缀后同名）+ 非终态（终态集
        _FIX_SPEC_TERMINAL，与 _resolve_fix_spec_name 的派生判定同源——
        verified 兄弟已被加前缀继续派生、属已收敛成员，不再计入家族宽度，
        code-review item 757e05f354fd）。
        含自身处于进行中的兄弟亦计入——守卫关心的是「同根是否已有非终态修复活动」。
        """
        if not self._is_fix_spec(spec_name):
            return []
        root = self._fix_strip_all(spec_name)
        specs = self._pm.state_machine.read_all() or {}
        siblings = []
        for name, entry in specs.items():
            if not isinstance(name, str) or not self._is_fix_spec(name):
                continue
            if self._fix_strip_all(name) != root:
                continue
            if name == spec_name:
                continue
            # STATE 坏条目防御（code-review item 18a70e5931b4）：非 dict 条目
            # 直接跳过，不让 .get 抛 AttributeError 中断 bug-found 主链。
            if not isinstance(entry, dict):
                continue
            status = (entry or {}).get("status", "")
            if status in _FIX_SPEC_TERMINAL:
                continue
            siblings.append(name)
        return siblings

    def _sibling_repair_active(self, spec_name: str, my_enqueued_at: float = None) -> str:
        """判定同根兄弟是否存在 actionable 修复活动，返回承载方 spec 名或空串（design D3）。

        actionable 定义（design D3）：兄弟 status ∈ {implementing, ready(其队列含实现器条目)}
        或存在活跃 impl/verify agent（worktree 进程存活探测复用孤儿白名单逻辑）。
        仅 ready 无队列条目不计为 actionable（防僵死 ready 永久阻塞）。

        my_enqueued_at：派发方（守卫三调用点）自身条目的入队时刻，用于先到先得
        裁决（design D2「先到先得，后到抑制」）。批量入队现场（full_scan 一次排入
        同根双 ready）若不做此裁决，兄弟双方都会把对方判为 actionable 而互相抑制
        ——双方永远无法派发（2026-08-28 实证队列死锁）。规则：仅当兄弟的实现器
        条目入队不晚于我时，才由兄弟承载；兄弟更新则我来承载。同刻入队（相等
        边界）先到先得失效——双方互判对方承载即双双抑制，改由 spec_name 字典序
        稳定次序裁决：字典序小者承载、大者自我抑制（code-review item
        fa1186427415），对同一对条目两方裁决互补。
        my_enqueued_at 为 None（非派发路径调用）保持原判，全部计 actionable。
        """
        probed_dead: set = set()
        for sib in self._same_root_siblings(spec_name):
            sib_spec = self._pm.state_machine.read_one(sib) or {}
            status = sib_spec.get("status", "")
            if status == "implementing":
                return sib
            if status == "ready":
                # 仅当队列含该兄弟的实现车道条目时才视为 actionable。匹配实现
                # 车道集合 (implementer, fast-track)（code-review item
                # 17dd655b3031）：fast-track spec 的在队条目 agent_type 为
                # "fast-track"（见 inplace 打回与 legacy 派生分支按
                # read_spec_mode 选道的 _enqueue 通道字面量），只认 implementer
                # 会让同根 fast-track fix 兄弟对互斥判定失明。
                with self._pm._queue_lock:
                    sib_entry = next(
                        (
                            e
                            for e in self._pm._run_queue
                            if e[1] == sib and e[2] in ("implementer", "fast-track")
                        ),
                        None,
                    )
                if sib_entry is not None:
                    if my_enqueued_at is None:
                        return sib
                    if sib_entry[3] < my_enqueued_at:
                        return sib
                    if sib_entry[3] > my_enqueued_at:
                        # 兄弟条目晚于我入队：先到先得，由我承载，不计 actionable
                        continue
                    # 同刻入队（full_scan 同轮两次 _enqueue 取到同一时刻）：
                    # 先到先得在相等边界失效，双方互判对方「不晚于我」即由
                    # 对方承载、双双回滚成互斥死锁（code-review item
                    # fa1186427415）——相等边界改由 spec_name 字典序稳定次序
                    # 裁决：字典序小者判对方承载（自我抑制）、大者判自己
                    # 承载，同一对条目两方裁决互补，同根修复链不停摆。
                    if sib < spec_name:
                        return sib
                    continue
                # ready 但无队列条目：进一步探测活跃 worktree/agent 进程
                # 经门面回引：测试在门面实例上 patch 的补丁缝保持有效
                if self._pm._sibling_has_live_agent(sib):
                    return sib
                # 已探测且判不存活：记入集合，兜底循环跳过免重复探测
                probed_dead.add(sib)
        # 兜底：直接探测自身/兄弟是否仍有存活 agent 进程（覆盖非 ready 但卡死
        # 的边缘态）。第一轮已探测且判定不存活的兄弟不再重复探测（每次探测
        # 遍历 worktrees 目录并对每个匹配目录各起一个 timeout=10 的 pgrep
        # 子进程，重复探测使互斥判定的进程表扫描开销翻倍，code-review item
        # 69f0a027b493）。
        for sib in self._same_root_siblings(spec_name):
            if sib in probed_dead:
                continue
            if self._pm._sibling_has_live_agent(sib):
                return sib
        return ""

    def _sibling_has_live_agent(self, spec_name: str) -> bool:
        """探测 spec 是否仍有存活的 agent 子进程（worktree 存活探测，复用孤儿白名单逻辑）。

        - worktree_manager.has_active_worktree 优先（内存活动集合，最可靠）；
        - 否则用 agent_runner.has_live_attempt（姊妹变更落地接口）兜底；
        - 二者皆不可得时回退 pgrep 探测进程表（与 event_bus._ready_has_live_child 同口径）。
        """
        try:
            wm = getattr(self._pm.agent_runner, "worktree_manager", None)
            if wm is not None and hasattr(wm, "has_active_worktree"):
                if wm.has_active_worktree(spec_name):
                    return True
        except Exception:
            pass
        try:
            ar = self._pm.agent_runner
            if hasattr(ar, "has_live_attempt"):
                if ar.has_live_attempt(spec_name):
                    return True
        except Exception:
            pass
        # 回退：pgrep 探测 worktrees 目录下的 claude 进程（与 event_bus 同语义）
        try:
            import subprocess as _sp

            # 根目录经 worktree_manager.base_dir 取（与 fenixd.py 初始化同源读
            # worktree.base_dir），避免改配后写死 .claude/worktrees 使 is_dir()
            # 恒假、探测静默落空；属性链缺失时回退缺省目录
            wm = getattr(getattr(self._pm, "agent_runner", None), "worktree_manager", None)
            wt_root = getattr(wm, "base_dir", None) or (
                self._pm.project_root / ".claude" / "worktrees"
            )
            if not wt_root.is_dir():
                return False
            # 精确前缀归属守卫（对齐 queries.find_implementer_worktree 范式）：
            # 子串匹配会把同根后代 fix-fix-x 的 worktree 误记到 fix-x 头上
            for d in wt_root.iterdir():
                if not d.is_dir():
                    continue
                if d.name.startswith(f"impl-{spec_name}-") or d.name.startswith(
                    f"verify-{spec_name}-"
                ):
                    # 尾部锚定（对齐 worktree_manager.locks._worktree_has_live_process
                    # 的锚定纪律）：裸子串在兄弟 worktree 目录名互为前缀时过配——
                    # impl-x-<ts10> 的 pattern 会命中 impl-x-<ts11> 的进程，
                    # 其活进程持续把本 spec 判存活，压制孤儿修复/重派判定
                    r = _sp.run(
                        [
                            "pgrep",
                            "-f",
                            f"worktrees/{re.escape(d.name)}([/[:space:]\"']|$)",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        return True
        except Exception:
            return False
        return False

    def _has_non_terminal_child_fix(self, spec_name: str) -> str:
        """判定 spec 是否已存在同根非终态子 fix（守卫一/二共用，design D4 子终态解封）。

        返回承载修复的子 fix 名；无则空串。子 fix 指更深一层的 fix- 前缀 SPEC
        （fix-{spec} 自身或 fix-fix-{spec} 等），非终态 = 非 _FIX_SPEC_TERMINAL
        （done/verified/pushed，与 _resolve_fix_spec_name 的派生判定同源）。
        """
        child = f"fix-{spec_name}"
        specs = self._pm.state_machine.read_all() or {}
        # 逐层检查更深前缀的子 fix 是否存在且非终态
        candidate = child
        best = ""
        while True:
            entry = specs.get(candidate)
            if entry is None:
                # 该层不存在：若已有更深层终态子，仍可承载；否则停止
                if best:
                    break
                # 递归尝试更深一层（fix-fix-{spec}）
                deeper = f"fix-{candidate}"
                if deeper in specs:
                    candidate = deeper
                    continue
                break
            if not isinstance(entry, dict):
                # STATE 坏条目防御（code-review item 18a70e5931b4）：非 dict 条目
                # 无法判终态，按非终态子 fix 处理（不允许再派生、不抛
                # AttributeError 中断 bug-found 主链）；此处为 while 下探循环，
                # 不能 bare continue（候选未变会死循环），沿用非终态分支的下探逻辑。
                best = candidate
                deeper = f"fix-{candidate}"
                if deeper in specs:
                    candidate = deeper
                    continue
                break
            status = (entry or {}).get("status", "")
            if status in _FIX_SPEC_TERMINAL:
                # 该层终态：不承载，但允许检查更深一层是否仍在飞
                deeper = f"fix-{candidate}"
                if deeper in specs:
                    candidate = deeper
                    continue
                break
            # 非终态：作为承载方；但仍继续检查是否有更深在飞（取最深非终态）
            best = candidate
            deeper = f"fix-{candidate}"
            if deeper in specs:
                candidate = deeper
                continue
            break
        return best

    def _signal_family_explosion(self, parent_name: str, child_name: str, detail: str):
        """越界派生请求转 family_explosion 困境信号（severity=major）写入 admin store。

        不改父 SPEC 状态、不产生 bug-found 处理副作用（design D4）。信号进入既有
        admin_monitor 唤起链（Administrator 处置 → 可对父 SPEC 放行一次）。
        """
        from core.admin_store import AdminStore, SIGNAL

        try:
            store = AdminStore(self._pm.project_root, self._pm.logger)
            rec = store.append(
                {
                    "kind": SIGNAL,
                    "signal_type": "family_explosion",
                    "spec": parent_name,
                    "severity": "major",
                    "description": (
                        f"fix 族谱爆炸：'{parent_name}' 派生 {child_name} 被"
                        f"深度/宽度上限拦截（{detail}），自动创建已中止"
                    ),
                    "evidence": f"candidate={child_name}; {detail}",
                    "recommended_action": (
                        "人工检修根因环境；若确认放行一次，对该父 SPEC "
                        "设置 _family_waiver=true（下轮允许再创建一个子 SPEC）"
                    ),
                }
            )
            # code-review item 17c3e99da9b7：文件损坏留底被下限保护拒写时
            # append 返回 None（core/admin_store.py append 契约，item
            # 2570ca391771：记录未落盘，按未落地处理）——Administrator 唤起链
            # 实际收不到该信号，不得仍记「已写入」误导排查（与同文件
            # _send_human_escalation_alert 判空口径一致，item ae509e1816f3）。
            if rec is None:
                self._pm.logger.warning(
                    "pm_engine",
                    f"family_explosion 信号未落盘（store 拒写，按未落地处理）: "
                    f"'{parent_name}' → {child_name} 自动创建中止（{detail}）",
                )
            else:
                self._pm.logger.error(
                    "pm_engine",
                    f"fix 族谱收敛拦截: '{parent_name}' → {child_name} 自动创建中止（{detail}）"
                    f"，已写入 family_explosion 信号",
                )
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"family_explosion 信号写入 admin store 失败: {e}",
            )

    # ── 失败历史分类与证据（fix-verdict-retry-misattribution D6）─────────
    @staticmethod
    def _classify_fail_history(history: list) -> list:
        """为失败历史每轮标注分型与相邻轮 failed_scenarios diff。

        - repeat：该轮 failed_scenarios 与上一轮完全相同（无进展信号）；
        - 否则按 cause_type：evidence-invalid / real-bugs；
        - 侧车缺失（history 为空）→ 全轮标注 unknown。
        """
        if not history:
            return []
        out = []
        prev_set = None
        for r in history:
            scenarios = [str(s) for s in (r.get("failed_scenarios") or [])]
            cur_set = set(scenarios)
            ftype = r.get("cause_type") or "unknown"
            if prev_set is not None and cur_set == prev_set:
                ftype = "repeat"
            if ftype not in ("evidence-invalid", "real-bugs", "repeat"):
                ftype = "unknown"
            if prev_set is None:
                diff = {"added": sorted(cur_set), "removed": [], "persisted": []}
            else:
                diff = {
                    "added": sorted(cur_set - prev_set),
                    "removed": sorted(prev_set - cur_set),
                    "persisted": sorted(cur_set & prev_set),
                }
            out.append(
                {
                    "round": r.get("round"),
                    "type": ftype,
                    "cause_type": r.get("cause_type"),
                    "scenarios": sorted(cur_set),
                    "diff_vs_prev": diff,
                }
            )
            prev_set = cur_set
        return out

    @staticmethod
    def _format_fail_history_evidence(classified: list, fail_rounds: int) -> str:
        """格式化升级闸门告警 evidence：分型摘要 + 相邻轮 diff 明细。"""
        if not classified:
            return (
                f"failure_profile=unknown（fail_history 缺失或首轮即触发冻结，"
                f"侧车无足够数据）; fail_rounds={fail_rounds}"
            )
        parts = [f"fail_rounds={fail_rounds}"]
        type_summary = [f"round{c.get('round')}:{c.get('type')}" for c in classified]
        parts.append(f"failure_profile={'; '.join(type_summary)}")
        for c in classified:
            d = c["diff_vs_prev"]
            round_num = c.get("round")
            parts.append(
                f"diff[round{round_num}]: "
                f"added={d['added']} removed={d['removed']} "
                f"persisted={d['persisted']}"
            )
        repeats = [c for c in classified if c.get("type") == "repeat"]
        if repeats:
            rounds = [c.get("round") for c in repeats]
            parts.append(
                f"repeat_rounds={rounds}"
                f"（与上一轮失败场景集完全相同，相邻轮 diff 为空——"
                f"可能属「根因已修复但闸门仍冻结」的误置情形，建议人工核对）"
            )
        return "; ".join(parts)

    def _do_spec_bug_found(self, spec_name: str, failure_class: str = "product", run_id: str = ""):
        """实际执行 bug-found 处理逻辑。

        分流依据（add-bug-repair-mode-config D2）：`admin.bug_repair_mode` 有效值
        取代 SPEC 名称前缀（`_is_fix_spec` 分流退役）。每次 bug-found 事件实时读取
        配置（经 get_admin_config 同源路径，不做实例级缓存）——与配置热更新（30s
        mtime）语义对齐，切换模式后下一次事件即按新值生效。
        - inplace（含未配置缺省）：对任何 SPEC（含 fix-* 名字）原地打回重修；
        - derive：派生 fix-* 子 SPEC（守卫一、族谱收敛 governor、_resolve_fix_spec_name
          逐级命名、done→父重验闭环全部保留生效）。

        evo-infra-failure-budget-exempt R3：``failure_class`` 三态归因——
        仅 product（unknown 按 product 保守处置）累加 ``_verify_fail_rounds``；
        infra 轮**不进本分支**（防御性守卫，正常由归因入口改走
        ``_record_infra_failure`` 记账，不递增闸门计数、不冻结、不派生 fix）。
        """
        # ── infra 防御性守卫（evo-infra-failure-budget-exempt R3）──
        # 调用方应在统一归因入口（enrich_failure_class 判定处）拦截 infra：
        # 记 _verify_infra_rounds + 预算退款 + 台账 failure_class=infra，
        # 不调用本函数。此处兜底：即使误入也绝不递增 _verify_fail_rounds
        # （infra 轮与 product 轮同计会虚增冻结计数，验收「闸门不累加」落空）。
        if failure_class == "infra":
            self._pm.logger.warning(
                "pm_engine",
                f"infra 归因误入 bug-found 分支 '{spec_name}' — 抑制闸门递增"
                f"（本分支仅 product/unknown 类）",
            )
            return

        from core.config import ConfigLoader

        mode = ConfigLoader.get_admin_config(self._pm.config).get("bug_repair_mode", "inplace")

        if mode == "derive":
            # ── derive 模式：派生 fix-* 子 SPEC（可配置保留的 legacy 派生闭环）──
            # 守卫一（fix-repair-lane-dedup）：fix spec 已有非终态子 fix 时抑制 reset
            carrier = self._has_non_terminal_child_fix(spec_name)
            if carrier:
                self._pm.logger.info(
                    "pm_engine",
                    f"守卫一：'{spec_name}' 为 fix spec 且已有非终态子 fix "
                    f"'{carrier}' 承载修复——抑制 reset，保持 bug-found",
                )
                self._pm.state_machine.update_spec(
                    spec_name,
                    {
                        "error": f"修复由子 fix '{carrier}' 承载，抑制重实现重置",
                    },
                )
                return
            # 派生闭环（守卫一 + 族谱 governor + _resolve_fix_spec_name 在函数内生效）
            self._do_legacy_fix_spec_bug_found(spec_name)
            return

        # ── inplace 模式（含未配置缺省）：原地打回（inplace-bug-repair D1-D3）──
        # 对任何 SPEC 生效，包括名称带 fix- 前缀的 SPEC（名称前缀分流已退役）。
        entry = self._pm.state_machine.read_one(spec_name) or {}
        # judge-rerun-stability R1：judge 重跑 hard cap 触发（_judge_cap_frozen）
        # 时 _verify_fail_rounds 一并冻结——不再递增（spec 已 blocked 等待人工，
        # 计数器保持冻结值，防止解冻后从旧值继续误累积）。
        if entry.get("_judge_cap_frozen"):
            self._pm.logger.warning(
                "pm_engine",
                f"judge hard cap 冻结期间 '{spec_name}' 的 _verify_fail_rounds "
                f"冻结递增（保持 {entry.get('_verify_fail_rounds', 0)}）",
            )
            return
        # 计数递增走锁内原子原语（code-fix dd37a2be6ef6）：原先「read_one 读 →
        # 算 +1 → 并进下方 update_spec 写回」读与写分处两段，与 fastlane 失败
        # 记账（dispatch_minor_defect_fastlane 对同字段 bump_counters 原子递增）
        # 在同一 spec 上时间重叠时，读旧值写回会吞掉对方刚加的增量。改按
        # bump_counters 写后最新值判阈值；下方冻结/打回写不再并入该字段。
        fail_rounds = self._pm.state_machine.bump_counters(
            spec_name, {"_verify_fail_rounds": 1}
        ).get("_verify_fail_rounds", 0)

        # ── 失败历史侧车（fix-verdict-retry-misattribution D6 + R3）──
        # 本轮 bug-found 采纳 = 真缺陷失败轮（cause_type=real-bugs），记入侧车供
        # 升级闸门分型与轮间 diff。写盘失败静默降级（分型 unknown，不阻断闸门）。
        # failure_class=product（或 unknown）随 R3 回拨参考台账记入。
        self._pm._append_fail_history(
            spec_name,
            "real-bugs",
            self._pm._failed_scenario_ids(spec_name),
            failure_class=failure_class,
            run_id=run_id,
        )

        if fail_rounds >= MAX_VERIFY_FAIL_ROUNDS:
            # ── 升级闸门：冻结转人工（freeze_for_human 单一入口）──
            # code-fix 0eda9bae5886：原先裸 update_spec 置 blocked，error 文案
            # 既无 frozen 结构化标记也无 FREEZE_ERROR_PREFIX，blocked_stuck
            # 看门狗的三选一豁免（frozen 字段 / 'frozen:' 前缀 / '用户指令'
            # 子串）全不命中——闸门声称「等待人工裁决」却会被自动派 admin
            # run。改走 freeze_for_human：frozen 与人工升级告警成对落盘，
            # 豁免真正生效。_verify_fail_rounds 已由上方 bump_counters 原子
            # 递增并落盘，不再并入本次写（避免覆盖并发写者的增量）。
            history = self._pm._read_fail_history(spec_name)
            classified = self._classify_fail_history(history)
            self._pm.state_machine.freeze_for_human(
                spec_name,
                error=(
                    f"升级闸门连续失败第 {fail_rounds} 轮，已冻结等待人工裁决。"
                    f"详见 `spec/changes/{spec_name}/verification-report.md`"
                ),
                signal_type="verify_fail_escalation",
                severity="major",
                description=(
                    f"'{spec_name}' 升级闸门连续失败第 {fail_rounds} 轮，已冻结等待人工裁决"
                ),
                evidence=(
                    f"spec={spec_name}; "
                    + self._format_fail_history_evidence(classified, fail_rounds)
                    + f"; report=spec/changes/{spec_name}/verification-report.md"
                ),
                recommended_action=(
                    "检查验证报告定位根因，人工调整 SPEC 状态后重跑验证；"
                    "人工重置计数器即重新获得自动修复机会"
                ),
                alert_callback=self._send_human_escalation_alert,
            )
            self._pm.logger.error(
                "pm_engine",
                f"升级闸门：'{spec_name}' 升级闸门连续失败第 {fail_rounds} 轮，"
                f"冻结为 blocked，等待人工裁决",
            )
            # 失败历史已被本次告警消费，清空侧车避免陈旧记录污染下一链条
            self._pm._clear_fail_history(spec_name)
            return

        # ── 正常打回：重置 implementing + 注入修复任务 ──
        # 计数已由上方 bump_counters 原子递增并落盘，此处不再并入 update_spec
        # （避免覆盖并发写者——如 fastlane 失败记账——的增量）。
        repair_fields = {
            "status": "implementing",
            "error": (f"验证失败（原地打回第 {fail_rounds} 轮），重修中"),
        }
        # 对齐下方 legacy 派生分支与 escalation / dispatch/rollback 的重置语义：
        # 打回重置状态时剥除上一轮遗留的 run 锚点，防新轮误挂旧 run
        # （code-review item 12142fc5cbaa）；entry 为本分支入口处 read_one
        # 快照，与 legacy 分支的 existing_fix 同形。
        if entry.get("implementer_run") is not None:
            repair_fields["implementer_run"] = None
        if entry.get("tester_run") is not None:
            repair_fields["tester_run"] = None
        # 写前冻结复查（code-review item 7d53e9eacf26，仿 dispatch/rollback
        # ._rollback_frozen_recheck/_rollback_write_guarded 收口）：入口 entry
        # 快照到此写之间隔着 bump_counters 与 _append_fail_history 的文件 I/O
        # （窗口比 transition 路径更宽），窗口内并发冻结时 frozen 条目的
        # update_spec 只剥 status 键——error 覆盖与 implementer_run/tester_run
        # 锚点清除照常生效，破坏冻结恢复语义。发现冻结即放弃打回（下方
        # tasks.md 修复段注入与重派一并跳过），bug-found 事件留待冻结解除后
        # 处理。
        from core.state_machine import FROZEN_FIELD

        if (self._pm.state_machine.read_one(spec_name) or {}).get(FROZEN_FIELD):
            self._pm.logger.warning(
                "pm_engine",
                f"原地打回放弃：'{spec_name}' 写盘前复查发现已冻结——放弃 "
                f"implementing 重置写与重派，冻结现场保留待人工解冻",
            )
            return
        self._pm.state_machine.update_spec(spec_name, repair_fields)
        self._pm.logger.warning(
            "pm_engine",
            f"原地打回第 {fail_rounds} 轮：'{spec_name}' 验证失败，"
            f"重置为 implementing 并注入修复任务",
        )
        # 注入 tasks.md「验证修复」段
        self._inject_verify_fix_task(spec_name, fail_rounds)
        # PROJECT_LOG 可丢、主链不可断（b21d8f2d8247 同口径）：此时打回已
        # 生效、修复段已注入，写盘失败不得中断下方重派 _enqueue
        try:
            self._pm._append_project_log(
                f"🐛 Bug found in **{spec_name}** → 原地打回第 {fail_rounds} 轮"
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"原地打回项目日志失败 '{spec_name}'（非阻断，打回已生效）: {e}",
            )
        # 重派通道按 spec 实现模式选择（与 repair_lane._fallback_after_repair、
        # engine 实现态恢复同口径）：fast-track spec 打回后仍回 fast-track
        # 重派，不硬派 implementer（读侧异常回退 implementer）
        try:
            from core.spec_mode import read_spec_mode

            channel = (
                "fast-track"
                if read_spec_mode(self._pm.project_root, spec_name) == "fast-track"
                else "implementer"
            )
        except Exception:
            channel = "implementer"
        self._pm._enqueue(spec_name, channel)

    def _do_legacy_fix_spec_bug_found(self, spec_name: str):
        """存量 fix-* SPEC 的 legacy 闭环（design D4：自然终态耗尽）。

        保留原有派生逻辑，直至所有存量 fix 链收敛。
        """
        raw_prio = (self._pm.state_machine.read_one(spec_name) or {}).get("priority", 5)
        # STATE 坏值容错（code-review item f0514aca33fe）：priority 被人工/外部
        # 改写为 None/非数值时下方 +1 会抛 TypeError 中断 bug-found 主链——
        # 对齐 dispatch/queue._get_spec_priority 的容错口径，非法值回退 5。
        parent_prio = raw_prio if isinstance(raw_prio, int) else 5

        # 确定本轮 bug 应使用的 fix SPEC 名称
        fix_spec_name = self._resolve_fix_spec_name(spec_name)
        if fix_spec_name is None:
            self._pm.logger.info(
                "pm_engine",
                f"Legacy fix SPEC for '{spec_name}' already in progress — "
                f"skipping duplicate bug-found handling",
            )
            return

        # ── fix 族谱收敛治理（design D4 legacy）──
        if self._pm.state_machine.read_one(fix_spec_name) is None:
            if self._family_gate_blocked(fix_spec_name):
                if self._consume_family_waiver(spec_name):
                    self._pm.logger.warning(
                        "pm_engine",
                        f"family_explosion 人工放行：'{spec_name}' 本轮豁免一次，"
                        f"继续创建 {fix_spec_name}",
                    )
                else:
                    detail = (
                        f"深度={self._fix_prefix_depth(fix_spec_name)}, "
                        f"宽度={self._family_width(fix_spec_name)}"
                    )
                    self._signal_family_explosion(spec_name, fix_spec_name, detail)
                    return
            # 未拦截（本就可创建）不消费豁免位（code-fix 33388af2a264）：waiver
            # 是管理员为后续将被深度/宽度拦截的派生预留的一次性放行额度，在
            # 不需要豁免的平凡创建上白白吃掉，真正被拦的那轮反而无豁免可用。

        existing_fix = self._pm.state_machine.read_one(fix_spec_name)
        guard_status = (existing_fix or {}).get("status", "")
        # 模板写入守卫（与下方幂等守卫对齐）：仅当 fix SPEC 不存在或状态属
        # 待重置集时写入模板文件；implementing/implemented 等在途状态的
        # tasks.md 已含勾选进度与修复结论、proposal.md 可能经人工细化，
        # 重写空白模板会丢失这些内容。
        if (
            existing_fix is None
            or guard_status not in _FIX_SPEC_IN_FLIGHT_OR_TERMINAL
        ):
            self._ensure_fix_spec_files(fix_spec_name, spec_name)

        # 重派通道按 spec 实现模式选择（code-review item f8ec6766731f，与上方
        # inplace 打回路径、repair_lane._fallback_after_repair 同口径）：fast-track
        # spec 派生的 fix SPEC 仍走 fast-track 重派，不硬派 implementer（读侧
        # 异常回退 implementer）。原先硬编码 implementer 入队与 _on_spec_ready
        # 内的模式感知入队按 (spec, agent_type) 去重键互不吸收，fast-track
        # fix spec 会双落 fast-track + implementer 两条条目，后者放行后以
        # implementer 车道错派单 run 全包 spec。
        try:
            from core.spec_mode import read_spec_mode

            channel = (
                "fast-track"
                if read_spec_mode(self._pm.project_root, fix_spec_name) == "fast-track"
                else "implementer"
            )
        except Exception:
            channel = "implementer"

        if existing_fix:
            if guard_status in _FIX_SPEC_IN_FLIGHT_OR_TERMINAL:
                self._pm.logger.info(
                    "pm_engine",
                    f"Fix SPEC '{fix_spec_name}' 处于 '{guard_status}' "
                    f"— bug-found 重发幂等守卫：跳过重置，保留状态与 run 字段",
                )
            else:
                self._pm.logger.info(
                    "pm_engine",
                    f"Fix SPEC '{fix_spec_name}' already exists "
                    f"(status={guard_status}) — resetting to ready",
                )
                reset_fields = {
                    "status": "ready",
                    "error": f"Re-triggered from bug found in {spec_name}",
                }
                # 对齐 escalation.py / dispatch/rollback.py 的重置语义：status
                # 复位 ready 时剥除上一轮遗留的 run 锚点，防新轮误挂旧 run。
                if existing_fix.get("implementer_run") is not None:
                    reset_fields["implementer_run"] = None
                if existing_fix.get("tester_run") is not None:
                    reset_fields["tester_run"] = None
                # 写前冻结复查（code-review item 7d53e9eacf26，与上方 inplace
                # 打回及 dispatch/rollback._rollback_frozen_recheck 同款收口）：
                # existing_fix 快照到此写之间隔着 _ensure_fix_spec_files 等文件
                # I/O，窗口内 fix SPEC 被并发冻结时 frozen 条目的 update_spec
                # 只剥 status 键——error 覆盖与 run 锚点清除照常生效。发现冻结
                # 即放弃重置（_on_spec_ready 与重派一并跳过），bug-found 事件
                # 留待冻结解除后处理。
                from core.state_machine import FROZEN_FIELD

                if (
                    self._pm.state_machine.read_one(fix_spec_name) or {}
                ).get(FROZEN_FIELD):
                    self._pm.logger.warning(
                        "pm_engine",
                        f"legacy fix 重置放弃：'{fix_spec_name}' 写盘前复查发现"
                        "已冻结——放弃 ready 重置写与重派，冻结现场保留待人工解冻",
                    )
                    return
                self._pm.state_machine.update_spec(fix_spec_name, reset_fields)
                self._pm._on_spec_ready(fix_spec_name)
                # 入队收敛（code-review item 5e687a6085a1）：仅在实际发生重置/
                # 新建的分支入队——幂等守卫跳过重置的 spec（implemented/blocked
                # 等在途或终态）不在 _queue_entry_ready 的 implementer 放行口径
                # （ready/implementing）内，无条件入队只会留下每轮扫描被跳过却
                # 不淘汰的永久滞留条目，还违背守卫「不动该 spec」的裁定。
                self._pm._enqueue(fix_spec_name, channel)
        else:
            self._pm.state_machine.add_spec(
                fix_spec_name,
                {
                    "status": "ready",
                    "priority": min(parent_prio + 1, 10),
                    "branch": None,
                    "error": f"Auto-created from bug found in {spec_name}",
                },
            )
            self._pm.logger.info("pm_engine", f"Created fix SPEC: {fix_spec_name}")
            # 新建分支入队（同上，code-review item 5e687a6085a1）
            self._pm._enqueue(fix_spec_name, channel)

        # PROJECT_LOG 可丢、主链不可断（b21d8f2d8247 同口径）：写盘失败不得
        # 抛穿 bug-found 处理链
        try:
            self._pm._append_project_log(
                f"🐛 Bug found in **{spec_name}** → scheduling legacy **{fix_spec_name}**"
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"legacy 派生项目日志失败 '{spec_name}'（非阻断，派生已生效）: {e}",
            )

    def _read_prev_impl_conclusions(self, spec_name: str) -> str:
        """读取上一轮 implementer 的收工结论，作为修复段的「上轮实现结论」小节。

        背景（fast-track 复盘，2026-09-02）：verify-repair 每轮的 implementer
        都要花 30+ 分钟从源码重新推导上轮已查明的结论（验证测的是哪个 dist、
        失败是场景缺陷还是产品 bug 等）——根目录 result 的 summary 是唯一载体，
        却从未传给下一轮。无记忆传递的重派是重复烧钱的固定根因
        （fix-startup-double-dispatch 处置：38% 纯重复）。

        主树 .fenix/.fenix-run-result.json 是跨 spec 共享文件：spec 字段不匹配
        （并发派发的其它 spec 的结果）时不注入，防跨 spec 污染。命中时同时
        持久化 per-spec 副本到 .fenix/verify-progress/<spec>/prev-impl-result.json
        （根文件会被后续 run 覆盖，副本供人工与后续轮次回溯）。
        """
        result_path = self._pm.project_root / ".fenix" / ".fenix-run-result.json"
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict) and data.get("spec") == spec_name:
            try:
                snap_dir = (
                    self._pm.project_root / ".fenix" / "verify-progress" / spec_name
                )
                snap_dir.mkdir(parents=True, exist_ok=True)
                # 原子写（tempfile + fsync + os.replace，落实 engine.py:1908
                # 注释声称的「同款手法」——prev-impl-result.json 供人工与后续轮次
                # 回溯，进程中断不得留截断 JSON）
                fd, tmp_name = tempfile.mkstemp(
                    prefix=".prev-impl-result.",
                    suffix=".tmp",
                    dir=str(snap_dir),
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(json.dumps(data, ensure_ascii=False, indent=2))
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_name, str(snap_dir / "prev-impl-result.json"))
                finally:
                    if os.path.exists(tmp_name):
                        try:
                            os.unlink(tmp_name)
                        except OSError:
                            pass
            except OSError:
                pass
        else:
            # 根文件缺失/被并发 spec 覆盖时回退读 per-spec 副本（code-review
            # item 1c6e6ec4620d）：副本的写入条件即根文件 spec 匹配本 spec
            # （stamp 已等于本 spec），回读无跨 spec 污染；副本已是持久化
            # 快照，回读时不再重写。
            snap_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / "prev-impl-result.json"
            )
            try:
                data = json.loads(snap_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return ""
            if not isinstance(data, dict) or data.get("spec") != spec_name:
                return ""
        summary = str(data.get("summary") or "").strip()[:800]
        findings = data.get("findings") or []
        # findings 形状守卫（code-review item 29af31a59dfa）：根文件跨 spec/
        # 跨车道共享，findings 为非 list 真值（dict/int 等）时下方 findings[:5]
        # 抛 TypeError 穿透 _inject_verify_fix_task 打断 bug-found 打回主链
        # （此时状态已重置 implementing、修复段未注入、重派未入队）——非 list
        # 按空清单降级，与 _same_root_siblings 的 STATE 坏条目防御
        # （item 18a70e5931b4）及 runs._parse_run_metric_stream 非 dict 行
        # 降级口径同族对齐。
        if not isinstance(findings, list):
            findings = []
        if not summary and not findings:
            return ""
        lines = ["", "### 上轮实现结论（自动携带，来自上一轮 implementer 收工结论）", ""]
        if summary:
            lines += [summary, ""]
        if findings:
            lines.append("上轮登记的 findings：")
            for f in findings[:5]:
                if isinstance(f, dict):
                    lines.append(
                        f"- {f.get('type', '?')}: {f.get('element', '')}"
                        f" — {f.get('suggestion') or f.get('current', '')}"
                    )
                else:
                    lines.append(f"- {f}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _sanitize_injected_text(text: str) -> str:
        """净化拼入「## 验证修复」段的自由文本（code-review item 0d8df4cc0e33）。

        上轮实现结论是 agent 自由文本，可能含行首「## 」或 ``` / ~~~ 围栏行，
        而段界探测按「围栏外首个行首二级标题」截断替换区间、按 stripped 后的
        围栏标记开合过滤——不净化则行首「## 」会让下轮段界提前落在结论内部
        （旧段剩余任务清单残留并逐轮堆积）、未闭合围栏让段界永不命中（end 停在
        文件尾，替换区间吞掉该段之后全部文件内容）。危险行统一加「> 」引用前缀
        使其失去行首锚（strip 后也不再以围栏标记开头），内容保留可读；判定谓词
        与段界探测逐字对齐（原始行「## 」前缀、stripped 后 ``` / ~~~ 前缀）。
        """
        if not text:
            return text
        safe_lines = []
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            if (
                line.startswith("## ")
                or stripped.startswith("```")
                or stripped.startswith("~~~")
            ):
                line = "> " + line
            safe_lines.append(line)
        return "".join(safe_lines)

    def _inject_verify_fix_task(self, spec_name: str, fail_rounds: int):
        """在父 SPEC 的 tasks.md 末尾追加/更新「## 验证修复」任务段。

        - 首次失败：追加新段
        - 后续失败：更新段内轮数注记
        MUST NOT 改写既有任务与勾选状态（design D3）。
        """
        tasks_path = self._pm.project_root / "spec" / "changes" / spec_name / "tasks.md"
        if not tasks_path.exists():
            self._pm.logger.warning(
                "pm_engine",
                f"tasks.md 不存在，跳过验证修复段注入：{spec_name}",
            )
            return

        try:
            text = tasks_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            self._pm.logger.warning(
                "pm_engine",
                f"tasks.md 读取失败，跳过验证修复段注入：{spec_name}: {e}",
            )
            return

        report_path = f"spec/changes/{spec_name}/verification-report.md"
        # fix-fake-failure-first：第一步强制复核失败场景有效性——验证场景自身
        # 的断言缺陷（英文状态字面量 vs 产品中文渲染、不存在选择器等）曾被当作
        # 产品 Bug 触发整条修复链（3 轮实现 5.24h 修一个不存在的 bug）。
        # prev 是 agent 自由文本，拼入段前先净化（行首「## 」/围栏标记加引用
        # 前缀），防下方段界扫描被注入文本内部的伪段界/未闭合围栏带偏
        # （code-review item 0d8df4cc0e33）。
        prev = self._sanitize_injected_text(self._read_prev_impl_conclusions(spec_name))
        section = (
            f"\n\n## 验证修复（原地打回第 {fail_rounds} 轮）\n"
            f"{prev}"
            f"\n- [ ] 先复核失败有效性：逐条核对 `{report_path}` 中失败场景的期望断言"
            f"（状态字面量/选择器/前置数据）与产品实际行为是否相符——"
            f"断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码\n"
            f"- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码\n"
            f"- [ ] 修复后重跑验证确认通过\n"
        )

        m = self._pm._VERIFY_FIX_SECTION_RE.search(text)
        if m:
            # 已有验证修复段：替换为新轮数版本
            # 找到段的起始位置（含前一个 \n\n），到段尾
            start = m.start()
            # 向前找到段落分隔
            while start > 0 and text[start - 1] == "\n":
                start -= 1
            # 向后找到下一个二级标题或文件末尾。MUST NOT 排除「验」字（item
            # 255393413ec3）：本段内部不含二级标题，「## 验收标准」等以「验」
            # 开头的后续标题也是合法段界——排除会把整段误并入替换区间删掉。
            after = text[m.end() :]
            # 段界探测围栏感知（code-review item cb421886ef72）：tasks.md 可能
            # 贴含行首「## 」的代码围栏示例，裸搜 "\n## " 会在围栏内提前截断
            # 替换区间丢内容——逐行跟踪 ``` / ~~~ 围栏开合，仅在围栏外匹配
            # 首个二级标题（保持原「下一个二级标题」命中语义）。
            end = len(text)
            offset = m.end()
            fence_char = ""
            fence_len = 0
            for line in after.splitlines(keepends=True):
                body = line.strip()
                if fence_char:
                    # 闭栏：同字符、长度不小于开栏的裸标记行（不得带 info 串）
                    if body and set(body) == {fence_char} and len(body) >= fence_len:
                        fence_char = ""
                elif body.startswith("```") or body.startswith("~~~"):
                    fence_char = body[0]
                    fence_len = len(body) - len(body.lstrip(body[0]))
                elif line.startswith("## "):
                    end = offset
                    break
                offset += len(line)
            # 行首锚保持（item a25d95843de3）：start 已回退吃掉段前全部换行、
            # section.strip() 又剥掉新段自带的前导换行，直接拼接会把「## 验证修复」
            # 标题粘在上一行行尾，下一轮 ^## 验证修复 MULTILINE 失配走追加分支、
            # 修复段重复堆积。此处补回段落分隔（与追加分支 \n\n 形态一致）；
            # start==0（段落在文件头）时不补，避免文件首出现多余空行。
            sep = "\n\n" if start > 0 else ""
            # 段尾同样回补空行分隔（code-review item ecc1436a1615）：end 落在
            # 下一个二级标题行首，原区间内标题前的空行被一并吞掉，段尾只补
            # 单 \n 会让修复段与后续标题贴合成单换行相接、tasks.md 版式逐轮
            # 退化——与段前 sep 的 \n\n 形态对称。end 抵文件末尾（段后无
            # 后续标题）时不补，避免文件尾堆积空行。
            sep_tail = "\n\n" if end < len(text) else "\n"
            new_text = text[:start] + sep + section.strip() + sep_tail + text[end:]
        else:
            # 无现有段：追加到末尾
            new_text = text.rstrip("\n") + section

        # 原子写（tempfile + fsync + os.replace，对齐 engine._sync_task_progress
        # 同款手法——tasks.md 是任务完成度门禁（_task_completion_blocker 经
        # parse_tasks_md 读取）的关键输入，中途崩溃/磁盘满不得留截断文件）
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".tasks.{spec_name}.",
                suffix=".tmp",
                dir=str(tasks_path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(new_text)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_name, str(tasks_path))
            finally:
                if os.path.exists(tmp_name):
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"验证修复段写入 tasks.md 失败：{spec_name}: {e}",
            )
            return
        self._pm.logger.info(
            "pm_engine",
            f"验证修复段已{'更新' if m else '注入'}：{spec_name}（原地打回第 {fail_rounds} 轮）",
        )

    def _send_human_escalation_alert(
        self,
        spec_name: str,
        signal_type: str,
        severity: str,
        description: str,
        evidence: str,
        recommended_action: str,
        trigger: Optional[dict] = None,
        facts: Optional[dict] = None,
    ):
        """发送 human-escalation-alerts 告警（escalation 种类）写入 admin store。

        add-alert-auto-resolve D2：条目附带结构化触发条件（trigger 字段，含
        type/spec/condition），供闭环判定直接消费、无需解析自然语言 description。
        trigger 缺省时按 signal_type 从闭环枚举推导（接入点集中在此一处）；
        未接入枚举的 signal_type 不写 trigger、永不自动闭环（保守默认）。
        facts 为可选结构化增强参数位（upgrade-narrative-to-investigation 1.2：
        发射点内存中独有、事后难重建的信息如 judge 派发台账；本期缺省不传
        不注入，prompt【补充事实】段存在时才注入），不参与 trigger/choices
        既有落盘形态。

        降噪分级（2026-09-01 用户决策）：仅 critical/major 进人工待处理队列；
        warning/minor 写入即标记 handled，只留历史记录不弹横幅。
        """
        from core.admin_store import AdminStore, ESCALATION, severity_needs_human
        from core.alert_lifecycle import build_trigger

        try:
            store = AdminStore(self._pm.project_root, self._pm.logger)
            if trigger is None:
                trigger = build_trigger(signal_type, spec_name)
            entry = {
                "kind": ESCALATION,
                "signal_type": signal_type,
                "spec": spec_name,
                "severity": severity,
                "description": description,
                "evidence": evidence,
                "recommended_action": recommended_action,
            }
            if trigger:
                entry["trigger"] = trigger
            # add-human-adjudication-choices 2.1-2.5：桶 2 发射点接线（D1「发射点
            # 只引用注册表」+ D2「写告警时快照」）——按 signal_type 从裁决选项
            # 注册表取 choices 并入告警记录。本单点是全部 ESCALATION 告警的
            # 共同写入口（预算耗尽/升级闸门/评审两族/judge 重跑上限/同因重派
            # 熔断/恢复期 human_alert_callback 均汇聚于此），注册表未覆盖的
            # 信号（桶 0 知情/自愈类等）返回空集、不写该字段——MUST NOT 携带。
            from core.dashboard.data.adjudication_choices import choices_for

            choices = choices_for(signal_type)
            if choices:
                entry["choices"] = list(choices)
            # add-adjudication-alert-narrative 2.1 → upgrade-narrative-to-
            # investigation 3.1：叙事从「落盘前同步附加」改为「落盘后后台补叙」
            # ——告警以机械文案**立即落盘**（append 先行，叙事时延/失败零阻塞
            # 落盘路径），随后调度后台生成经侧车补叙（alert_id 取落地记录的
            # id，MUST NOT 依赖 entry 预先持有）；choices 非空才发起（桶 0
            # 零线程零调用）。facts 为可选结构化增强（task 1.2 参数位，本期
            # 发射点缺省不传不注入）。
            rec = store.append(entry)
            # code-review item ae509e1816f3：文件损坏留底被下限保护拒写时
            # append 返回 None（core/admin_store.py append 契约，item
            # 2570ca391771：记录未落盘，按未落地处理）——未判空即取 rec["id"]
            # 会抛 TypeError 被外层误记为「Failed to send escalation alert」，
            # 掩盖 store 拒写真实根因（同款写法见 token_budget item
            # 3e202131bd3a）。
            if rec is None:
                self._pm.logger.warning(
                    "pm_engine",
                    f"human-escalation-alert 未落盘（store 拒写，按未落地处理）: "
                    f"{signal_type} for '{spec_name}'",
                )
            else:
                if not severity_needs_human(severity):
                    store.mark_handled(rec["id"])
                from core.adjudication_narrative import schedule_narrative

                schedule_narrative(rec["id"], entry, self._pm, facts=facts)
            self._pm.logger.warning(
                "pm_engine",
                f"human-escalation-alert: {signal_type} for '{spec_name}'",
            )
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"Failed to send escalation alert for '{spec_name}': {e}",
            )
