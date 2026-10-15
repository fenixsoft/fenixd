"""
infra_breaker.py — 链路级 infra 熔断器（evo-run-failure-classification-circuitbreaker）。

连续 infra 失败达阈值 → 熔断该链路停止派发；冷却后自动恢复重试。
状态持久化到 .fenix/admin_infra_breaker.json（daemon 重启后恢复）。

设计要点：
- 阈值默认 3，冷却默认 30 分钟（配置见 core/config.py）
- 状态 {link: {"count": int, "until": epoch, "state": "broken"|"closed"}}
- 文件损坏/不可读 fail-open（不阻塞派发）
- 仅 v1 接驳 spec-review 链路（verify/impl 留后续 SPEC）
"""

import json
import logging
import math
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

_logger = logging.getLogger("fenixd.infra_breaker")

# 熔断状态持久化文件
_BREAKER_STATE_FILE = ".fenix/admin_infra_breaker.json"


def _is_fenixd_logger(obj) -> bool:
    """判断 logger 是否 fenixd 的 Logger（component/message 两参接口）。

    fenixd Logger（core/logger.py）接口为 info/warning(component, message)；
    标准 logging.Logger 接口为 info/warning(msg, ...args)（单参 msg）。二者
    混用时以 `_log` 需按对象形态取参，避免格式串错配（"% 处抛 TypeError"或
    msg 被当 component 静默丢失）。
    """
    return hasattr(obj, "_log") and hasattr(obj, "_python_logger")


def _is_valid_state_number(val, nonneg: bool) -> bool:
    """状态文件数值字段合法性（数值类型 + isfinite + 可选非负，bool 不算数值）。

    与 cooldown_minutes 配置侧 isfinite 守卫口径对齐（code-review item
    d0a328355581 同构问题，code-review item 004678944eab）：json.loads 默认
    接受 NaN/Infinity 字面量，非有限 until 使 condition() 的 now >= until
    恒 False（熔断永续不恢复）。巨大 int 不送 math.isfinite（其内部转
    float 会 OverflowError），改用 abs(val) > sys.float_info.max 拦截：
    超出 float 表示范围的 int 虽任意精度恒有限，却会在 _load_state 的
    float(until) 处抛 OverflowError 逃出逐链路守卫、落入外层 except 致
    _cache 整体清空（code-review item 8783900adf96），须在校验期拦截。
    """
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    if isinstance(val, float) and not math.isfinite(val):
        return False
    if abs(val) > sys.float_info.max:
        # 仅巨大 int 会命中（有限 float 恒 <= max，inf 已被上方 isfinite 拒绝）
        return False
    return not (nonneg and val < 0)


class InfraCircuitBreaker:
    """链路级熔断器：连续 infra 失败达阈值 → 熔断，冷却后自动恢复。

    状态持久化到 .fenix/admin_infra_breaker.json（daemon 重启后恢复，防止重启
    重置熔断）；文件损坏/不可读按熔断复位 fail-open，不阻塞派发。

    链路标识（link）：v1 仅 "spec-review"；后续 SPEC 扩展 verify/impl。

    并发约束：仅同进程单实例使用（生产路径仅 engine 构造一例）。互斥只靠
    实例级 threading.Lock + 落盘原子替换；不做跨实例 flock——状态落盘为
    实例 cache 的整文件覆写，多实例并存时各自 cache 互不知晓，后写者会
    覆盖前者的计数与熔断窗口（flock 防不了 lost update，须锁内重读磁盘
    合并，见 _save_state 注释）。
    """

    def __init__(self, project_root, config: dict, logger=None):
        self.project_root = Path(project_root)
        self._logger = logger or _logger
        self._state_path = self.project_root / _BREAKER_STATE_FILE
        self._config = config or {}
        # 内存缓存：{link: {"count": int, "until": float, "state": str}}
        self._cache: dict = {}
        # 实例级锁：串行化 _cache 读改写与 _save_state（参照 engine._push_lock
        # 模式）。派发路径（engine.condition）与评审 worker（record_failure/
        # record_success）跨线程并发触碰同一实例，无锁会丢计数或重复落恢复事件。
        self._lock = threading.Lock()
        # 「record_failure 内部刚发生冷却到期恢复」一次性标志（per-link）：
        # 该路径返回值只暴露 triggered，恢复事实须经 take_recovery_flag 补给
        # 调用方（code-review item c3dfbbd563f5）。condition() 直接返回
        # "recovered"（调用方可见并由其落记录），不置本标志以免重复落。
        self._recovered_links: set[str] = set()
        self._load_state()

    # ── 日志（兼容 fenixd Logger 双参与标准 logging 单参）──────────────

    def _log(self, level: str, component: str, message: str):
        method = getattr(self._logger, level, None)
        if method is None:
            return
        if _is_fenixd_logger(self._logger):
            method(component, message)
        else:
            method(f"{component}: {message}")

    # ── 配置 ────────────────────────────────────────────────────────

    @property
    def threshold(self) -> int:
        """连续 infra 失败触发熔断的阈值（admin.run_infra_breaker.threshold）。

        范围守卫与 ConfigLoader.get_run_infra_breaker_config 一致（code-review
        item 8c2855513307）：bool / 非数值 / ``< 1`` / 非整值浮点一律回退缺省
        3——仅 int() 截断会让 ``0.5`` 变 0（首次 infra 失败即熔断）、``true``
        变 1、``2.5`` 变 2（与配置侧归一结果 3 分叉），阈值保护被静默收紧；
        非整值浮点拒绝与配置侧同口径（code-review item f03d70778889）。巨大
        int（YAML 任意精度）穿透 isinstance 与 ``< 1`` 比较后 ``int()`` 原样
        返回，阈值被静默抬到不可达（熔断保护失效且无留痕），补
        ``abs(val) > sys.float_info.max`` 拦截回退缺省（口径同
        _is_valid_state_number 与 cooldown_minutes 的巨大 int 裁决）。
        """
        try:
            val = self._get_config("threshold", 3)
            if (
                isinstance(val, bool)
                or not isinstance(val, (int, float))
                or val < 1
                or abs(val) > sys.float_info.max
                or (isinstance(val, float) and not val.is_integer())
            ):
                return 3
            return int(val)
        except (TypeError, ValueError, OverflowError):
            # 非有限浮点（.nan/.inf）穿透范围比较时按脏值回退缺省（不抛）
            return 3

    @property
    def cooldown_minutes(self) -> float:
        """熔断冷却时长（分钟，admin.run_infra_breaker.cooldown_minutes）。

        范围守卫与 ConfigLoader.get_run_infra_breaker_config 一致（code-review
        item 8c2855513307）：bool / 非数值 / ``<= 0`` 一律回退缺省 30.0——
        0/负数会使 until <= now，熔断即建即恢复，保护静默失效。非有限浮点
        （.nan/.inf）同样回退（code-review item d0a328355581）：``.inf`` 使
        until 永不到期（熔断永久），``.nan`` 使 now>=until 恒 False 同样永续
        熔断。巨大 int（YAML 任意精度）穿透类型守卫后送 math.isfinite 内部
        转 float 抛 OverflowError，同样按脏值回退缺省（口径同 threshold 与
        _is_valid_state_number）。
        """
        try:
            val = self._get_config("cooldown_minutes", 30)
            if not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0:
                return 30.0
            if not math.isfinite(val):
                # 非有限浮点（.nan/.inf）穿透范围比较时按脏值回退缺省（同 threshold）
                return 30.0
            return float(val)
        except (TypeError, ValueError, OverflowError):
            # 巨大 int 送 math.isfinite 内部转 float 抛 OverflowError → 按脏值
            # 回退缺省（不抛，同 threshold）
            return 30.0

    def _get_config(self, key: str, default):
        """取 admin.run_infra_breaker 段配置值（key 为段内字段名）。

        直读原始 config 的 admin.run_infra_breaker 段（不依赖 get_admin_config
        规范化路径——本熔断器可由 engine / 测试任意注入 config 独立工作）；
        段缺失/非法回退缺省（与 config.py D5 读取宽容语义一致）。
        """
        admin = self._config.get("admin") or {}
        ib = admin.get("run_infra_breaker") if isinstance(admin, dict) else None
        if not isinstance(ib, dict):
            return default
        val = ib.get(key)
        if val is None:
            return default
        return val

    # ── 持久化 ──────────────────────────────────────────────────────

    def _load_state(self):
        """从文件加载熔断状态。文件损坏/不可读 fail-open（不阻塞派发）。"""
        if not self._state_path.exists():
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                self._log(
                    "warning",
                    "infra_breaker",
                    f"熔断状态文件格式非法（应为 dict），fail-open 复位: {self._state_path}",
                )
                return
            for link, st in raw.items():
                if not isinstance(st, dict):
                    continue
                count = st.get("count", 0)
                until = st.get("until", 0.0)
                state = st.get("state", "closed")
                if not (
                    _is_valid_state_number(count, nonneg=True)
                    and _is_valid_state_number(until, nonneg=False)
                ):
                    # 脏值（NaN/Infinity/负数/bool 等）→ fail-open 复位该链路
                    # 为 closed，防非有限 until 使 now >= until 恒 False 致熔断
                    # 永续（code-review item 004678944eab，口径同配置侧
                    # cooldown_minutes 的 isfinite 守卫）。
                    self._log(
                        "warning",
                        "infra_breaker",
                        f"熔断状态含非法数值（link={link}），fail-open 复位为"
                        f" closed: {self._state_path}",
                    )
                    self._cache[link] = {"count": 0, "until": 0.0, "state": "closed"}
                    continue
                if state not in ("broken", "closed"):
                    # 非法 state（手改/版本代差写入未知值）→ 与上方数值脏值分支
                    # 同口径记 warning 并复位 closed（code-review item
                    # 4479f82451c7）：未知值使 condition() 的 =="broken" 判定恒
                    # False，熔断保护被静默禁用且无留痕。写入点均为小写字面量、
                    # 判定大小写敏感，故不做 lower() 归一放行，异形值按脏值
                    # fail-open 处理。
                    self._log(
                        "warning",
                        "infra_breaker",
                        f"熔断状态含非法 state（link={link}），fail-open 复位为"
                        f" closed: {self._state_path}",
                    )
                    self._cache[link] = {"count": 0, "until": 0.0, "state": "closed"}
                    continue
                self._cache[link] = {
                    "count": int(count),
                    "until": float(until),
                    "state": str(state),
                }
        except (OSError, json.JSONDecodeError, ValueError, TypeError, OverflowError) as e:
            self._log(
                "warning",
                "infra_breaker",
                f"熔断状态文件损坏，fail-open 复位: {self._state_path}: {e}",
            )
            self._cache.clear()

    def _save_state(self):
        """持久化熔断状态到文件。写失败仅记日志（不阻塞）。

        须持 ``self._lock`` 调用（锁不可重入，本方法不再自行取锁）；
        仅 ``__init__`` 阶段的 ``_load_state`` 不经锁（对象尚未共享）。
        """
        data = {}
        for link, st in self._cache.items():
            data[link] = {
                "count": st["count"],
                "until": st["until"],
                "state": st["state"],
            }
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            # 原子替换（code-review item b5580085c3bb：write_text 覆盖写中途
            # 崩溃会留下截断 JSON，下次 _load_state 解析失败 fail-open 复位，
            # 恰在 infra 持续故障时把熔断保护拆掉）：对齐 tokens.json 写法
            # （_append_token_run）的原子落盘半段——同目录 mkstemp + fsync +
            # os.replace；其 fcntl.flock 互斥半段不照搬：本类仅同进程单实例
            # 使用（生产路径仅 engine 构造一例），实例内 threading.Lock 已
            # 覆盖读-改-写窗口；跨实例 flock 也防不了各自 cache 整文件覆写
            # 的 lost update（须锁内重读磁盘合并，多实例不安全，见类
            # docstring 并发约束）。
            fd, tmp_str = tempfile.mkstemp(
                prefix=f".{self._state_path.name}.",
                suffix=".tmp",
                dir=str(self._state_path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(data, ensure_ascii=False, indent=2))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_str, str(self._state_path))
            finally:
                if os.path.exists(tmp_str):
                    try:
                        os.unlink(tmp_str)
                    except OSError:
                        pass
        except OSError as e:
            self._log("warning", "infra_breaker", f"熔断状态保存失败: {e}")

    def _ensure_link(self, link: str):
        """确保链接在缓存中存在。"""
        if link not in self._cache:
            self._cache[link] = {"count": 0, "until": 0.0, "state": "closed"}

    # ── 查询 ────────────────────────────────────────────────────────

    def condition(self, link: str, now: float | None = None) -> str:
        """返回链路熔断三态（短路点与恢复事件共用判定）。

        - "broken"：熔断窗口内（停止派发）；
        - "recovered"：刚冷却到期自动恢复（本调用把 broken 翻转为 closed，
          供调用方恰好落一条恢复 SIGNAL 记录，下次调用返回 "closed"）；
        - "closed"：正常（可派发）。

        冷却到期自动恢复（design D4 窗口滑动）：state=broken 且 now>=until →
        翻转 closed 并持久化；count 保留（恢复后首个失败将因 count 达标立即
        重新熔断——半开探测语义；首个成功经 record_success 清零）。
        """
        with self._lock:
            self._ensure_link(link)
            st = self._cache[link]
            if now is None:
                now = time.time()
            if st["state"] == "broken":
                if now >= st["until"]:
                    st["state"] = "closed"
                    self._save_state()
                    return "recovered"
                return "broken"
            return "closed"

    def is_open(self, link: str, now: float | None = None) -> bool:
        """链路是否处于熔断窗口（不派发）。冷却到期自动恢复。"""
        if now is None:
            now = time.time()
        return self.condition(link, now) == "broken"

    def cooldown_remaining(self, link: str, now: float | None = None) -> int:
        """熔断剩余秒数；已恢复返回 0。"""
        with self._lock:
            self._ensure_link(link)
            st = self._cache[link]
            if now is None:
                now = time.time()
            if st["state"] == "broken" and now < st["until"]:
                return int(st["until"] - now)
            return 0

    def get_state(self, link: str) -> dict:
        """返回链接的完整状态副本（供告警 evidence）。"""
        with self._lock:
            self._ensure_link(link)
            return dict(self._cache[link])

    # ── 写入 ────────────────────────────────────────────────────────

    def record_failure(self, link: str, now: float | None = None) -> bool | str:
        """记录一次 infra 失败。返回是否刚触发熔断（首次达到阈值）。

        - 计数递增；未熔断且达到阈值 → 触发熔断（until=now+cooldown）
        - 已处于熔断（半开探测失败）→ 重置冷却窗口（窗口滑动）
        - 冷却已到期但期间无人调用 condition() → 先按 recovered 口径翻转
          closed（与 condition() 的半开语义一致），再继续本次失败累计与触发；
          若随即再熔断返回 "recovered_then_triggered"（truthy，告警侧
          ``if triggered:`` 门控不受影响，同时得以先补一条 recovered 记录
          再记新触发）；恢复事实本身经 take_recovery_flag() 一次性标志补给
          调用方（本次失败未达阈值返回 False 时恢复记录也不丢）
        - 仅首次触发熔断返回 True（告警恰好落一条）
        """
        with self._lock:
            self._ensure_link(link)
            st = self._cache[link]
            if now is None:
                now = time.time()
            triggered = False
            recovered_expired = False

            # 冷却已到期但期间无人调用 condition()（如冷却窗内无任何 spec 进入
            # reviewing）：先按 condition() 的 recovered 口径把 broken 翻转为
            # closed（count 保留，半开探测语义一致）——否则直接落入下方 elif
            # 再熔断，告警流出现两条 triggered 之间无 recovered（code-review
            # item 899630a8897c）。先翻转也保证后续 condition() 看到的不是
            # 已到期 broken，不会重复返回 "recovered" 落第二条恢复记录。
            if st["state"] == "broken" and now >= st["until"]:
                st["state"] = "closed"
                recovered_expired = True
                # 恢复事实对 ``if triggered:`` 门控不可见于返回值（本次未达
                # 阈值时连 truthy 都没有）→ 置一次性标志供调用方经
                # take_recovery_flag 补落 recovered 记录
                self._recovered_links.add(link)

            st["count"] += 1

            if st["state"] == "broken" and now < st["until"]:
                # 已熔断（半开探测失败）→ 重置冷却窗口（不触发额外告警）
                st["until"] = now + self.cooldown_minutes * 60
            elif st["count"] >= self.threshold:
                # 未熔断且达到阈值 → 触发熔断
                st["state"] = "broken"
                st["until"] = now + self.cooldown_minutes * 60
                triggered = True

            self._save_state()
            if recovered_expired and triggered:
                # 区分「冷却到期未消费即再熔断」的标记（truthy）
                return "recovered_then_triggered"
            return triggered

    def take_recovery_flag(self, link: str) -> bool:
        """取走「record_failure 内部刚发生冷却到期恢复」标志（消费即清除）。

        record_failure 把到期 broken 翻转为 closed 时置位——该路径返回值只
        暴露 triggered，本次失败未达阈值时连 truthy 都没有，恢复记录会被
        告警侧 ``if triggered:`` 门控静默吞掉（code-review item
        c3dfbbd563f5）；调用方在 record_failure 之后取走标志补落 recovered
        记录。仅首次取用返回 True，重复取返回 False。condition() 的翻转不置
        本标志（其返回 "recovered" 调用方可见，已由调用点落记录）。
        """
        with self._lock:
            if link in self._recovered_links:
                self._recovered_links.discard(link)
                return True
            return False

    def record_success(self, link: str):
        """成功 run：清零计数，重置为正常状态。

        落实「连续 ≥3 次」语义：熔断前/恢复后任意成功均清零。

        evo-add-review-failure-attribution 2.2/2.3 接线确认：spec-review 链路
        的调用点在 spec_review.py 评审 run 成功收工处（run_ok=True 即清零，
        「链路证明可用」语义——run 跑通但产物不合法走 content 类重试的分支
        同样经过；产物质量类失败不影响 infra 计数）。熔断短路期间未实际
        派发的尝试在 dispatch_review 入口 condition()=="broken" 即返回，
        到不了该调用点，不计成功/失败；「冷却到期后首次派发成功」路径下
        condition() 恢复时保留的半开残留 count 由此处清零。
        """
        with self._lock:
            self._ensure_link(link)
            st = self._cache[link]
            st["count"] = 0
            st["until"] = 0.0
            st["state"] = "closed"
            self._save_state()

    def reset(self, link: str):
        """复位熔断器（fail-open 路径或管理员干预）。"""
        with self._lock:
            self._ensure_link(link)
            self._cache[link] = {"count": 0, "until": 0.0, "state": "closed"}
            self._save_state()
