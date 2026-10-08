"""repair_lane.py — P merge-back 修复车道（refactor-giant-classes D1/D3/D5/D6）。

原为 Dispatcher 的 9 个方法（`core/pm_engine/dispatch/_legacy.py`），
原样搬移为 mixin（方法体零改动）。跨组协作（_reconcile_and_merge /
_run_fast_track_flow 等 F 组）仍经宿主实例 `self.<method>` 协作。

D6 无环约束：本组 MUST NOT 直接 import `core.worktree_manager`
（现状经 `self._pm.agent_runner.<...>` 属性链间接访问，无边）。

D3 patch 缝隙更正（code-review item 01338d60b747）：测试注入确定性时钟走的是
**包命名空间** ``core.pm_engine.dispatch.time``（由 tests/test_repair_lane_dedup.py
patch.object 重绑），而非本模块的 ``repair_lane.time``——入队时刻的 ``time.time()``
实际在 ``queue.py`` 求值。故本模块不 import ``time``；docstring 旧称「本组使用
time 模块」与任何调用点都不符，已删除。同理本模块亦不参与 env-block/start-after
gate（``ENV_BLOCK_ROUNDS_FIELD``/``start_after_pending`` 仅 queue/fast_track 消费）。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from core.pm_engine.dispatch import (
    MAX_REPAIR_ROUNDS_PER_FAILURE,
)


def _merge_breaker_threshold(pm) -> int:
    """``agents.merge_breaker_threshold`` 读取与归一（单一落点）。

    归一规则（code-review item bba1be087ad5）：None 判空而非 or 兜底（对齐
    fast_track c54ffbef69c5，合法配置 0 不被 or 吞成缺省 2）→ TypeError/
    ValueError 回退缺省 2（code-review item a8c4f9dfc7a0：字符串/null 配置
    裸用于熔断比较抛 TypeError）→ ``max(..., 1)`` 下限保护（负数配置无意义，
    收敛到 1）。bool/小数显式拒绝（code-review item 4b349f62101e，对齐
    config._normalize_transient_seconds 归一口径）：裸 ``int()`` 会把
    ``true`` 截成 1、``1.5`` 截成 1，配置写坏静默改写熔断阈值——整值浮点
    （``2.0``）按整数接受，非法值回退缺省并经 ``pm.logger`` WARNING 留痕
    （logger 取 getattr 守卫，兼容仅注入 _get_config 的测试替身）。归一
    规则调整只改此处。

    注：queue.py ``_handle_merge_back_real_failure`` 的同型第三处复制亦已
    改为本读取器的调用点（code-review item bba1be087ad5），三处调用点同源。
    """
    default = 2
    try:
        cfg_threshold = pm._get_config("agents.merge_breaker_threshold", 2)
    except (TypeError, ValueError):
        cfg_threshold = None
    threshold = default
    illegal = False
    # [fenix-ignore:e2ec7ebc8aed] 清单快照过期：布尔/小数拒绝已由 item 4b349f62101e 在下方 isinstance 守卫落地（回退缺省 2），与 config.get_admin_config 同口径。
    if cfg_threshold is not None and not isinstance(cfg_threshold, bool):
        if isinstance(cfg_threshold, int):
            threshold = cfg_threshold
        elif isinstance(cfg_threshold, float):
            # 小数拒绝——int() 截断会静默改写熔断阈值（item 4b349f62101e）。
            if cfg_threshold.is_integer():
                threshold = int(cfg_threshold)
            else:
                illegal = True
        else:
            try:
                threshold = int(str(cfg_threshold).strip())
            except (TypeError, ValueError):
                illegal = True
    elif cfg_threshold is not None:
        illegal = True
    if illegal:
        logger = getattr(pm, "logger", None)
        if logger is not None:
            logger.warning(
                "pm_engine",
                "配置 agents.merge_breaker_threshold 非法（应为整数，"
                f"布尔/小数/非数字均不合法）: {cfg_threshold!r}，回退缺省 {default}",
            )
    # 下限保护：负数配置无意义，收敛到 1。
    return max(threshold, 1)


def _max_retries(pm) -> int:
    """``agents.max_retries`` 读取与归一（三条车道单一落点）。

    归一规则（code-review item 8b26fd7980ce）：同一配置键的归一曾在三条
    车道分裂——queue.py 两处读取点 int 归一后追加 ``max(..., 1)`` 下限，
    本文件 ``_fallback_after_repair`` 与 fast_track.py 两处读取点均无下限，
    配置写 0 时 full 车道按 1 生效（仍允许一轮重试）、fast-track/repair
    按 0 生效（首次失败即冻结转人工），同键跨车道语义互相矛盾。收敛于此：

    - None 判空回缺省 3，而非 ``or`` 兜底（合法配置 0 不被吞成缺省，
      code-review item c54ffbef69c5）；
    - 解析异常回退缺省 3（字符串/null 配置裸用于 ``retries >= max_r``
      比较抛 TypeError，code-review item 74317ab4a77a；``except Exception``
      宽口径沿用原 queue.py 通用失败分支与本文件 fallback 的防御姿态——
      本读取器的消费点全在失败收尾链，异常会打断 update_spec/冻结收尾）；
    - **下限策略：无下限**——0 的语义以 fast_track.py 既有注释为准
      （0=不自动重试为合法语义，首次失败即冻结转人工），``max(..., 1)``
      会违背之。归一规则调整只改此处，三条车道共用（queue/fast_track
      经模块顶部导入本读取器，与 ``_merge_breaker_threshold`` 同型）。
    """
    try:
        cfg_max_r = pm._get_config("agents.max_retries", 3)
    except Exception:  # noqa: BLE001 —— 失败收尾链防御，回退缺省不抛穿
        cfg_max_r = None
    if cfg_max_r is None:
        return 3
    # bool 显式拒绝（code-review item 637ed7beaee1，与 _merge_breaker_threshold
    # 同族归一）：裸 int() 把 true/false 截成 1/0 静默生效——true 使重试上限
    # 变 1（首次失败即冻结转人工）、false 得 0，配置写坏被无声采信且无留痕。
    if isinstance(cfg_max_r, bool):
        logger = getattr(pm, "logger", None)
        if logger is not None:
            logger.warning(
                "pm_engine",
                "配置 agents.max_retries 非法（布尔不合法），"
                f"回退缺省 3: {cfg_max_r!r}",
            )
        return 3
    # 小数显式拒绝（code-review item b5544dd00582，对齐 _merge_breaker_threshold
    # 的 float 分支）：裸 int() 把 2.5 截成 2 静默采信且无留痕，而字符串
    # "2.5" 走下方异常分支回退缺省 3——同值不同型行为分裂。整值浮点
    # （2.0）按整数接受，非整值 WARNING 留痕回退缺省 3。
    if isinstance(cfg_max_r, float):
        if cfg_max_r.is_integer():
            return int(cfg_max_r)
        logger = getattr(pm, "logger", None)
        if logger is not None:
            logger.warning(
                "pm_engine",
                "配置 agents.max_retries 非法（应为整数，小数不合法），"
                f"回退缺省 3: {cfg_max_r!r}",
            )
        return 3
    try:
        return int(cfg_max_r)
    except Exception:  # noqa: BLE001 —— 同上
        return 3


class PRepairLaneMixin:
    """P merge-back 修复车道（design D1 表 B P 组）。"""

    def _direct_rehearsed_to_repair(
        self, spec_name: str, merge_info, branch: str, merge_error: str
    ) -> None:
        """预演语义冲突直通 repair（add-merge-tree-rehearsal D2/D5）。

        implementer 与 fast-track 失败分支共用：merge-tree 预演已在主树零污染点
        检出语义冲突（``rehearsed=True``）——真合并从未发生，``_merge_fp``/
        ``_merge_streak`` 记账与 ready 降级在此路径均无意义（fp 熔断的职责——
        阻断「根因不消除→整轮重跑→再败」循环——由 repair 轮次上限承接）。
        spec 保持 in-flight，repair agent 在实现分支内把 main 合入解决冲突。

        轮次兜底（D5）：``_should_enter_repair`` 拒绝（已 blocked / ``_repair_round``
        超限）时回退现行 fallback 重派路径（prompt 注入冲突上下文），不产生无限
        repair 循环；repair 后 re-merge 失败链仍走既有 fp 熔断（本方法不动熔断语义）。
        """
        # 配置侧 int() 归一（code-review item a8c4f9dfc7a0，对齐 fast_track
        # 同键 74317ab4a77a 治理）：字符串/null 配置裸用于熔断比较抛
        # TypeError，被 worker 外层兜底放大成派发回滚——非法值回退缺省。
        # 归一规则单一落点（code-review item bba1be087ad5）：见模块级
        # _merge_breaker_threshold。
        breaker_threshold = _merge_breaker_threshold(self._pm)
        if self._pm._should_enter_repair(spec_name, merge_info, 0, breaker_threshold):
            # conflict_paths 统一 getattr 守卫（code-review item c1e84fcc2afd）：
            # merge_info 非 MergeConflictInfo 形态（测试替身/未来重构）时
            # 不因裸取属性抛 AttributeError 中断直通 repair 分支。
            conflict_paths = list(getattr(merge_info, "conflict_paths", []) or [])
            # 主树在飞修订根因透传（evo-inflight-spec-amendment-watch 1.3）：
            # merge-back 侧检出 spec/changes/<spec>/ 的主树已提交修订时，
            # merge_info.amended_inflight 携带修订提交短哈希列表——随 merge_info
            # 经 _dispatch_repair_lane → _run_repair_worker →
            # _repair_conflict_summary 下行进 repair prompt（「主树在飞修订根因」
            # 段），repair 直接带根因，消除考古成本。同款 getattr 守卫：旧形态
            # merge_info（测试替身/无字段）按未命中处理。
            amended = list(getattr(merge_info, "amended_inflight", []) or [])
            root_note = (
                f"，含主树在飞修订 {len(amended)} commit(s) {amended}"
                f"（根因随上下文透传 repair prompt）"
                if amended
                else ""
            )
            self._pm.logger.info(
                "pm_engine",
                f"预演检出语义冲突直通 repair '{spec_name}'："
                f"{len(conflict_paths)} path(s) "
                f"{conflict_paths} — 主树零污染，"
                f"不经 fp 记账（rehearsed）{root_note}",
            )
            self._pm._dispatch_repair_lane(spec_name, merge_info, branch)
        else:
            self._pm.logger.info(
                "pm_engine",
                f"预演检出语义冲突但 repair 不可用 '{spec_name}'"
                f"（轮次超限/已 blocked）— 回退 fallback 重派（rehearsed，"
                f"prompt 注入冲突上下文）",
            )
            # code-review item eeb49d9c68dd：此分支 repair 被拒（轮次超限/已
            # blocked），从未派发 repair agent——merge_error 须落 merge_error
            # 形参，repair_error 只写「repair 不可用」事实，避免 STATE error
            # 被误标为 repair 失败误导排障。
            self._fallback_after_repair(
                spec_name,
                branch,
                repair_error="预演检出语义冲突且 repair 不可用",
                merge_error=merge_error,
            )

    def _should_enter_repair(
        self, spec_name: str, merge_info, streak: int, breaker_threshold: int
    ) -> bool:
        """merge-back 失败后是否进入 repair 通道（语义冲突 + 熔断未触发 + 未超轮次）。

        判定依据（spec-mergeback-inplace-repair）：
        - merge_info 携带结构化冲突分类（D1）；
        - 全部冲突路径均为构建产物且自愈成功时（success=True）不会走到这里——
          调用方仅在 ``not merge_ok`` 分支内调用；
        - 冲突含语义文件（has_semantic_conflict）→ 产物/ignored-DU 自愈均不适用；
        - 熔断未触发（streak < threshold）：blocked spec 不再派发 repair；
        - 同一失败链内 repair 未超轮次（_repair_round < MAX_REPAIR_ROUNDS_PER_FAILURE）。
        """
        # 语义冲突判据（code-review item ea9b5b370bcf）：旧注释声称「兼容
        # (bool, str) 元组调用」，但 getattr(tuple, "has_semantic_conflict", False)
        # 恒为 False——元组入参会无条件禁用 repair（静默落 fallback），该兼容
        # 声明从未成立、且会误导后续调用方。此处删除误导性声明，如实说明：仅
        # 具 has_semantic_conflict 属性的 MergeConflictInfo 才进入 repair 通道。
        info_has_semantic = bool(getattr(merge_info, "has_semantic_conflict", False))
        if not info_has_semantic:
            return False
        try:
            spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        except Exception:
            spec_entry = {}
        if spec_entry.get("status") == "blocked":
            return False
        if streak >= breaker_threshold:
            return False
        try:
            repair_round = int(spec_entry.get("_repair_round", 0) or 0)
        except (TypeError, ValueError):
            repair_round = 0
        return repair_round < MAX_REPAIR_ROUNDS_PER_FAILURE

    def _dispatch_repair_lane(
        self, spec_name: str, merge_info, branch: str, fp: str | None = None, streak: int = 0
    ) -> bool:
        """进入 repair 通道：三态解析载体 → 认领现场 → 派发 repair worker。

        返回值（code-review item ec22643fa99a 锁移交标记）：True 表示已认领
        现场并启动新一轮 repair worker（``{spec}:repair`` 锁已移交给新
        worker）；False 表示未派发（冷却/超限/载体缺失/线程启动失败等早退
        路径，均未重新认领锁，上一轮 worker 可安全释放自己那轮的锁）。

        载体三态（design D3，以 git 事实为判定基准）：
        (a) 原 worktree 存在 → 原地进入（保留 node_modules/构建缓存）；
        (b) worktree 已清但分支存在 → 换壳：在分支上新建 worktree；
        (c) 分支不存在 → 回退 fallback 全新重派（prompt 注入 merge 失败上下文）。

        轮次控制（D5/D6）：``_repair_round`` 在派发前递增并持久化；本方法作为
        兜底在此**再次**校验轮次上限（code-review item 2a26974066a9：docstring
        旧称「超限不派发…此处兜底回退」，但旧实现无条件递增派发，任何绕过
        ``_should_enter_repair`` 的直呼调用都可超预算）。超限 → 回退 fallback
        全新重派，不再发起 repair 轮。
        """
        wm = self._pm.agent_runner.worktree_manager
        # cli-retry-backoff 2.2：秒挂冷却期内不派发 repair（repair agent 同样会秒挂）。
        # spec 保持原状，冷却到期由恢复定时器 / full_scan 重新唤起实现派发。
        if self._pm._instant_fail_cooled(spec_name):
            self._pm.logger.debug(
                "pm_engine",
                f"秒挂冷却中，跳过 repair 派发 '{spec_name}'（冷却期后恢复调度）",
            )
            self._schedule_instant_fail_recovery(spec_name)
            return False
        # evo-sigterm-source-tracking-cooldown：信号死法冷却期内不派发 repair。
        # 与秒挂冷却并存：两条通道各自排程恢复，取更晚的冷却截止生效。
        if self._pm._signal_kill_cooled(spec_name):
            self._pm.logger.debug(
                "pm_engine",
                f"信号死法冷却中，跳过 repair 派发 '{spec_name}'"
                f"（冷却期后恢复调度）",
            )
            self._schedule_signal_kill_recovery(spec_name)
            return False
        try:
            repair_round = int(
                (self._pm.state_machine.read_one(spec_name) or {}).get("_repair_round", 0) or 0
            )
        except (TypeError, ValueError):
            repair_round = 0
        # 兜底轮次上限（code-review item 2a26974066a9）：正常路径由
        # _should_enter_repair 前置拦截；此处防御直呼/旁路调用不得超预算。
        if repair_round >= MAX_REPAIR_ROUNDS_PER_FAILURE:
            self._pm.logger.warning(
                "pm_engine",
                f"repair 轮次已达上限（{repair_round}/{MAX_REPAIR_ROUNDS_PER_FAILURE}）"
                f"'{spec_name}' — 兜底回退 fallback 全新重派",
            )
            # code-review item 8e379d862123：从未派发本轮 repair——merge 错误
            # 须落 merge_error 形参，repair_error 只写「轮次超限」事实，避免
            # STATE error 被误标为 repair 失败、真实 merge 上下文被占位符替换。
            self._fallback_after_repair(
                spec_name,
                branch,
                repair_error="repair 轮次超限",
                merge_error=getattr(merge_info, "error", "") or "",
            )
            return False
        # 分支消亡 → fallback（三态 (c)）
        if not branch or not wm.branch_exists(branch):
            self._pm.logger.warning(
                "pm_engine",
                f"repair 载体分支 '{branch}' 不存在 — 回退 fallback 全新重派",
            )
            # code-review item 46859c50e0a5：此分支 repair agent 从未派发
            # （载体解析即失败）——merge 错误须落 merge_error 形参，
            # repair_error 只写「载体不存在」事实，避免 STATE error 被误标
            # 为 repair 失败、真实 merge 上下文被占位符替换。
            self._fallback_after_repair(
                spec_name,
                None,
                repair_error="repair 载体分支不存在",
                merge_error=getattr(merge_info, "error", "") or "",
            )
            return False
        # 三态解析：原地 / 换壳
        wt_path, resolved_branch = wm.resolve_repair_site(spec_name, branch)
        if wt_path is None:
            self._pm.logger.warning(
                "pm_engine",
                f"repair 载体解析失败（分支 '{branch}' 不可用）— 回退 fallback",
            )
            # code-review item 46859c50e0a5：同上，repair agent 从未派发——
            # merge 错误落 merge_error 形参，repair_error 只写事实文案。
            self._fallback_after_repair(
                spec_name,
                branch,
                repair_error="repair 载体解析失败",
                merge_error=getattr(merge_info, "error", "") or "",
            )
            return False
        # 认领现场（D4）：_legacy take 摘出 + _spec_locks 注册，防 sweeper 宽限期回收
        # code-review item 94d6ad914d0b：认领先于线程启动，先留存认领前 legacy
        # 记录——Thread 启动失败回滚时按原记录恢复（claim_legacy_for_repair
        # 摘出即不还）。
        legacy_rec = None
        if hasattr(wm, "_legacy"):
            legacy_rec = wm._legacy.get(spec_name)
        self._pm._claim_repair_site(spec_name, wt_path, resolved_branch)
        # 轮次递增（D5/D6）：repair 轮计入该 spec 的实现预算（token 记名下）；
        # 连续计数 _merge_fp/_merge_streak 不被 repair 轮清零（熔断协同）。
        round_no = repair_round + 1
        # ── 基准 tip 记录（fix-repair-commit-enforcement D2）─────────────
        # repair 派发前记录分支 tip，repair 后 worker 复核「tip 是否前进」。
        # 与 _repair_round/_repair_merge_fp 同处一次 update_spec 落盘，
        # 语义一致（统一 repair 轮次元数据）。
        # code-review item 5859406dd4b6：此处已认领现场（{spec}:repair 锁 +
        # legacy 摘除）而 _repair_round 尚未持久化，裸调一旦抛错会越过后方
        # 线程启动失败的局部回滚逃逸到调用方，认领残留无任何回滚。对齐同
        # 文件 _check_repair_commit_facts 的 branch_tip 既有守卫形态：失败
        # 降级 base_tip=None（复核对基准缺失本就跳过 tip 前进校验，保守
        # 放行）——不做认领回滚再 fallback（改动面更大，且降级语义即既有
        # 设计），仅消除逃逸窗口。
        try:
            base_tip = wm.branch_tip(resolved_branch)
        except Exception as e:
            base_tip = None
            self._pm.logger.warning(
                "pm_engine",
                f"repair 基准 tip 查询失败 '{spec_name}'"
                f"（按基准缺失降级，跳过 tip 前进校验）: {e}",
            )
        try:
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "_repair_round": round_no,
                    "_repair_merge_error": getattr(merge_info, "error", "") or "",
                    "_repair_merge_fp": fp,
                    "_repair_base_tip": base_tip,
                    # 进入下一轮 repair：上一轮若曾写入「待 re-merge」标记则一并清除
                    # （fix-recovery-branch-anchor D3 清除点 2/4）。
                    "_repair_awaiting_remerge": False,
                },
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"repair 轮次计数回写失败 '{spec_name}'（非阻塞）: {e}",
            )
        self._pm.logger.warning(
            "pm_engine",
            f"进入 repair 通道 '{spec_name}'（第 {round_no}/{MAX_REPAIR_ROUNDS_PER_FAILURE} 轮，"
            f"merge 失败 streak={streak}） worktree={wt_path} branch={resolved_branch}",
        )
        # code-review item 94d6ad914d0b：认领（{spec}:repair 锁 + legacy 认领
        # 摘除 + _repair_round 递增）已先于线程启动落位，Thread 构造/start 失败
        # （如环境性 RuntimeError can't start new thread）时 worker 的 finally
        # 永不执行，认领即悬置——对齐 ocr 车道守卫形态（queue.py，code-review
        # item b52d9c1760b6）：捕获失败、回滚本轮认领后按未派发语义返回 False。
        try:
            t = threading.Thread(
                target=self._pm._run_repair_worker,
                args=(spec_name, wt_path, resolved_branch, merge_info),
                daemon=True,
                name=f"fenix-repair-{spec_name}",
            )
            t.start()
        except Exception as e:  # noqa: BLE001 — 环境性启动失败按「未派发」处置
            # 回滚顺序对齐 _claim_repair_site 的登记项：{spec}:repair 锁
            # discard → legacy 认领恢复 → _repair_round 记账回退。
            # _wt_branches 无需回退——该映射在三态解析（resolve_repair_site）
            # 时已登记，认领处为幂等重写。
            if hasattr(wm, "_spec_locks"):
                wm._spec_locks.discard(f"{spec_name}:repair")
            if legacy_rec is not None and hasattr(wm, "_legacy"):
                wm._legacy[spec_name] = legacy_rec
            try:
                self._pm.state_machine.update_spec(
                    spec_name, {"_repair_round": repair_round}
                )
            except Exception as e2:  # noqa: BLE001 — 记账回退失败仅留痕
                self._pm.logger.warning(
                    "pm_engine",
                    f"repair 轮次记账回退失败 '{spec_name}'（非阻塞）: {e2}",
                )
            self._pm.logger.warning(
                "pm_engine",
                f"repair 线程启动失败 '{spec_name}'（已回滚本轮认领，"
                f"按未派发处置）: {type(e).__name__}: {e}",
            )
            # code-review item 641365358807：回滚后补恢复安排（与超限/载体缺失
            # 早退路径同款 fallback 重派）——本方法四个调用点均不消费 False
            # 返回值安排重派，原行为 spec 悬置 implementing 且无活跃 run，只能
            # 等 admin_monitor stuck 阈值唤起人工。_repair_round 已在上方回退
            # 至派发前值，此处由 fallback 收尾统一归零。
            self._fallback_after_repair(
                spec_name,
                resolved_branch,
                repair_error=f"repair 线程启动失败（{type(e).__name__}）",
                merge_error=getattr(merge_info, "error", "") or "",
            )
            return False
        # 锁已移交给新 worker（code-review item ec22643fa99a）：此后调用方的
        # finally 不得再 discard 同名锁。
        return True

    def _claim_repair_site(self, spec_name: str, wt_path, branch: str) -> None:
        """认领 repair 现场（add-merge-back-repair-lane D4）。

        与 fast-track 复用同款 take 动作：认领时从 ``_legacy`` 摘出（防 sweeper
        宽限期按孤儿回收正在使用的现场）；在 ``_spec_locks`` 注册 repair 锁
        （防 repair 进行中重复派发）。worktree 已在三态解析时登记进活动集
        （``_active_worktrees``/``_wt_branches``），sweeper 不再豁免该目录。

        私有属性访问一致容错（code-review item bbb27ecdff1e / f916e16d044f）：
        ``_legacy``/``_spec_locks``/``_wt_branches`` 均经 ``hasattr`` 守卫——
        旧实现只守卫前两者，``_wt_branches`` 裸写；一旦 worktree_manager 实现
        变更或测试替身缺该属性，会在 ``claim_legacy_for_repair`` 已改写
        ``_legacy``（现场半认领）之后抛 AttributeError，留下不一致状态。
        """
        wm = self._pm.agent_runner.worktree_manager
        # 认领即摘出登记表（与 fast-track `_take_reusable_worktree` 同款 take）
        if hasattr(wm, "claim_legacy_for_repair"):
            wm.claim_legacy_for_repair(spec_name)
        elif spec_name in getattr(wm, "_legacy", {}):  # 兜底：直接摘出
            wm._legacy.pop(spec_name, None)
        if hasattr(wm, "_spec_locks"):
            wm._spec_locks.add(f"{spec_name}:repair")
        if branch and hasattr(wm, "_wt_branches"):
            wm._wt_branches[str(wt_path)] = branch

    def _run_repair_worker(self, spec_name: str, wt_path, branch: str, merge_info) -> None:
        """repair worker：派发 repair agent → re-merge-back → 状态推进。

        在守护线程内同步执行（与 implementer worker 同线程语义）。repair agent
        在实现分支一侧把 main 合入分支并解决冲突、commit；成功后框架对该分支
        重新执行 merge-back（分支已含 main 历史应快速前进）。

        熔断协同（D6）：re-merge-back 再失败时 ``_merge_fp``/``_merge_streak``
        连续累计（repair 轮不清零）；blocked 后不再派发 repair。
        """
        wm = self._pm.agent_runner.worktree_manager
        # 锁移交标记（code-review item ec22643fa99a）：True 表示 re-merge 失败后
        # 已链式派发下一轮 repair、其锁由新轮 _claim_repair_site 重新认领——
        # 本 worker 的 finally 只释放自己这轮的锁，不得摘掉新轮的锁。
        lock_handed_off = False
        try:
            repair_ok = False
            repair_error = ""
            r = None
            try:
                # code-review item a1563e2bce84：派发前清除上一轮结果文件
                # （陈旧结果防护，对齐 dispute-judge 路径 runner.py 的派发前
                # unlink 先例）：结果文件按 worktree 根固定路径跨轮复用且内容
                # 不带 run id，原地 repair 复用实现 worktree 时，上一轮实现
                # run 遗留的 status=error 结果文件若未被本轮 repair agent
                # 覆写，读取侧（下方）会把陈旧失败误判为本轮 repair 失败、
                # 触发多余的 fallback 全新重派。派发前 unlink 使「本轮未写 =
                # 文件不存在」；换壳全新 worktree 下文件本不存在，删除幂等。
                # 删除失败不阻断派发。
                try:
                    (Path(wt_path) / ".fenix-run-result.json").unlink(missing_ok=True)
                except OSError as e:
                    self._pm.logger.debug(
                        "pm_engine",
                        f"清除上一轮 repair 结果文件失败 '{spec_name}'"
                        f"（不阻断派发）: {e}",
                    )
                r = self._pm.agent_runner.run_repair(
                    spec_name,
                    wt_path,
                    conflict_summary=self._repair_conflict_summary(spec_name, merge_info),
                )
                # 读取 repair 结果文件（repair agent 在 worktree 写 .fenix-run-result.json）
                wt_result = Path(wt_path) / ".fenix-run-result.json"
                repair_ok = bool(r.success)
                if wt_result.exists():
                    try:
                        data = json.loads(wt_result.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            stamped = data.get("spec")
                            if stamped and stamped != spec_name:
                                repair_ok = False
                                repair_error = f"结果文件 spec 戳 '{stamped}' 与 '{spec_name}' 不符"
                            elif data.get("status") == "error":
                                repair_ok = False
                                repair_error = data.get("error") or "repair agent 显式报告失败"
                    except (json.JSONDecodeError, OSError) as e:
                        repair_ok = False
                        repair_error = f"repair 结果文件解析失败: {e}"
            except Exception as e:
                repair_ok = False
                repair_error = str(e)
                self._pm.logger.error(
                    "pm_engine",
                    f"repair agent 派发异常 '{spec_name}': {e}",
                )

            # ── 冻结终止 hold-state（add-freeze-stop-inflight-agents 3.3）──
            # repair run 被冻结终止：spec 保持原状（blocked），只写
            # _frozen_hold 标记 + error，不动 _retry_count/_merge_fp/
            # _merge_streak、不入队重派。
            # 判定用 `is True`（修复验证轮 BUG：MagicMock 替身自动生成
            # truthy 属性，裸布尔会误判；r=None（派发异常）时 getattr 取
            # 缺省 False）；生产结果 frozen_terminated 为显式 bool。
            if getattr(r, "frozen_terminated", False) is True:
                ft_err = getattr(r, "error", None) or repair_error or ""
                frozen_err = (
                    f"repair run 因 spec 冻结被终止（进度已保全，解冻后续做）"
                    f"{': ' + ft_err if ft_err else ''}"
                )
                self._pm.logger.warning(
                    "pm_engine",
                    f"repair run 因 spec 冻结被终止 — hold-state '{spec_name}'"
                    f"（保持原状）: {frozen_err}",
                )
                self._pm.state_machine.mark_frozen_hold(
                    spec_name, frozen_err)
                return

            # ── 人工取消 hold-state（add-run-cancel D4，repair worker）──
            # repair run 被取消：spec 保持原状（implementing），只写 error，
            # 不动 _retry_count/_merge_fp/_merge_streak、不入队重派。
            # 判定用 `is True`（code-review item 10bac9026b6a，与上方
            # frozen_terminated 同款防护）：MagicMock 替身自动生成 truthy
            # 属性，裸布尔会把测试替身误判为人工取消而落入 hold-state。
            if getattr(r, "cancelled", False) is True:
                r_err = getattr(r, "error", None) or repair_error or ""
                cancelled_err = f"run 被人工取消：{r_err}" if r_err else "run 被人工取消"
                self._pm.logger.warning(
                    "pm_engine",
                    f"repair run 被人工取消 — hold-state '{spec_name}'"
                    f"（保持原状）: {cancelled_err}",
                )
                self._pm.state_machine.update_spec(
                    spec_name,
                    {
                        "error": cancelled_err,
                        # 取消保持持久标记（fix-cancel-holdstate-recovery D1）。
                        "_cancelled_hold": True,
                    },
                )
                return

            # ── repair git 事实复核（fix-repair-commit-enforcement D1/D2）──
            # repair agent 声明 success 只是「声明」，worker 在此以分支 git 事实
            # 独立验证「repair 确实被落地」：① 分支 tip 相对派发前基准前进（至少
            # 一个新提交）；② worktree 内无未解决冲突；③ 不处于未完成 merge。
            # 任一不满足即判 repair 未完成，repair_error 携带具体事实注入
            # fallback 重派上下文（不再以笼统「merge-back failed」重派）。
            if repair_ok:
                facts_ok, fact_err = self._pm._check_repair_commit_facts(spec_name, wt_path, branch)
                if not facts_ok:
                    repair_ok = False
                    repair_error = fact_err
                    self._pm.logger.error(
                        "pm_engine",
                        f"repair git 事实复核未通过 '{spec_name}'：{fact_err}",
                    )

            if not repair_ok:
                # repair 失败/超时/显式失败 → 回退 fallback 全新重派（原分支按既有
                # 清扫策略处理：登记遗产供后继 run 参考）
                self._fallback_after_repair(
                    spec_name,
                    branch,
                    repair_error,
                    merge_error=getattr(merge_info, "error", "") or "",
                )
                return

            # repair 成功：对分支重新执行 merge-back（分支已含 main 历史）
            self._pm._reconcile_impl_budget(spec_name)
            # ── 锚点提前落盘（fix-recovery-branch-anchor D1）─────────
            # repair run 终态成功后、re-merge-back 之前写入 branch/implementer_run，
            # 使恢复链在「repair 成功待 re-merge」窗口内可命中实现分支。
            # 同时写入 _repair_awaiting_remerge 标记（D3），标识「仅剩合并」。
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "branch": branch,
                    "implementer_run": getattr(r, "run_id", None) or None,
                    "_repair_awaiting_remerge": True,
                },
            )
            self._pm.logger.info(
                "pm_engine",
                f"锚点已提前落盘（repair）'{spec_name}': "
                f"branch={branch}, _repair_awaiting_remerge=True",
            )
            remerge_info = wm.merge_back_from_branch(branch)
            remerge_ok, remerge_error = remerge_info

            if remerge_ok:
                # 成功尾段单独包 try/except（code-review item 6a553a71ac8a）：
                # 此段任一 IO 类异常若外溢到 worker 的外层 except，会被兜底成
                # _fallback_after_repair 全新重派——而此时 re-merge 已成功、
                # 分支已并入 main、锚点已写，白烧一轮实现 run。尾段异常改走
                # 下方恢复路径（保留 implemented 锚点 + verifier 重入队）。
                try:
                    # 链成功：回收 repair worktree，推进 implemented
                    # ── 顺序修复（fix-recovery-branch-anchor D1 1.4）───────
                    # update_spec(branch=...) MUST 先于 wm.cleanup 执行
                    # （先写锚点载体、后删 worktree，happy path 上不留窗口）。
                    # fix-observability-gaps 2.2：repair re-merge 成功 → implemented
                    # 合并收尾 ready 态兜底（evo-spec-concurrency-flight-guard D3）：
                    # status=ready（评审收尾竞态回退残留）时先补记 ready→implementing，
                    # 再推进 implemented（消除 ready→implemented 非法转移 ERROR）。
                    self._pm._merge_ready_fallback(
                        spec_name,
                        getattr(r, "run_id", None) or None,
                        "repair",
                        branch,
                    )
                    # transition 返回值校验（code-review item a5e1c9319ad4，
                    # 对齐 fast_track.py _reconcile_and_merge 的 40292d21fd97
                    # 同型收口）：上方读态/fallback 与 implemented 转移之间存在
                    # 窗口，并发写者可能已把 spec 推进/冻结（非法转移返回
                    # False）。失败时保留计数与 error 原样、不继续清字段并入队
                    # verifier——否则清账照常落盘（冻结 error 内嵌「原状态 X」
                    # 供 parse_orig_status 解冻还原的锚点被 None 覆盖），且排入
                    # 一条永不满足派发前置的 verifier 条目。
                    if not self._pm.state_machine.transition(
                        spec_name, "implemented",
                        trigger_run_id=getattr(r, "run_id", None) or None,
                        agent_type="repair", channel="auto",
                    ):
                        self._pm.logger.warning(
                            "pm_engine",
                            f"repair re-merge 成功但 transition 到 implemented "
                            f"失败（并发写者已推进/冻结），保留计数与 error 现场"
                            f"待收口重试/审计: {spec_name}",
                        )
                        return
                    self._pm.state_machine.update_spec(
                        spec_name,
                        {
                            "implementer_run": getattr(r, "run_id", None) or None,
                            "branch": branch,
                            "error": None,
                            "_retry_count": 0,
                            "_merge_fp": None,
                            "_merge_streak": 0,
                            "_repair_round": 0,
                            "_repair_merge_error": None,
                            # repair 链成功收口：基准 tip 随 _repair_round 一并清零
                            # （fix-repair-commit-enforcement 1.4），避免 stale 基准残留。
                            "_repair_base_tip": None,
                            "_repair_awaiting_remerge": False,
                            **self._pm._clear_dispatch_conflict(spec_name),
                        },
                    )
                    # 锚点已落盘（branch/implementer_run 已写入 STATE），此时才清理
                    # repair worktree 载体（1.4 顺序修复：先写锚点、后删载体）。
                    # dev-server 收割经门面单跳（code-review item 227d772b3847）。
                    try:
                        self._pm._stop_devserver_for_worktree(wt_path)
                    except Exception:
                        pass
                    try:
                        wm.cleanup(wt_path, success=True)
                    except Exception as e:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"repair worktree 清理失败 '{spec_name}'（非阻塞）: {e}",
                        )
                    try:
                        self._pm._sync_task_progress(spec_name)
                    except Exception as e:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"repair 任务进度回写失败 '{spec_name}'（非阻塞）: {e}",
                        )
                    try:
                        wm.consume_legacy(spec_name)
                    except Exception as e:
                        # 失败不再静默吞掉（code-review item 8fde33e82e7b）：与
                        # fast_track.py / queue.py 的等价调用同款非阻塞 WARNING，
                        # 使持续的 legacy 清理失败在本车道可观测（fail-open 但可见）。
                        self._pm.logger.warning(
                            "pm_engine",
                            f"consume_legacy 清理失败 '{spec_name}'（非阻塞）: "
                            f"{type(e).__name__}: {e}",
                        )
                    # verify 单飞守卫（evo-add-verify-dispatch-single-flight 1.3）：
                    # repair 链成功尾段经 _enqueue_front 入队，与 spec_implemented
                    # 事件/admin 复位直通道共用同一守卫入口——同 spec 已有在飞
                    # 验证时此处为空操作（_enqueue_front 内拒绝＋结构化留痕），
                    # 在飞 run 收工后由既有通道重新入队。
                    self._enqueue_front(spec_name, "verifier")
                    self._pm.logger.info(
                        "pm_engine",
                        f"repair 链成功：'{spec_name}' re-merge-back 完成 → implemented",
                    )
                    return
                except Exception as tail_e:
                    # code-review item 6a553a71ac8a：成功尾段异常不转
                    # _fallback_after_repair——bump _retry_count 强制 ready 全新
                    # 重派会白烧已成功的实现 run，且该路径无 queue.py:2735-2755
                    # 式在飞状态回写保护，可能把已推进的 implemented 锚点覆盖回
                    # ready。恢复口径：保留 implemented 锚点，best-effort 补齐
                    # 收口后重入队 verifier（transition 对非法转移仅 WARNING +
                    # False 不抛异常，已推进时幂等短路，重复补推无副作用）。
                    self._pm.logger.error(
                        "pm_engine",
                        f"repair 链成功尾段异常 '{spec_name}'（re-merge 已成功，"
                        f"不回退重派，转 verifier 重入队恢复）: "
                        f"{type(tail_e).__name__}: {tail_e}",
                    )
                    try:
                        self._pm.state_machine.transition(
                            spec_name, "implemented",
                            trigger_run_id=getattr(r, "run_id", None) or None,
                            agent_type="repair", channel="auto",
                        )
                    except Exception as e2:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"成功尾段异常恢复：补推 implemented 失败 "
                            f"'{spec_name}'（非阻塞）: {e2}",
                        )
                    try:
                        # best-effort 补齐收口字段（与成功尾段 update_spec 同族
                        # 复位，含 _clear_dispatch_conflict 锁冲突收口；已写过的
                        # 字段幂等重写无害）。写面与成功尾段一致，仅触发时机不同。
                        self._pm.state_machine.update_spec(
                            spec_name,
                            {
                                "implementer_run": getattr(r, "run_id", None) or None,
                                "branch": branch,
                                "error": None,
                                "_retry_count": 0,
                                "_merge_fp": None,
                                "_merge_streak": 0,
                                "_repair_round": 0,
                                "_repair_merge_error": None,
                                "_repair_base_tip": None,
                                "_repair_awaiting_remerge": False,
                                **self._pm._clear_dispatch_conflict(spec_name),
                            },
                        )
                    except Exception as e3:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"成功尾段异常恢复：收口字段回写失败 "
                            f"'{spec_name}'（非阻塞）: {e3}",
                        )
                    try:
                        # verify 单飞守卫同上（evo-add-verify-dispatch-single-flight
                        # 1.3）：异常恢复尾段与成功尾段共用 _enqueue_front 守卫入口。
                        self._enqueue_front(spec_name, "verifier")
                    except Exception as e4:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"成功尾段异常恢复：verifier 重入队失败 "
                            f"'{spec_name}'（等 full_scan 周期兜底）: {e4}",
                        )
                    return

            # re-merge-back 再失败：与首次 merge 失败同路径处理（熔断计数连续累计），
            # repair 轮不清零 _merge_fp/_merge_streak（spec-merge-circuit-breaker）。
            # 返回 True = 已续链派发下一轮 repair（锁已由新轮重新认领）。
            lock_handed_off = bool(
                self._pm._handle_remerge_failure(spec_name, remerge_info, branch)
            )

        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"repair worker 异常 '{spec_name}': {e}",
            )
            # verify-process-lifecycle（D3 dispatch 兜底）：hand-off 边界内异常
            # 时收割 repair 载体 worktree 的 dev-server 注册条目（run_repair 的
            # runner 收割因 repair 属 handed_off 而跳过）。幂等，双调无害。
            # dev-server 收割经门面单跳（code-review item 227d772b3847）。
            try:
                self._pm._stop_devserver_for_worktree(Path(wt_path))
            except Exception:
                pass
            self._fallback_after_repair(
                spec_name,
                branch,
                str(e),
                merge_error=getattr(merge_info, "error", "") or "",
            )
        finally:
            # 释放 repair 锁（_spec_locks 中 {spec}:repair 条目）。
            # 锁移交豁免（code-review item ec22643fa99a）：链式派发下一轮时
            # _claim_repair_site 已为新轮重新注册同名锁，此处不得 discard——
            # 否则新轮 repair 全程无锁，防重复派发与 sweeper 孤儿回收两项
            # 保护同时失效。未续链（fallback/熔断/hold-state/异常）才释放。
            if not lock_handed_off:
                try:
                    wm._spec_locks.discard(f"{spec_name}:repair")
                except Exception:
                    pass
            self._pm._process_queue()

    # ── repair git 事实复核（fix-repair-commit-enforcement D1/D2/D5）──────

    def _check_repair_commit_facts(self, spec_name: str, wt_path, branch: str) -> tuple[bool, str]:
        """repair git 事实复核：分支 tip 前进 + 无冲突残留 + 无未完成 merge。

        repair agent 的 success 是「声明」，worker 在此以分支 git 事实独立验证
        「repair 确实被落地」。复核逻辑为**可测试的纯组合判定**（D5）：只读
        查询委托 worktree_manager（``branch_tip`` / ``repair_site_facts``），
        组合判定在此方法内完成——单测可注入 mock worktree_manager 覆盖四态
        （tip 未前进 / 有未合并条目 / 有 MERGE_HEAD / 全 ok），沿用
        ``test_mergeback_repair_lane.py`` 的临时仓库夹具风格。

        判定规则（任一不满足 → 判未完成）：
        - ``repair_site_facts.unmerged`` 非空 → 未解决冲突残留；
        - ``repair_site_facts.merge_head`` 为 True → 仍处于未完成 merge；
        - 基准 ``_repair_base_tip`` 可判且 ``branch_tip(branch)`` 查询成功时，
          ``now_tip == base_tip`` → 分支 tip 未前进（可能只暂存未提交）。
        ``_repair_base_tip`` 缺失（老状态迁移或查询失败），或 check 时刻
        ``branch_tip`` 查询失败（异常，或超时/OSError 在 worktree_manager
        内部降级为 None）时跳过 tip 前进校验，仅查冲突残留 + MERGE_HEAD
        （保守放行，不引入新假阴性硬门——只读层的失败一律按保守原则处理，
        与同函数 repair_site_facts 查询侧 fail-open 口径一致；查询成功且
        tip 等于基准才判未前进）。

        Returns:
            ``(ok, error_text)``：ok=True 表示复核通过；ok=False 时
            error_text 携带可诊断事实（如 tip SHA、未合并条目计数、MERGE_HEAD
            有无），供 ``_fallback_after_repair`` 注入下一轮重派上下文。
        """
        wm = self._pm.agent_runner.worktree_manager
        # ── 查询侧（D2：只读，不新增 worktree 写操作）──
        try:
            facts = wm.repair_site_facts(wt_path)
        except Exception as e:
            facts = {}
            self._pm.logger.warning(
                "pm_engine",
                f"repair git 事实查询异常（fail-open 防误拦）'{spec_name}': {e}",
            )
        unmerged = list(facts.get("unmerged") or [])
        merge_head = bool(facts.get("merge_head"))
        # ── 冲突残留 / MERGE_HEAD 是硬事实，任一出问题即判未完成 ──
        if unmerged or merge_head:
            parts = []
            if unmerged:
                shown = ", ".join(unmerged[:3])
                tail = "…" if len(unmerged) > 3 else ""
                parts.append(f"未解决冲突残留 {len(unmerged)} 个文件" f"（{shown}{tail}）")
            if merge_head:
                parts.append("存在未完成 merge（MERGE_HEAD）")
            return False, f"repair git 事实复核未通过：{'; '.join(parts)}"
        # ── tip 前进校验（基准可判时，D2）──
        try:
            base_tip = (self._pm.state_machine.read_one(spec_name) or {}).get("_repair_base_tip")
        except Exception:
            base_tip = None
        if base_tip:
            now_tip = None
            tip_err = ""
            try:
                now_tip = wm.branch_tip(branch)
            except Exception as e:
                tip_err = str(e)
            if now_tip is None:
                # 查询失败降级（code-review item 03344b76fd8e）：异常或
                # branch_tip 内部超时/OSError 降级 None 均跳过 tip 前进校验
                # （保守放行），不按「未前进」fail-closed——瞬时 git 故障
                # （锁竞争/仓库短暂不可用）误判会烧掉一整轮已成功落地的
                # 实现 run；对齐 branch_tip 契约「调用侧据此跳过校验」与
                # 本方法 docstring「只读层失败按保守原则处理」。未完成的
                # repair 仍由冲突残留/MERGE_HEAD 硬事实兜底，后续
                # re-merge-back 真实执行合并，假阳性不会漏网。
                self._pm.logger.warning(
                    "pm_engine",
                    f"repair 分支 tip 查询失败（{tip_err or 'branch_tip 返回 None'}），"
                    f"跳过 tip 前进校验（保守放行）'{spec_name}'",
                )
            elif now_tip == base_tip:
                base_short = base_tip[:12]
                now_short = now_tip[:12]
                return False, (
                    f"repair git 事实复核未通过：分支 tip 未前进"
                    f"（base={base_short}, now={now_short}）"
                    f"——repair 声称成功但分支无新提交，可能只暂存未提交"
                )
        return True, ""

    def _handle_remerge_failure(self, spec_name: str, remerge_info, branch: str) -> bool:
        """repair 后的 re-merge-back 失败：熔断 → repair 下一轮 → fallback。

        与首次 merge-back 失败同判定基准（fp/streak 连续累计，repair 不重置），
        轮次超过上限回退 fallback。不重复 testing/implemented 保护检查——
        repair 链内 spec 保持 implementing，无在飞 tester。

        返回值（code-review item ec22643fa99a 锁移交标记）：True 表示已链式
        派发下一轮 repair（``{spec}:repair`` 锁由新轮重新认领，worker 的
        finally 不得释放）；False 表示未续链（熔断/顺延/fallback，锁可释放）。
        """
        merge_error = getattr(remerge_info, "error", "") or str(remerge_info)
        # ── WIP 重叠闸门阻塞旁路（evo-merge-back-wip-overlap-gate D3）──
        # repair 后 re-merge-back 同样可能被主树 WIP 重叠闸门阻塞（repair 期间
        # 主树出现新 WIP 与分支改动重叠）：阻塞是前置拦截而非 merge 失败，主树
        # 未被 stash/merge/pop 触碰——不经 _merge_fp/_merge_streak 记账、不
        # blocked、不进 repair 轮，spec 保持 in-flight，仅直发告警等待人工处置。
        if getattr(remerge_info, "wip_gate_blocked", False):
            self._report_mergeback_wip_overlap(spec_name, remerge_info, branch, merge_error)
            return False
        # ── spec 目录在飞编辑顺延（evo-merge-back-spec-dir-inflight-guard D1/D1a；
        # code-review item 4d8a36d16d39，repair 车道对齐 full/fast-track 车道
        # _defer_merge_back）── repair 后 re-merge-back 被卫检查顺延
        # （spec_dir_inflight=True）：主树 spec 目录有未提交改动。MUST NOT 消费
        # _repair_awaiting_remerge 标记——原样保留（清除会让「仅剩合并」的分支
        # 退回 ready 全新派发）。亦不经 fp 记账/blocked/repair 轮（顺延不是 merge
        # 失败）。与 full 车道同语义：写 _merge_retry_pending 记账 + 排程
        # merge-only 重试（_retry_merge_back_only 按 branch 锚点通用实现，天然
        # 覆盖 repair 车道），有界顺延自动重试合并；窗口/轮数超限由
        # _defer_merge_back 内部回落「告警 + 人工处置」通道
        # （_report_mergeback_spec_dir_inflight_stuck）。MUST NOT 在飞顺延零重试
        # ——原行为 spec 悬置 implementing 且无活跃 run，只能等 admin_monitor
        # stuck 阈值唤起人工，三条车道有界性不对称。
        if getattr(remerge_info, "spec_dir_inflight", False):
            self._pm.logger.warning(
                "pm_engine",
                f"repair 后 re-merge-back 顺延 '{spec_name}'（branch '{branch}'）: "
                f"{merge_error} — spec 目录在飞编辑，保留 _repair_awaiting_remerge，"
                f"写顺延记账并排程 merge-only 重试（不消费标记、不重派）",
            )
            self._defer_merge_back(spec_name, remerge_info, branch, merge_error)
            return False
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        fp = self._pm._merge_fingerprint(merge_error)
        prev_fp = spec_entry.get("_merge_fp")
        # _merge_streak 走锁内原子递增（bump_counters 返回写后值参与阈值判定，
        # 同型修复见 queue.py _handle_merge_back_real_failure，code-review item
        # 6c89067c172a）：原先「read_one 读 → 算 +1 → 并进 update_spec 写回」读与
        # 写分处两次 STATE 锁临界区，merge-only 重试通道并发进入同一 spec 时各持
        # 相同旧值写回、丢一次递增，同指纹熔断晚一轮触发。指纹切换属重置语义
        # （绝对写 1，无丢增量面），不 bump、随后续 update_spec 落盘。
        if prev_fp == fp:
            streak = self._pm.state_machine.bump_counters(
                spec_name, {"_merge_streak": 1}
            ).get("_merge_streak", 0)
            streak_bumped = True
        else:
            streak = 1
            streak_bumped = False
        final_error = f"Merge-back failed (fp={fp}): {merge_error}"
        # 配置侧 int() 归一（code-review item a8c4f9dfc7a0，对齐 fast_track
        # 同键 74317ab4a77a 治理）：字符串/null 配置裸用于比较抛 TypeError
        # 中断 merge 失败处置，非法值回退缺省。归一规则单一落点
        # （code-review item bba1be087ad5）：见模块级 _merge_breaker_threshold
        # （下限 1：streak 自 1 起计，threshold<=1 均为首次失败即熔断）。
        breaker_threshold = _merge_breaker_threshold(self._pm)
        if streak >= breaker_threshold:
            # fix-observability-gaps 2.2：repair re-merge 熔断 blocked（自动降级路径）
            # transition 返回值校验（code-review item a5e1c9319ad4，对齐
            # fast_track.py _reconcile_and_merge 的 40292d21fd97 同型收口；
            # 三车道 merge-back 失败处置家族 MUST 同步）：并发冻结窗口内
            # transition 失败（目标态已被并发写者推进或 freeze_for_human 冻结）
            # 时保留现场早退——否则下方清账照常落盘，冻结 error（内嵌
            # 「原状态 X」供 parse_orig_status 解冻还原，state_machine 契约）
            # 被覆盖后人工解冻无法还原原状态，_retry_count 清零抹掉现场计数。
            if not self._pm.state_machine.transition(
                spec_name, "blocked",
                trigger_run_id=None, agent_type="repair", channel="auto",
            ):
                self._pm.logger.warning(
                    "pm_engine",
                    f"repair re-merge 熔断但 transition 到 blocked 失败（并发"
                    f"写者已推进/冻结），保留计数与 error 现场待收口重试/审计: "
                    f"{spec_name}",
                )
                return False
            # streak 已由 bump_counters 原子递增落盘时不再并写该字段
            # （防并发写回互相覆盖丢增量），仅指纹切换重置路径补绝对写。
            breaker_updates: dict = {
                "error": final_error,
                "_merge_fp": fp,
                "_retry_count": 0,
                # 熔断封顶时一并清除「待 re-merge」标记（D3）：blocked
                # 状态下无论 admin 如何处置（unfreeze/重置），该标记不应
                # 残留导致后续启动误走 re-merge 路径。
                "_repair_awaiting_remerge": False,
            }
            if not streak_bumped:
                breaker_updates["_merge_streak"] = streak
            self._pm.state_machine.update_spec(spec_name, breaker_updates)
            self._pm.logger.error(
                "pm_engine",
                f"Circuit breaker tripped after repair for '{spec_name}' (fp={fp}) "
                f"— spec blocked (repair 不绕过熔断)",
            )
            return False
        if self._pm._should_enter_repair(spec_name, remerge_info, streak, breaker_threshold):
            # 锁移交（code-review item ec22643fa99a）：True = 下一轮 repair 已
            # 派发并在 _claim_repair_site 重新认领同名锁，worker finally 跳过释放。
            return bool(self._pm._dispatch_repair_lane(
                spec_name,
                remerge_info,
                branch,
                fp=fp,
                streak=streak,
            ))
        # 未触发熔断且不可 repair → fallback 全新重派
        # code-review item 8e379d862123：re-merge 错误须落 merge_error 形参，
        # repair_error 只写「re-merge 失败不可 repair」事实，避免 STATE error
        # 被误标为 repair 失败、真实 merge 上下文被占位符替换。
        self._fallback_after_repair(
            spec_name,
            branch,
            repair_error="repair 后 re-merge 失败且不可 repair",
            merge_error=merge_error,
        )
        return False

    def _fallback_after_repair(
        self, spec_name: str, branch: str | None, repair_error: str, merge_error: str = ""
    ) -> None:
        """repair 链失败回退：全新重派 implementer，prompt 注入 merge 失败上下文。

        - 清理 repair worktree（保留分支：按既有清扫策略登记遗产，供后继 run 参考）；
        - ``_repair_round`` 归零：fallback 后新 implementer 的 merge 失败开启新链
          （design D6）；
        - 状态置 ready + error（既有 _prev_error_section 会把它注入新 implementer
          prompt，即「prompt 注入当次 merge 失败上下文」）；例外：``_retry_count``
          达 ``agents.max_retries`` 时走 freeze_for_human 冻结转人工（3.1 单一
          入口），不再重派；
        - ``_merge_fp``/``_merge_streak`` **不清零**：repair 失败后 fallback 重派
          引发的 merge-back 失败与前序失败连续累计（熔断协同）。
        """
        wm = self._pm.agent_runner.worktree_manager
        # 清理 repair worktree（若有现场）：分支按既有清扫策略登记遗产
        try:
            if branch and wm.branch_exists(branch):
                wt_path = wm.find_worktree_path(branch)
                if wt_path is not None and wt_path.exists():
                    try:
                        # dev-server 收割经门面单跳（code-review item 227d772b3847）。
                        self._pm._stop_devserver_for_worktree(wt_path)
                    except Exception:
                        pass
                    wm.cleanup(wt_path, success=True)
                # 成功收工清理后仅分支留存（已解决的冲突成果随分支保留），
                # 登记为仅分支遗产供后继 run 参考收编（不丢失修复工作）
                wm.register_legacy(spec_name, None, branch)
            elif branch:
                wm.register_legacy(spec_name, None, branch)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fallback 清理 repair worktree 失败 '{spec_name}'（非阻塞）: {e}",
            )
        # 失败链收尾：归零轮次，回退 fallback
        # _retry_count 走锁内原子递增（bump_counters 返回写后值）：原先
        # 「read_one 读 → 算 +1 → 并进 update_spec 写回」读与写分处两段，
        # 两个并发 fallback（重复派发的 repair worker 同时收尾）会各持相同
        # 旧值写回同一 retries，丢一次递增、max_retries 熔断晚一轮触发。
        retries = self._pm.state_machine.bump_counters(spec_name, {"_retry_count": 1}).get(
            "_retry_count", 0
        )
        base_error = merge_error or "merge-back failed"
        if repair_error:
            full_error = (
                f"repair 失败（{repair_error[:300]}）→ 回退全新重派。"
                f"原 merge 失败上下文：{base_error[:600]}"
            )
        else:
            full_error = base_error
        # 配置归一收敛单一读取器（code-review item 8b26fd7980ce）：本方法是
        # repair 链三条失败路径的共同收尾（且可能运行在 worker 的 except 兜底
        # 内），解析异常会打断 update_spec/blocked 收尾——None 判空/非法值回退
        # 缺省 3、0=不自动重试（无下限）的统一口径见模块级 _max_retries。
        max_r = _max_retries(self._pm)
        # 收尾字段（不含 error/status）：冻结转人工路径经 freeze_for_human 的
        # extra_updates 并入同一原子写；ready 回退路径再并上 status/error 写。
        updates: dict = {
            "_repair_round": 0,
            "_repair_merge_error": None,
            # 基准 tip 随 fallback 一并清零（fix-repair-commit-enforcement 2.2）：
            # 复核失败 / remerge 再失败 / worker 异常三条 fallback 路径都不再续
            # repair 链，清空避免 STATE 残留 stale 基准 tip 孤儿字段（新 implementer
            # 的 merge 失败开启新链，与 _repair_round 归零同族）。
            "_repair_base_tip": None,
            # 清除待 re-merge 标记（fix-recovery-branch-anchor D3）：fallback
            # 重派后由新 implementer 正常收口，不得再被恢复链当「待 re-merge」处理。
            # （fix-fasttrack-recovery-resume 4.1 出口矩阵·例外）此清除**不涉及**
            # branch/implementer_run（二者保持原值，不新增清锚点），也**不消费**
            # _recovery_resume（恢复标记在 dispatch 入口一次性消费，此处不触碰）。
            "_repair_awaiting_remerge": False,
            # _retry_count 已由上方 bump_counters 原子递增并落盘，此处不再
            # 并入 update_spec（避免并发 fallback 间互相覆盖丢增量）。
        }
        if retries >= max_r:
            # fix-blocked-freeze-classification 3.1：重试耗尽收敛到 freeze_for_human
            # 单一入口（frozen + 人工升级告警成对写入），与 budget.py /
            # spec_integrity.py 同语义站点及 queue.py / fast_track.py 重试耗尽分支
            # 同口径——原手工 status=blocked 既无 frozen 标记也无成对告警，
            # admin_monitor 的 blocked_stuck 豁免判据一条不占，冷却期满会被按
            # stuck 自动召唤 admin run，与 full 车道同场景处置机制分裂。error
            # 内嵌「原状态 X」供 parse_orig_status 解冻还原。
            orig_status = (self._pm.state_machine.read_one(spec_name) or {}).get(
                "status"
            ) or "implementing"
            self._pm.state_machine.freeze_for_human(
                spec_name,
                error=(
                    f"原状态 {orig_status} · 实现尝试连续 {max_r} 次失败"
                    f"（含 repair 通道）— 已冻结转人工，需人工检查。"
                    f"最近失败：{full_error[:400]}"
                ),
                signal_type="redispatch_loop_detected",
                severity="major",
                description=(
                    f"'{spec_name}' 实现尝试连续 {max_r} 次失败（含 repair 通道）"
                    f"已达 agents.max_retries 上限，自动重试终止——已冻结转人工处置"
                ),
                evidence=(
                    f"spec={spec_name}; retries={retries}; max_retries={max_r}; "
                    f"final_error={full_error}"
                ),
                recommended_action=(
                    "检查实现/repair 失败根因；处置后解冻（unfreeze_spec 自动清零"
                    "计数）可重新获得自动修复机会"
                ),
                alert_callback=self._pm._send_human_escalation_alert,
                extra_updates=updates,
            )
            self._pm.logger.error(
                "pm_engine",
                f"repair 链回退重试耗尽 '{spec_name}'：{full_error[:200]} — "
                f"冻结转人工，不再重派",
            )
            return
        self._pm.state_machine.update_spec(
            spec_name, {"status": "ready", "error": full_error, **updates},
        )
        self._pm.logger.error(
            "pm_engine",
            f"repair 链回退 fallback '{spec_name}'：{full_error[:200]}",
        )
        # 回退通道按 spec 实现模式选择（fast-track 接入 repair lane 配套）：
        # fast-track spec 的 repair 失败回 fast-track 重派，不硬派 implementer
        try:
            from core.spec_mode import read_spec_mode

            channel = (
                "fast-track"
                if read_spec_mode(self._pm.project_root, spec_name) == "fast-track"
                else "implementer"
            )
        except Exception:
            channel = "implementer"
        self._enqueue_front(spec_name, channel)

    def _repair_conflict_summary(self, spec_name: str, merge_info) -> dict:
        """构造 repair prompt 的冲突摘要（D5：spec 身份 + 冲突清单 + 方向说明）。

        不含原 worktree 地址类间接情报（agent 即在现场，冲突状态自查）。

        evo-inflight-spec-amendment-watch 1.3：附 ``amended_inflight``（主树
        已提交在飞修订提交短哈希列表，merge-back 侧检出时携带）——prompt 构建侧
        （_build_repair_prompt）据此增补「主树在飞修订根因」段；旧形态
        merge_info（测试替身/无字段）按未命中空列表处理。
        """
        try:
            repair_round = int(
                (self._pm.state_machine.read_one(spec_name) or {}).get("_repair_round", 0) or 0
            )
        except (TypeError, ValueError):
            repair_round = 0
        return {
            "spec": spec_name,
            "merge_error": getattr(merge_info, "error", "") or "",
            "conflict_paths": list(getattr(merge_info, "conflict_paths", []) or []),
            "has_semantic_conflict": bool(getattr(merge_info, "has_semantic_conflict", False)),
            "repair_round": repair_round,
            "amended_inflight": list(getattr(merge_info, "amended_inflight", []) or []),
        }
