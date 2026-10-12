"""legacy_registry.py — G2 遗产/复用注册表（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 11 个方法，原样搬移为 mixin（方法体零改动）。
宿主实例 `self._legacy` 字典为遗产存储载体，`self._reused_worktrees` 为复用记录。
"""

from __future__ import annotations

import shutil
import subprocess
import time

from pathlib import Path
from typing import Optional

from core.worktree_manager.constants import (  # noqa: E402
    LEGACY_GRACE_SECONDS,
    WT_AVAILABLE,
)

class G2LegacyRegistryMixin:
    def register_legacy(self, spec_name: str, worktree_path, branch: str) -> None:
        """登记某 spec 的死亡 run 遗产（worktree 路径 + 分支）。

        覆盖式更新（D5）：同一 spec 再次死亡时仅保留最新一份登记（避免遗产链
        膨胀）。本方法**只覆盖内存登记、不做物理回收**——旧遗产的 worktree 目录
        与分支交由既有清扫路径兜底回收（``_reclaim_expired_legacy`` 宽限期回收 /
        ``consume_legacy`` 收编回收 / 孤儿清扫），被覆盖的登记随之出册、不再受
        清扫豁免。daemon 重启后内存态丢失，遗产按孤儿清扫兜底回收。

        支持两种模式（守卫拒绝重派接入，add-project-description 事故治理）：
        - worktree 模式：worktree_path 非空 —— 死亡 run 的未提交半成品目录保留；
        - 仅分支模式：worktree_path 为 None/空 —— 守卫拒绝发生在成功收工清理之后，
          worktree 已物理删除，仅分支留存（完整已提交成果），path 记空串。

        Args:
            spec_name: 死亡 run 所属 SPEC。
            worktree_path: 死亡 run 的 worktree 绝对路径（Path 或 str）；
                仅分支模式传 None。
            branch: 死亡 run 的分支名（仅分支模式下为收编唯一线索，必填）。

        并发纪律（code-review item fb49eca84deb）：覆盖判定与入册写全程持
        _spec_lock_th，与陈锁兜底注册（``_maybe_register_legacy_for_stale_lock``
        的「has_legacy 复核 + 登记」原子段）互斥——否则陈锁线程入口检查通过后、
        登记写之前，同 spec 收尾线程恰经 keep_for_reuse 登记的 reuse 遗产会被
        本处无 reuse 的覆盖登记顶掉（下轮 create 认领失效退化为全新建树，宽限
        期后现场目录被 sweeper 当无主孤儿回收）。实际写体在
        ``_register_legacy_unlocked``（threading.Lock 非重入，已持锁语境不得再
        走本方法）。
        """
        if not spec_name or not branch:
            return
        wt_str = str(worktree_path) if worktree_path else ""
        # 覆盖式更新（D5：仅留最新一份登记；旧遗产物理回收交由清扫器）。
        # 写段持 _spec_lock_th（code-review item fb49eca84deb，纪律同
        # _release_spec_locks_of：锁内只做读判定与写，留痕日志移出锁外补记）。
        with self._spec_lock_th:
            replaced_path = self._register_legacy_unlocked(spec_name, wt_str, branch)
        if replaced_path is not None:
            self.logger.info(
                "worktree_manager",
                f"Replacing prior legacy for '{spec_name}' ({replaced_path}) "
                f"— superseded by newer death",
            )
        self._log_legacy_registered(spec_name, wt_str, branch)

    def _log_legacy_registered(self, spec_name: str, wt_str: str, branch: str) -> None:
        """遗产登记成功入册的统一留痕（register_legacy / 陈锁兜底原子段共用）。"""
        self.logger.warning(
            "worktree_manager",
            f"Registered legacy for '{spec_name}': "
            f"{'worktree=' + wt_str if wt_str else 'branch-only'} branch={branch}",
        )

    def _register_legacy_unlocked(
        self, spec_name: str, wt_str: str, branch: str,
    ) -> Optional[str]:
        """register_legacy 的实际写体（MUST 持 _spec_lock_th 调用）。

        覆盖式更新（D5：仅留最新一份登记；旧遗产物理回收交由清扫器）。
        返回被覆盖的旧遗产 path（无覆盖返回 None），供调用方在锁外补留痕日志。
        """
        old = self._legacy.get(spec_name)
        self._legacy[spec_name] = {
            "path": wt_str,
            "branch": branch or "",
            "worktree_name": (
                wt_str.rstrip("/").split("/")[-1] if wt_str else f"branch-only:{branch}"
            ),
            "registered_at": time.time(),
            "dirty": bool(wt_str),  # worktree 模式待刷新脏快照；仅分支模式无脏文件
        }
        return old.get("path") if old is not None else None

    def get_legacy(self, spec_name: str) -> Optional[dict]:
        """返回某 spec 的遗产记录（copy），无则 None。

        调用方（agent_runner 的 prompt 构建）据此注入遗产上下文；返回副本避免
        外部直接改内部态。结构见 register_legacy。
        """
        rec = self._legacy.get(spec_name)
        if rec is None:
            return None
        return dict(rec)

    def consume_legacy(self, spec_name: str) -> Optional[dict]:
        """回收某 spec 的遗产（后继 run 成功 merge 时调用），返回被回收的记录。

        返回 None 表示该 spec 无在册遗产（幂等：重复调用安全）。回收时同步物理删除
        遗产 worktree 与分支（失败后保留的半成品不再需要），使清扫器不再对其豁免。
        物理删除失败仅记 WARNING，内存态遗产仍清除以放行后续逻辑。
        """
        rec = self._legacy.pop(spec_name, None)
        if rec is None:
            return None
        self._active_reuse.pop(spec_name, None)
        self.logger.info(
            "worktree_manager",
            f"Consumed legacy for '{spec_name}' (successor merged): {rec.get('path')}",
        )
        self._physically_reclaim_legacy(
            spec_name, rec, failure_label="consume physical reclaim",
        )
        return rec

    def has_legacy(self, spec_name: str) -> bool:
        """某 spec 是否有在册遗产（只读查询，prompt 注入 `无遗产不注入` 判定用）。"""
        return spec_name in self._legacy

    def mark_legacy_reusable(self, spec_name: str) -> bool:
        """把在册遗产标记为可被下轮 create 认领（reuse=True，与 keep_for_reuse 同源标记）。

        fix-relint-redispatch-legacy：守卫/relint 打回路径在 ``register_legacy``
        （仅分支模式，worktree_path=None）登记后调用——register_legacy 自身不置
        reuse，而 ``_take_reusable_worktree`` 认领条件要求 reuse 为真；仅分支遗产
        打上该标记后，下轮 create 才能在既有分支上重建载体认领同一分支，继承首轮
        已提交成果（而非仅靠 prompt 注入提示收编）。

        无在册遗产时安全返回 False（幂等，不抛异常）；fast-track 车道不走本方法
        （其现场保留经 ``keep_for_reuse`` 已置 reuse，若此处再置不改变语义）。
        """
        rec = self._legacy.get(spec_name)
        if rec is None:
            return False
        rec["reuse"] = True
        return True

    def keep_for_reuse(self, spec_name: str, wt_path: Path, agent_type: str = "") -> None:
        """保留 worktree 目录与分支，登记供下轮重派继承。

        底层复用 register_legacy（同一登记表：宽限期回收、清扫器豁免全继承），
        仅追加 ``reuse`` 标记供 create() 认领。与 cleanup(success=False) 的差异：
        不删除目录与分支、仅释放锁与活动集；dev-server 由调用方先行回收。

        fix-provider-transient-backoff（D3）：transient 终态失败同样走此路径
        （替代 cleanup(success=False)），agent_type 参数供日志区分来源
        （fast-track / implementer / transient 其他 agent_type）。
        """
        # 入口时刻快照（code-review item ede232241fe2，与 cleanup finally 的
        # cleanup_entry_ts 同款）：两条出口的摘锁共用该基准——收尾期间并发
        # create() 登记的同 spec 他 agent_type 新锁 _lock_since 晚于该时刻即
        # 跳过不误摘（快照取方法入口，覆盖 _kill_worktree_strays 等耗时判定
        # 的全程窗口）。
        entry_ts = time.time()
        wt_str = str(wt_path)
        branch = self._wt_branches.get(wt_str) or self._guess_branch_from_worktree(wt_path)
        # agent_type 家族限定（code-review item 1c6d47a74461，对齐 cleanup
        # finally 的 79268616af63 口径）：摘锁只限本家族——verifier 收尾只摘
        # :verifier，非 verifier 车道不摘 :verifier。not_after 入口守卫只挡
        # 入口之后的新锁，挡不住入口之前他家族已持有的锁（如 verifier 收尾时
        # implementer 已重派持锁），误摘会让在飞 run 在构建窗口内失去锁保护
        # （重开 2026-09-03 双派发事故同型窗口）。调用方未传 agent_type 的
        # 旧调用点按被收尾 worktree 形状反推（分支 fenix/verify- 前缀或目录
        # verify- 前缀 → verifier 家族，fenix/ 或 impl- 前缀 → 非 verifier，
        # 与 cleanup finally 的形状反推同口径）；形状完全不可辨时维持旧全摘。
        if agent_type == "verifier":
            lock_family = "verifier"
        elif agent_type:
            lock_family = "non-verifier"
        elif (branch or "").startswith("fenix/verify-") or wt_path.name.startswith("verify-"):
            lock_family = "verifier"
        elif (branch or "").startswith("fenix/") or wt_path.name.startswith("impl-"):
            lock_family = "non-verifier"
        else:
            lock_family = None
        # 收工清扫：agent 已退出，杀掉残留测试子进程（目录保留，进程不留）
        self._kill_worktree_strays(wt_path.name)
        self.register_legacy(spec_name, wt_path, branch)
        rec = self._legacy.get(spec_name)
        # 登记生效判定（code-review item a35088c8bdbb）：不能只凭 rec 非 None——
        # 同 spec 已有更早遗产记录（如前次死亡登记后经 resolve_resume_site 续做/
        # mark_reused 路径复用，两者均不出册 _legacy）且本次 branch 双兜底皆空时，
        # register_legacy 对空分支直接早退、不触碰 _legacy，rec 会取到旧记录
        # （path 指向别的 worktree）：误盖 reuse=True 会让 _take_reusable_worktree
        # 认领旧 path，落入正常收尾分支又会把当前 wt_path 误摘活动集成无登记
        # 孤儿。按 path 归属校验取到的确属本次登记才置 reuse，否则归入下方的
        # 登记未生效出口（置 None 复用同一判定，正常/告警两出口结构不变）。
        if rec is not None and rec.get("path") == wt_str:
            rec["reuse"] = True
        else:
            rec = None
        if rec is None:
            # 登记未生效（_wt_branches 与 _guess_branch_from_worktree 双兜底皆空，
            # register_legacy 对空分支直接 return；rec 非 None 时为同 spec 更早的
            # 旧遗产记录，未被本次登记覆盖）：本应受清扫豁免与 reuse 认领
            # 保护的现场会变成无登记孤儿、可被孤儿清扫回收。留痕并保留活动集
            # 成员身份使豁免仍生效；锁照常释放（run 已终结，扣锁会阻塞重派），
            # 仅降级说明 reuse 认领不可用（code-review item 431f12115971）。
            self.logger.warning(
                "worktree_manager",
                f"keep_for_reuse 登记未生效: spec '{spec_name}' 双兜底均未解析到分支"
                f"（wt={wt_path}），保留活动集成员身份防孤儿清扫，reuse 认领本轮不可用"
                + (f"，agent_type '{agent_type}'" if agent_type else ""),
            )
            self._active_reuse.pop(spec_name, None)
            self._proc_scan_cache.pop(spec_name, None)
            self._release_spec_locks_of(spec_name, not_after=entry_ts, family=lock_family)
            return
        self._active_worktrees.discard(wt_str)
        self._wt_branches.pop(wt_str, None)
        self._active_reuse.pop(spec_name, None)
        # 释放 spec 锁（与 cleanup 的 finally 段同语义，按 spec 精确匹配，
        # 并按 agent_type 家族限定——见上方 lock_family 推导注释）：
        # 摘锁口径与入口时刻守卫统一收敛到 _release_spec_locks_of 单一实现。
        self._release_spec_locks_of(spec_name, not_after=entry_ts, family=lock_family)
        self._proc_scan_cache.pop(spec_name, None)
        self.logger.info(
            "worktree_manager",
            f"Kept worktree for reuse: {wt_path} (branch {branch}, "
            f"spec '{spec_name}'" + (f", agent_type '{agent_type}'" if agent_type else "") + ")",
        )

    def _release_spec_locks_of(
        self, spec_name: str, not_after: float | None = None,
        family: str | None = None,
    ) -> None:
        """摘除该 spec 名下（`<spec>:<agent_type>` 键按 spec 前缀精确匹配）的在册锁。

        薄委托（code-review item 53b7d6a78045）：摘锁口径单源在
        ``_release_spec_locks_core``（与 locks._release_spec_locks 同一底层
        实现，lock_key/family/not_after 三维可选，调整摘锁纪律只改该处），
        本方法保持既有签名与行为不变。

        keep_for_reuse 两条出口（登记未生效 / 正常收尾）共用单一实现
        （code-review item fcffade60cc9）：两条出口行为不再漂移。

        not_after：入口时刻守卫（code-review item ede232241fe2，与 cleanup
        finally 的 cleanup_entry_ts 同款）——仅摘除 _lock_since 不晚于该时刻
        的锁：收尾期间派发器对同一 spec 换 agent_type 发起的新 create（如
        verifier 收尾时 implementer 重派，lifecycle.py 清理注释已承认该并发
        可发生）键不同故加锁成功，其 _lock_since 晚于入口时刻，跳过不误摘，
        防在飞 run 失去锁保护重开双派发窗口；None 表示不设限（旧版行为）。

        family：agent_type 家族限定（code-review item 1c6d47a74461，对齐
        cleanup finally 的 79268616af63 口径）——"verifier" 只摘 :verifier、
        "non-verifier" 不摘 :verifier（分支名只编码 verify/impl 两族形状，
        impl 族内具体 agent_type 不可辨，同族维持全摘）；None 表示不设限
        （被收尾 worktree 形状完全不可辨时的兜底）。
        """
        self._release_spec_locks_core(spec_name, not_after=not_after, family=family)

    def get_reuse_record(self, spec_name: str) -> Optional[dict]:
        """返回本轮 run 已认领的复用 worktree 记录（prompt 注入用），无则 None。"""
        rec = self._active_reuse.get(spec_name)
        if rec:
            return dict(rec)
        rec = self._legacy.get(spec_name)
        if rec and rec.get("reuse"):
            return dict(rec)
        return None

    def mark_reused(
        self, spec_name: str, wt_path: Path, branch: str,
        recovery: bool = False,
    ) -> None:
        """标记跨 attempt 复用的 worktree（未走 create 认领路径时补记，幂等）。

        Args:
            recovery: 为真时把恢复来源标记写入记录（``{"path": …,
                "branch": …, "recovery": True}``），供 prompt 恢复续做判据
                （fix-fasttrack-recovery-resume 3.2b）区分「恢复续做」与
                「普通打回重派/跨 attempt 复用」——后者同样写入 _active_reuse，
                无来源判据会把「曾因 daemon 重启被中断」的错误归因注入普通
                重派轮（design D6）。缺省不写键，既有调用行为不变。
        """
        rec = {
            "path": str(wt_path),
            "branch": branch or "",
        }
        if recovery:
            rec["recovery"] = True
        self._active_reuse[spec_name] = rec

    def _take_reusable_worktree(
        self, spec_name: str, agent_type: str = "",
    ) -> Optional[tuple]:
        """认领该 spec 的复用遗产；有效返回 (wt_path, branch)，无效清理后返回 None。

        有效性：目录存在、仍是注册的 git worktree、分支仍可解析。认领即从
        _legacy 摘出（在用目录不再是「遗产」，防 sweeper 宽限期回收正在工作的
        worktree），转入 _active_reuse 供 prompt 注入与收尾清理。

        agent_type（code-review item 7f66c46fffef）：create 发起方 agent_type，
        供家族校验——verify 族 legacy（fenix/verify- 分支 / verify- 目录前缀）
        仅 verifier 可认领、非 verify 族 legacy 不被 verifier 认领（认领不校验
        家族会在 verify 载体上做实现，merge-back 分支语义随之混乱）。家族按
        keep_for_reuse / cleanup finally 同款形状反推（分支前缀优先、目录名
        兜底；仅分支模式 path 为空时以登记的 worktree_name 兜底），形状不可辨
        不设限（fail-open）。不匹配 → 跳过认领（不动在册遗产：verifier 后续
        重派仍可认领，宽限期回收兜底不变）返回 None 走全新建树；agent_type 为
        空（直调旧口径）不设限，行为同旧版。
        """
        rec = self._legacy.get(spec_name)
        if not rec or not rec.get("reuse"):
            return None
        path = rec.get("path") or ""
        branch = rec.get("branch") or ""
        if agent_type:
            wt_name = (
                path.rstrip("/").rsplit("/", 1)[-1]
                if path else str(rec.get("worktree_name") or "")
            )
            if branch.startswith("fenix/verify-") or wt_name.startswith("verify-"):
                legacy_family = "verifier"
            elif branch.startswith("fenix/") or wt_name.startswith("impl-"):
                legacy_family = "non-verifier"
            else:
                legacy_family = None
            if legacy_family is not None:
                claimant = "verifier" if agent_type == "verifier" else "non-verifier"
                if claimant != legacy_family:
                    self.logger.info(
                        "worktree_manager",
                        f"Reusable legacy for '{spec_name}' family mismatch "
                        f"(legacy={legacy_family}, claimant agent_type "
                        f"'{agent_type}') — skip claim, fresh create",
                    )
                    return None
        wt = Path(path) if path else None
        if wt is None:
            # 仅分支模式（fix-relint-redispatch-legacy，守卫/relint 打回）：成功收工
            # 后 worktree 已被 cleanup(success=True) 物理清理、仅分支留存完整已提交
            # 成果——在既有分支上重建载体（checkout，impl- 前缀保持 implementer 通道
            # 语义）认领同一分支，MUST NOT 从 main HEAD 起新分支（继承首轮已提交
            # 工作）。仅在 path 为空时启用，worktree 模式语义不变；分支不可解析或
            # 换壳失败 → fail-open 回退全新 create（遗产清除，防 sweeper 误豁免）。
            if not branch:
                self._legacy.pop(spec_name, None)
                return None
            wt_path = self.create_worktree_on_branch(spec_name, branch, prefix="impl")
            if wt_path is None:
                self._legacy.pop(spec_name, None)
                self.logger.info(
                    "worktree_manager",
                    f"Branch-only legacy for '{spec_name}' cannot be re-checked out "
                    f"(branch={branch or 'none'}) — fresh create",
                )
                return None
            self._legacy.pop(spec_name, None)
            self._active_reuse[spec_name] = {"path": str(wt_path), "branch": branch}
            return wt_path, branch
        # 有效性判定收敛到 is_available 单源（interrupt-recovery-preserve D5）：
        # 目录存在 + git worktree 注册有效 + 分支可解析。判定口径与 repair
        # 换壳（resolve_repair_site）、recovery 保留一致，任何链路不自行拼装。
        valid = False
        try:
            valid = self.is_available(wt, branch) == WT_AVAILABLE
        except Exception:
            valid = False
        if not valid:
            self._legacy.pop(spec_name, None)
            self.logger.info(
                "worktree_manager",
                f"Reusable legacy for '{spec_name}' no longer valid "
                f"(path={path or 'none'}, branch={branch or 'none'}) — fresh create",
            )
            return None
        self._legacy.pop(spec_name, None)
        self._active_reuse[spec_name] = {"path": str(wt), "branch": branch}
        return wt, branch

    def _maybe_register_legacy_for_stale_lock(self, spec_name: str) -> None:
        """refresh_locks 释放陈锁时的遗产兜底注册（add-recovery-legacy-check D2）。

        若该 spec 已无在册锁、但有物理残留的 implementer worktree（孤儿目录），且
        该 worktree 当前未被活动集占用，则注册为遗产，避免被 cleanup_stale_worktrees
        直接回收（design D2「单点改动、无新增扫描」：复用 refresh_locks 的扫锁时机）。

        幂等：register_legacy 为覆盖式更新，已注册遗产不重复写。若该 spec 已在册
        遗产则跳过（不覆盖已有更早注册的遗产——更早注册的宽限期更短，应由其决定）。
        入口的 has_legacy 只是无锁快检（省后续目录扫描），权威判定在登记前与
        登记写同锁复核——code-review item fb49eca84deb：快检与登记写之间的窗口
        内，同 spec 收尾线程可能恰经 keep_for_reuse 登记带 reuse=True 的遗产，
        无锁覆盖会把 reuse 顶掉（下轮 create 认领失效退化为全新建树，宽限期后
        现场目录被 sweeper 当无主孤儿回收）。

        例外：分支三级兜底（get_branch_name/_wt_branches/_guess_branch_from_worktree）
        皆空时 register_legacy 对空 branch 直接早退不入册——该孤儿目录不获清扫豁免、
        将被 cleanup_stale_worktrees 正常回收，此时仅记 WARNING 留痕。
        """
        if self.has_legacy(spec_name):
            return
        wt = self.find_implementer_worktree(spec_name)
        if wt is None:
            return
        if str(wt) in self._active_worktrees:
            return  # 仍在活动集：未被清理，非孤儿，正常派发中
        branch = self.get_branch_name(wt) or self._wt_branches.get(str(wt))
        if not branch:
            branch = self._guess_branch_from_worktree(wt)
        if not branch:
            # 三级兜底皆空：register_legacy 对空 branch 直接 return 不入册，孤儿
            # worktree 未获清扫豁免。留痕说明放弃注册（对齐 keep_for_reuse 同型
            # 处理，code-review item 26cdfa042cf8）。
            self.logger.warning(
                "worktree_manager",
                f"Stale-lock legacy registration skipped for '{spec_name}': branch "
                f"unresolvable (wt={wt}) — no sweep exemption, orphan directory is "
                f"subject to cleanup_stale_worktrees reclaim",
            )
        # 原子段（code-review item fb49eca84deb）：has_legacy 复核 + 覆盖决定 +
        # 登记写全程持 _spec_lock_th，与 keep_for_reuse / register_legacy 的登记
        # 写互斥。写体走 _register_legacy_unlocked（本段已持锁，threading.Lock
        # 非重入，不得再走会重复取锁的 register_legacy）；「已在册不覆盖」与
        # 「空分支不入册」（register_legacy 对空 branch 直接早退的同语义）都在
        # 锁内判定，登记留痕照 register_legacy 口径移出锁外补记。
        with self._spec_lock_th:
            if self.has_legacy(spec_name) or not branch:
                return
            self._register_legacy_unlocked(spec_name, str(wt), branch)
        self._log_legacy_registered(spec_name, str(wt), branch)

    def _guess_branch_from_worktree(self, wt_path) -> str:
        """从 worktree 目录 HEAD 取分支名（register_legacy 兜底用）。"""
        try:
            br = subprocess.run(
                ["git", "-C", str(wt_path), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                # 显式 UTF-8（code-review item 3847fde03f79）：text=True 缺省按
                # locale strict 解码，非 ASCII 分支名在非 UTF-8 locale 下抛
                # UnicodeDecodeError 使分支解析静默降级——与包内 dist_conflicts.py /
                # verify_report.py / repair_site.py 采集点同口径。
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if br.returncode == 0:
                branch = br.stdout.strip()
                # detached HEAD 时 rev-parse 返回字面量 "HEAD"（code-review item
                # c1c890cd48ff）：与 _physically_reclaim_legacy 的
                # branch != "HEAD" 守卫在源头对齐，过滤为空串交由调用方
                # `if not branch` 守卫承接，避免 "HEAD" 作为分支名入册误导。
                return "" if branch == "HEAD" else branch
        # 收窄捕获（code-review item 3847fde03f79）：subprocess.run 只会抛
        # SubprocessError（含 TimeoutExpired）或 OSError；解码异常已由上方
        # errors="replace" 消除，不再吞其他意外异常掩盖真实缺陷。
        except (subprocess.SubprocessError, OSError):
            pass
        return ""

    def _reclaim_expired_legacy(self, now: float | None = None) -> list:
        """宽限期兜底回收（add-recovery-legacy-check D2）：清扫器在扫孤儿前调用。

        对每条在册遗产，若注册时刻距今超过 LEGACY_GRACE_SECONDS（跟随孤儿清扫周期），
        视为无人收编而兜底回收：删除 worktree 目录 + 分支、记审计。返回被回收的
        spec 名列表（审计/测试用）。

        宽限期内（后继 run 尚在派发中）的遗产不动，交 merge 成功 / 重派逻辑处理。
        """
        if not self._legacy:
            return []
        now = time.time() if now is None else now
        # 迭代前物化快照（code-review item 19fc3ac92552）：register_legacy
        # （runner 终态线程）/consume_legacy（merge-back 线程）/keep_for_reuse
        # 会在本回收运行期间增删 _legacy 同键，直接迭代 items() 会触发
        # "dictionary changed size during iteration" 并中断整轮回收；物化后
        # 迭代期间的增删不再作用于正在迭代的字典流（与 _release_spec_locks_of
        # 对 _spec_locks 的 sorted 快照同纪律）。
        expired = [
            spec
            for spec, rec in list(self._legacy.items())
            if now - rec.get("registered_at", 0) > LEGACY_GRACE_SECONDS
        ]
        reclaimed: list = []
        for spec in expired:
            rec = self._legacy.pop(spec, None)
            if rec is None:
                continue
            # pop 后复核宽限期（code-review item 0d5c6c7e148e）：快照与 pop
            # 之间该 spec 可能被 register_legacy 覆盖登记（再次死亡，
            # registered_at=now），pop 取出的是当前新记录；仍在宽限期内则
            # 放回出册位并跳过本条，不提前回收新遗产。setdefault 而非直接
            # 赋值，避免覆盖此间隙内更新的登记。
            if now - rec.get("registered_at", 0) <= LEGACY_GRACE_SECONDS:
                self._legacy.setdefault(spec, rec)
                continue
            path = rec.get("path", "")
            branch = rec.get("branch", "")
            self.logger.warning(
                "worktree_manager",
                f"Legacy grace period expired for '{spec}' — sweeper reclaiming "
                f"worktree={path} branch={branch}",
            )
            self._physically_reclaim_legacy(
                spec, rec, failure_label="sweeper reclaim",
            )
            reclaimed.append(spec)
        return reclaimed

    def _physically_reclaim_legacy(
        self, spec_name: str, rec: dict, *, failure_label: str,
    ) -> None:
        """对单条已出册遗产执行物理回收序列（consume / sweeper 共用单一实现）。

        完整销毁序列：git worktree remove --force → 失败且目录仍在时 rmtree
        兜底 → worktree prune → branch -D（跳过 HEAD）。rmtree 兜底统一采用
        较保守的 wt.exists() 判定，避免对已消失目录无条件 rmtree。

        三步彼此隔离容错（code-review item 2e481b11b82f）：任一步失败仅记
        WARNING、不向上抛，且不阻断后续步骤——调用方（consume / sweeper）已
        先行出册、无重试入口，单 try 短路会让死亡分支与目录长期残留
        （``failure_label`` 供两个入口区分失败日志文案）。prune 随每条记录执行
        （幂等），统一取代原先 consume 单次 / sweeper 循环收尾单次的两种落点。
        """
        path = rec.get("path", "")
        branch = rec.get("branch", "")
        if path:
            wt = Path(path)
            # 删除前收尾清扫（code-review item d50610627782）：登记遗产的孤儿
            # 目录（daemon 重启、attempt 已死、cleanup 从未跑过）其残留子进程
            # 从未被收割——目录删除后它们成为 cwd 失效的永生孤儿（曾致存活检
            # 测永久受骗）。与 cleanup / cleanup_orphans / stale_sweep /
            # keep_for_reuse 四条删除或保留目录的路径同口径。
            self._kill_worktree_strays(wt.name)
            # 删除前留档（code-review item d1735b0c555f，cleanup_orphans
            # docstring 声明的 MUST 不变量）：本方法面对的正是未提交半成品
            # （register_legacy：死亡 run 的未提交半成品目录保留），销毁前做
            # stash create 快照引用供事后取证；失败仅 WARNING，不阻断删除。
            self._snapshot_dirty_worktree(wt, branch or None)
            try:
                res = subprocess.run(
                    ["git", "-C", str(self.project_root), "worktree", "remove", str(wt), "--force"],
                    capture_output=True,
                    text=True,
                    # encoding/errors（code-review item 3847fde03f79）：缺省按
                    # locale strict 解码，非 ASCII 路径会使解码异常被下方 except
                    # 误判为 remove 失败——与 _guess_branch_from_worktree 同口径。
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                if res.returncode != 0 and wt.exists():
                    # rmtree 兜底失败留痕（code-review item 8775e28ca392）：
                    # ignore_errors=True 会把权限不足/文件被占用等部分或全部
                    # 删除失败静默吞掉，目录残留无任何日志。失败仅记 WARNING
                    # （含未删残留说明），不向上抛——与 branch -D / prune 同口径。
                    try:
                        shutil.rmtree(str(wt))
                    except OSError as e:
                        self.logger.warning(
                            "worktree_manager",
                            f"Legacy {failure_label} rmtree fallback failed for "
                            f"'{spec_name}': {e} — residual dir may remain at {wt}",
                        )
            except Exception as e:
                self.logger.warning(
                    "worktree_manager",
                    f"Legacy {failure_label} worktree-remove failed for "
                    f"'{spec_name}': {e}",
                )
                # 异常兜底（code-review item 7ad969aa114b）：remove 抛异常
                # （TimeoutExpired / OSError）时目录可能仍在，与 returncode != 0
                # 分支同款做 rmtree 兜底——否则残留目录继续被存活探测当作有效
                # worktree 且无重试入口；兜底失败按同款口径留痕，不向上抛。
                if wt.exists():
                    try:
                        shutil.rmtree(str(wt))
                    except OSError as e:
                        self.logger.warning(
                            "worktree_manager",
                            f"Legacy {failure_label} rmtree fallback failed for "
                            f"'{spec_name}': {e} — residual dir may remain at {wt}",
                        )
        # prune 提前到 branch -D 之前（code-review item 41d5c0def055）：remove
        # 失败而 rmtree 兜底成功时，该 worktree 的注册（.git/worktrees 条目）
        # 尚未清理，branch -D 会因「分支仍被该 worktree checkout」被 git 拒绝
        # 且记录已出册无重试入口，死分支就此残留；先 prune 清掉陈旧注册再删
        # 分支，对齐 cleanup() rmtree 兜底块内先 prune 再 branch -D 的成功次序
        # （prune 幂等，remove 成功的正常路径为 no-op）。
        try:
            res = subprocess.run(
                ["git", "-C", str(self.project_root), "worktree", "prune"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if res.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Legacy {failure_label} prune failed for '{spec_name}': "
                    f"{(res.stderr or '').strip()[:200]}",
                )
        except Exception as e:
            self.logger.warning(
                "worktree_manager",
                f"Legacy {failure_label} prune failed for '{spec_name}': {e}",
            )
        if branch and branch != "HEAD":
            # ── 分支在飞引用保护（code-review item 77071d383b94）──
            # 删分支前复核该分支是否被 STATE 在飞/待收口 spec 引用
            # （implementing/implemented/testing/带 _recovery_resume 的 ready、
            # blocked+frozen+_frozen_hold 冻结保持），与 stale_sweep 孤儿清扫
            # 删分支同口径：命中则保留分支、仅回收 worktree 目录——否则冻结
            # 保持 spec 的分支被登记为遗产且宽限期耗尽时会被删，解冻后续做
            # 降级为从零重派。STATE 不可解析时 _branch_protected_by_state
            # 保守返回保留，不按「无引用」放行删除。
            kept, reason = self._branch_protected_by_state(branch)
            if kept:
                self.logger.warning(
                    "worktree_manager",
                    f"Legacy {failure_label} branch-delete skipped for "
                    f"'{spec_name}': 分支在飞引用保护保留 '{branch}'（{reason}）"
                    f"— worktree 目录已回收，分支留待恢复/后继 run 收编",
                )
            else:
                try:
                    res = subprocess.run(
                        ["git", "-C", str(self.project_root), "branch", "-D", branch],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=10,
                    )
                    if res.returncode != 0:
                        # 非零（如分支仍被其他 worktree checkout、引用锁定）时
                        # 分支会静默残留，记 WARNING 留痕（code-review item 20c7ad71a648）。
                        self.logger.warning(
                            "worktree_manager",
                            f"Legacy {failure_label} branch-delete failed for "
                            f"'{spec_name}': "
                            f"{(res.stderr or '').strip()[:200]}",
                        )
                except Exception as e:
                    self.logger.warning(
                        "worktree_manager",
                        f"Legacy {failure_label} branch-delete failed for "
                        f"'{spec_name}': {e}",
                    )

