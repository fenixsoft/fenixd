"""
registry.py — 多项目发现与注册（dashboard-server D3）。

中心配置文件 `~/.config/fenixd/dashboard.yaml`：
    port: 8787
    projects:
      - name: <别名>
        path: <项目绝对路径>
    scan_dirs:
      - <父目录>

`discover()` 合并显式 projects 与 scan_dirs 扫描结果；扫描仅当目录存在
`.fenix/STATE.md` 即识别为 Fenixd 项目（无需 `.fenix/config.yaml`）。显式注册的
项目始终出现在监控列表（即使目录不存在，标记 exists=False）。

默认扫描：`scan_dirs` 未配置（或为空）时，自动以用户主目录 `~` 为唯一扫描根
遍历一级子目录做发现（自动发现为主）；显式配置 `scan_dirs` 可覆盖该默认。
显式注册（`add_project`）为扫描的补充，可纳入扫描范围之外的路径。
"""

import errno
import logging
import os
import tempfile
import threading
import yaml
from pathlib import Path

# 可传播到 fenixd 已挂载 handler 的结构化日志器（fix-robustness-edge-cases 3.1：
# 收敛旁路裸 getLogger(__name__)=core.dashboard.registry，保证 WARNING 落盘）
logger = logging.getLogger("fenixd.dashboard.registry")

DEFAULT_PORT = 8787
DEFAULT_CONFIG = Path.home() / ".config" / "fenixd" / "dashboard.yaml"


class Registry:
    """读写监控配置并执行多项目发现。"""

    # 配置读-改-写的进程内互斥（code-review item 2f4301b32a85）：dashboard 经
    # ThreadingHTTPServer 服务请求，add_ignored/remove_project/mark_fixture 等
    # 直接走 `load() → mutate → save()`。无锁时两个并发请求会互相覆盖（整份
    # YAML 文档后写者胜），且旧 save 复用同一临时路径 `.yaml.tmp`，重叠写会把
    # 两次写入交错进同一文件。类级 RLock：同进程内所有 Registry 实例共用一把锁
    # （跨进程场景由 CLI/dashboard 各自单写，不在本锁范围）。
    _SAVE_LOCK = threading.RLock()

    def __init__(self, config_path=None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG

    # ── 忽略列表（软删除：被忽略路径不再被显式/扫描发现） ──────────

    @staticmethod
    def _norm(path) -> str:
        """规范化路径（展开 ~ 与软链接，解析为绝对路径）。

        恒返回 str（code-review item d8c059571002）：畸形条目一律降级——
        非字符串（如 ignored: [123] 的 int，Path() 抛 TypeError）、无法解析
        的 ~user（expanduser 抛 RuntimeError）、resolve 的 OSError，MUST NOT
        让单条脏配置炸穿 discover/add_ignored 等调用方。旧实现的 except
        处理器自身在守卫外再调 expanduser，同类异常会二次抛出。
        """
        try:
            return str(Path(path).expanduser().resolve())
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        try:
            return str(Path(path).expanduser())
        except (OSError, RuntimeError, TypeError, ValueError):
            return str(path)

    # ── 子目录探测（容错三态：present / absent / unreadable）──────────

    _PROBE_PRESENT = "present"
    _PROBE_ABSENT = "absent"
    _PROBE_UNREADABLE = "unreadable"

    # pathlib.Path.is_file()/_is_dir() 内部只吞 ENOENT/ENOTDIR/EBADF/ELOOP，
    # 但 EIO 等其它 OSError 会直接上抛。这里显式捕获以区分「正常不存在」与「不可读」。
    # （code-review item f7dc193f07fe：原 _ABSENT_ERRNOS 常量声明后从未被引用，
    # 自相矛盾地「记录了未实现的行为」——probe_child 实际对任一 OSError 都判
    # unreadable。已删除该死常量，语义以 _log_unreadable 实现为准。）

    def probe_child(self, child: Path) -> str:
        """对扫描候选子目录执行 is_dir() + .fenix/STATE.md is_file() 探测。

        返回三态：
          present    —— 是目录且存在 .fenix/STATE.md（Fenixd 项目）
          absent     —— 正常不存在（非目录，或缺少 STATE.md），静默
          unreadable —— 探测抛 OSError（含 EIO），写 WARNING 日志后跳过

        实现须显式 try/except OSError——MUST NOT 依赖 pathlib 默认吞异常
        （其 _IGNORED_ERROS 不含 EIO，EIO 会直接上抛）。
        """
        # 目录类型判断
        try:
            if not child.is_dir():
                return self._PROBE_ABSENT
        except OSError as exc:
            return self._log_unreadable(child, exc)

        # .fenix/STATE.md 存在性探测
        state_path = child / ".fenix" / "STATE.md"
        try:
            if not state_path.is_file():
                return self._PROBE_ABSENT
        except OSError as exc:
            return self._log_unreadable(child, exc)

        return self._PROBE_PRESENT

    @staticmethod
    def _log_unreadable(path: Path, exc: OSError) -> str:
        """对「不可读」子目录写一条 WARNING 日志并返回 unreadable 三态。"""
        errno_code = errno.errorcode.get(exc.errno, "?")
        logger.warning(
            "发现层跳过不可读路径 %s（%s, errno=%s）: %s",
            path,
            errno_code,
            exc.errno,
            exc,
        )
        return Registry._PROBE_UNREADABLE

    # ── 配置读写 ─────────────────────────────────────────────

    def load(self) -> dict:
        """读取配置；缺失/损坏时返回默认结构。"""
        data, _ = self._load_checked()
        return data

    def _load_checked(self) -> tuple:
        """load() 的带状态版本：区分「文件不存在」与「存在但读取/解析失败」。

        返回 (data, load_error)：
          load_error=None —— 文件不存在（返回干净的默认结构，可正常写回），
            或读取解析成功；
          load_error=exc  —— 文件存在但 read_text 抛 OSError、YAML 解析失败
            （含用户手改产生的语法错误），或解析成功但顶层不是映射
            （code-review item 4656307bf332：手改成列表/标量的文件同样带毒，
             不能视为干净默认），data 为默认结构。该默认结构带毒：
            add_project/add_ignored/mark_fixture/remove_project 的 load→mutate→save
            链路一旦据此写回，损坏/暂不可读的原始配置即被只有新条目的默认结构
            整份覆盖，用户全部项目注册与忽略列表不可恢复地丢失
            （code-review item 27a41212fb75）——写方法须拒绝 save。
        """
        defaults = {"port": DEFAULT_PORT, "projects": [], "scan_dirs": [], "ignored": []}
        if not self.config_path.exists():
            return defaults, None
        try:
            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
            return defaults, exc
        if not isinstance(data, dict):
            # code-review item 4656307bf332：合法 YAML 但顶层非映射（如整份
            # 列表/标量）与解析失败同毒——旧实现返回 (defaults, None) 会使
            # 27a41212fb75 的带毒守卫失效，写方法用默认结构整份覆盖原文件。
            # 构造描述性错误对象，走 _load_for_write 的统一拒写口径。
            return defaults, ValueError(
                f"配置文件顶层不是映射（而是 {type(data).__name__}）"
            )
        # code-review item 1c3eb3a7bdd5：以读入 dict 为基底做键级归一化（保留
        # 用户/第三方工具写入的未知顶层键），仅对四个已知键做容错归一——旧实现
        # 只重建 4 个键，add_project 等任一写操作的 save 会把其余顶层键静默丢弃。
        out = dict(data)
        # [fenix-ignore:664c907a50c4] 唯一消费方 bin/fenix_dashboard.py run_serve 已有 int() + TypeError/ValueError 兜底回退 DEFAULT_PORT，非法 port 不会拖到启动报错
        out["port"] = data.get("port") or DEFAULT_PORT
        out["projects"] = data.get("projects") or []
        out["scan_dirs"] = data.get("scan_dirs") or []
        out["ignored"] = data.get("ignored") or []
        if not isinstance(out["projects"], list):
            out["projects"] = []
        if not isinstance(out["scan_dirs"], list):
            out["scan_dirs"] = []
        if not isinstance(out["ignored"], list):
            out["ignored"] = []
        return out, None

    def _load_for_write(self) -> tuple:
        """写方法专用读入：load + 带毒检查，返回 (data, error_message)。

        可正常写回时 error_message 为 None；文件存在但读取/解析失败、或解析
        成功但顶层非映射时返回可读错误，调用方按 (False, message) 契约直接
        返回且 MUST NOT save（code-review item 27a41212fb75、4656307bf332）。
        """
        data, load_error = self._load_checked()
        if load_error is None:
            return data, None
        return data, (
            f"配置 {self.config_path} 读取/解析失败或顶层结构非法（{load_error}），"
            "已拒绝写回以免整份覆盖丢失；请先手工修复该文件后重试"
        )

    def save(self, data: dict):
        """写回配置（确保目录存在；原子替换，唯一临时路径）。

        用 ``tempfile.mkstemp`` 取进程唯一临时名 + ``os.replace`` 原子替换：
        旧实现固定借用 ``<config>.yaml.tmp``，两个并发 save 会写同一文件并
        互相截断（code-review item 2f4301b32a85）。
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_str = tempfile.mkstemp(
            prefix=f".{self.config_path.name}.", suffix=".tmp", dir=str(self.config_path.parent)
        )
        try:
            try:
                f = open(fd, "w", encoding="utf-8")
            except OSError:
                # open 失败不会接管 fd（code-review item e55c2da78214）：不显式
                # 关闭则描述符泄漏——finally 只负责 unlink 临时文件。close 自身
                # 再失败（fd 已坏）不吞掉原始异常。
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
            with f:
                f.write(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_str, str(self.config_path))
        finally:
            tmp_path = Path(tmp_str)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _save_or_error(self, data: dict):
        """写方法的 save 契约包装（code-review item 30ea99a516eb）。

        save 内部 mkdir/mkstemp/write/fsync/os.replace 抛出的 OSError
        （EACCES、ENOSPC、目录被删等）若穿透 add_project/mark_fixture/
        remove_project/add_ignored，会破坏「返回 (bool, message)、不抛异常」
        契约——这里统一捕获转错误消息；成功返回 None。
        """
        try:
            self.save(data)
        except OSError as exc:
            return f"写回配置失败: {exc}"
        return None

    # ── 发现 ─────────────────────────────────────────────────

    @staticmethod
    def _dir_exists(path: Path) -> bool:
        """``is_dir()`` 的 OSError 容错包装：探测失败按 False（不可达 ≠ 存在）。

        裸 ``rp.is_dir()`` 在 EIO/EACCES 等 pathlib 不吞的 errno 上抛 OSError，
        会中止整个 ``discover()``（丢掉后续全部显式项目与扫描结果，
        code-review item a0e0813c0f88）。探测失败降级 exists=False + WARNING。
        """
        try:
            return path.is_dir()
        except OSError as exc:
            logger.warning("发现层探测项目路径失败 %s: %s", path, exc)
            return False

    @staticmethod
    def _state_md_is_file(path: Path) -> bool:
        """``is_file()`` 的 OSError 容错包装：探测失败按 False + WARNING。

        同 _dir_exists：裸 is_file() 的 EIO/EACCES 会逃出 ``add_project``，
        破坏其「返回 (added, message) 元组」契约并崩掉 HTTP 路由/CLI
        （code-review item a0e0813c0f88）。
        """
        try:
            return path.is_file()
        except OSError as exc:
            logger.warning("发现层探测 STATE.md 失败 %s: %s", path, exc)
            return False

    def discover(self) -> list:
        """合并显式配置与目录扫描，返回 [{name, path, discovered, exists, fixture}]。

        合并后按 `ignored` 列表过滤规范化路径——被忽略项目（无论显式注册
        还是自动发现）一律不再出现在监控列表，实现软删除语义。

        `fixture` 为「该项目是验证夹具、其数据为验证噪音」的权威标记：
        显式条目仅当配置键为布尔真（``fixture: true``）时为真——缺省、假值
        与非布尔值（如字符串 "yes"）一律按假处理；扫描发现的项目恒为假
        （扫描无法判定夹具属性，缺省保守=非夹具，宁多展示不静默隐藏）。
        """
        data = self.load()
        ignored = {self._norm(x) for x in data.get("ignored", []) if x}
        projects = []
        seen = set()

        for p in data.get("projects", []):
            if not isinstance(p, dict):
                continue
            raw = p.get("path", "")
            # 类型校验（code-review item 90f925a2042b）：path 缺失/为空时
            # Path("").resolve() 返回当前工作目录——畸形条目会静默把 dashboard
            # 进程 CWD 注册成受监控项目（exists=True）；非字符串 path（手改/
            # 畸形 YAML 的 path: 123、path: {a: b}）让 Path(...) 抛 TypeError
            # 穿透 discover，破坏模块故障隔离契约。两类条目一律跳过并告警。
            if not isinstance(raw, str) or not raw.strip():
                logger.warning("显式项目条目 path 缺失/为空/非字符串，跳过: %r", p)
                continue
            try:
                rp = Path(raw).expanduser().resolve()
            except (OSError, RuntimeError, ValueError) as exc:
                # 留痕口径与上方 path 守卫、下方 scan_dirs 守卫一致（item
                # aa30f6864549）：~user 无法解析（RuntimeError）、resolve 遇
                # EIO（OSError）等解析失败同样无声吞掉显式项目，须告警。
                logger.warning("显式项目条目路径解析失败，跳过: %r: %s", p, exc)
                continue
            key = str(rp)
            if key in ignored:
                continue
            if key in seen:
                continue
            seen.add(key)
            # 类型守卫（code-review item a5535e261c2c）：与上方 path、下方
            # scan_dirs 同式——name 非字符串（手改/畸形 YAML 的 name: 123、
            # name: [a]）会绕过 falsy 回退把 int/list 原样放进监控列表，
            # 破坏下游按字符串处理 name 的契约；非字符串/空白一律回退
            # rp.name or key。
            name = p.get("name")
            if not isinstance(name, str) or not name.strip():
                name = rp.name or key
            projects.append(
                {
                    "name": name,
                    "path": key,
                    "discovered": False,
                    "exists": self._dir_exists(rp),
                    "fixture": p.get("fixture") is True,
                }
            )

        # 扫描根：显式配置 scan_dirs 时沿用该配置（覆盖默认）；未配置（或为空）
        # 时默认以用户主目录 ~ 为唯一扫描根，遍历其一级子目录做自动发现。
        scan_dirs = data.get("scan_dirs", [])
        if not scan_dirs:
            scan_dirs = [str(Path.home())]
        for sd in scan_dirs:
            # 类型守卫（code-review item 03bc59736158）：与上方 projects 条目
            # 同式——load() 只校验 scan_dirs 是 list 不校验元素类型，非字符串/
            # 空白条目（手改 YAML 的 scan_dirs: [123]）让 Path(...) 抛 TypeError
            # 穿透 discover，崩掉整个发现层；一律跳过并告警。
            if not isinstance(sd, str) or not sd.strip():
                logger.warning("扫描根条目缺失/为空/非字符串，跳过: %r", sd)
                continue
            try:
                base = Path(sd).expanduser()
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
            try:
                if not base.is_dir():
                    continue
            except OSError:
                continue
            try:
                children = sorted(base.iterdir())
            except OSError:
                # 扫描根整体不可读：跳过该根，继续处理其余扫描根与显式项目
                continue
            for child in children:
                # 忽略过滤前置：任何可能抛 OSError 的探测之前先短路，
                # 使软删除对不可读路径同样生效（写侧与读侧共用 _norm）。
                key = self._norm(child)
                if key in ignored:
                    continue
                if key in seen:
                    continue
                # 三态探测：present（Fenixd 项目）/ absent（静默跳过）/
                # unreadable（写 WARNING 日志后跳过），均不中断整体发现。
                if self.probe_child(child) != self._PROBE_PRESENT:
                    continue
                seen.add(key)
                projects.append(
                    {
                        "name": child.name or key,
                        "path": key,
                        "discovered": True,
                        "exists": True,
                        "fixture": False,
                    }
                )

        return projects

    # ── 注册 ─────────────────────────────────────────────────

    def add_project(self, path, name=None, fixture=False) -> tuple:
        """注册项目到配置（按路径去重）。

        fixture=True 时在配置条目写入 `fixture` 标记（夹具项目权威标识）；
        对已存在同路径条目保持「跳过」语义——不重复添加、不静默改标记
        （存量条目标记的更新须经 mark_fixture 显式发起）。

        Returns: (added: bool, message: str)
        """
        try:
            rp = Path(path).expanduser().resolve()
        # 769245a1c0c2：捕获清单对齐 _norm（空字节入参抛 ValueError、
        # 非字符串入参抛 TypeError），守住「返回 (bool, message)、不抛异常」契约。
        except (OSError, RuntimeError, TypeError, ValueError):
            return False, f"无效路径: {path}"
        key = str(rp)

        # load→mutate→save 整段持锁（code-review item 2f4301b32a85：
        # ThreadingHTTPServer 下并发写请求会互相覆盖整份 YAML）。
        with self._SAVE_LOCK:
            # 读失败带毒守卫（code-review item 27a41212fb75）：拒绝以默认结构
            # 覆盖写回损坏/暂不可读的原始配置。
            data, load_error = self._load_for_write()
            if load_error is not None:
                return False, load_error
            for p in data.get("projects", []):
                if not isinstance(p, dict):
                    continue
                raw = p.get("path", "")
                # 类型守卫（code-review item ed1b8c91b255）：非字符串 path（畸形
                # YAML 的 path: 123）会让 Path(...) 抛 TypeError 穿透——与 discover
                # 同式守卫，畸形条目跳过，保住「返回 (bool, message)、不抛异常」契约。
                if not isinstance(raw, str) or not raw.strip():
                    continue
                try:
                    existing = str(Path(raw).expanduser().resolve())
                except (OSError, RuntimeError, ValueError):
                    continue
                if existing == key:
                    return False, f"项目已在监控列表: {key}"

            if not Registry._state_md_is_file(rp / ".fenix" / "STATE.md"):
                return False, f"目录不是 Fenixd 项目（缺少 STATE.md）: {key}"

            data.setdefault("projects", []).append(
                {
                    "name": name or (rp.name or key),
                    "path": key,
                    # code-review item 4346360f4dd6：与 mark_fixture 的
                    # bool(fixture) 口径对齐——非布尔真值（如 "yes"）若原样
                    # 落盘，discover 按 `is True` 判定恒为假，形成「写进去
                    # 了却不生效」的静默漂移。
                    "fixture": bool(fixture),
                }
            )
            # code-review item 30ea99a516eb：save 的 OSError 转错误消息，
            # 不穿透 (bool, message) 契约（下同）。
            save_error = self._save_or_error(data)
            if save_error is not None:
                return False, save_error
            return True, f"已注册项目: {key}"

    def mark_fixture(self, path, fixture=True) -> tuple:
        """按规范化路径定位配置条目并写入/更新 `fixture` 键后写回。

        add_project 对已存在同路径条目「跳过」（不重复添加、不静默改标记）；
        存量条目标记的显式更新（如夹具供给脚本对已登记夹具补 `fixture: true`）
        必须经本方法发起。目标路径不在配置中时返回未变更提示且不抛异常。

        Returns: (updated: bool, message: str)
        """
        try:
            rp = Path(path).expanduser().resolve()
        # 769245a1c0c2：捕获清单对齐 _norm（空字节入参抛 ValueError、
        # 非字符串入参抛 TypeError），守住「返回 (bool, message)、不抛异常」契约。
        except (OSError, RuntimeError, TypeError, ValueError):
            return False, f"无效路径: {path}"
        key = str(rp)

        with self._SAVE_LOCK:
            # 读失败带毒守卫（code-review item 27a41212fb75）：拒绝以默认结构
            # 覆盖写回损坏/暂不可读的原始配置。
            data, load_error = self._load_for_write()
            if load_error is not None:
                return False, load_error
            for p in data.get("projects", []):
                if not isinstance(p, dict):
                    continue
                raw = p.get("path", "")
                # 类型守卫（code-review item ed1b8c91b255）：非字符串 path 会让
                # Path(...) 抛 TypeError 穿透（与 discover 同式），畸形条目跳过。
                if not isinstance(raw, str) or not raw.strip():
                    continue
                try:
                    existing = str(Path(raw).expanduser().resolve())
                except (OSError, RuntimeError, ValueError):
                    continue
                if existing == key:
                    p["fixture"] = bool(fixture)
                    save_error = self._save_or_error(data)
                    if save_error is not None:
                        return False, save_error
                    return True, f"已更新夹具标记: {key}"
            return False, f"项目未在监控列表（无需变更）: {key}"

    def remove_project(self, path) -> tuple:
        """从配置 `projects` 移除显式注册的项目（按规范化路径匹配）并写回。

        未在配置中显式注册（含仅由扫描自动发现的项目）时返回未变更提示，
        不报错。返回: (removed: bool, message: str)
        """
        try:
            rp = Path(path).expanduser().resolve()
        # 769245a1c0c2：捕获清单对齐 _norm（空字节入参抛 ValueError、
        # 非字符串入参抛 TypeError），守住「返回 (bool, message)、不抛异常」契约。
        except (OSError, RuntimeError, TypeError, ValueError):
            return False, f"无效路径: {path}"
        key = str(rp)

        with self._SAVE_LOCK:
            # 读失败带毒守卫（code-review item 27a41212fb75）：拒绝以默认结构
            # 覆盖写回损坏/暂不可读的原始配置。
            data, load_error = self._load_for_write()
            if load_error is not None:
                return False, load_error
            remaining = []
            removed = False
            for p in data.get("projects", []):
                if not isinstance(p, dict):
                    remaining.append(p)
                    continue
                raw = p.get("path", "")
                # 类型守卫（code-review item ed1b8c91b255）：非字符串 path 会让
                # Path(...) 抛 TypeError 穿透（与 discover 同式）；畸形条目原样保留。
                if not isinstance(raw, str) or not raw.strip():
                    remaining.append(p)
                    continue
                try:
                    existing = str(Path(raw).expanduser().resolve())
                except (OSError, RuntimeError, ValueError):
                    remaining.append(p)
                    continue
                if existing == key:
                    removed = True
                    continue
                remaining.append(p)

            if not removed:
                return False, f"项目未在监控列表（无法移除）: {key}"
            data["projects"] = remaining
            save_error = self._save_or_error(data)
            if save_error is not None:
                return False, save_error
            return True, f"已从监控列表移除: {key}"

    def add_ignored(self, path) -> tuple:
        """把规范化路径追加进 `ignored` 列表（去重）并写回。

        软删除项目的实现：被忽略路径不再被显式/扫描发现（discover 过滤）。
        项目文件、配置、数据全部保留；恢复 = 手工从列表移除该路径。

        Returns: (added: bool, message: str)
        """
        # `_norm` 内部已吞 OSError/RuntimeError 并恒返回 str（code-review item
        # ff5c3d5d74d9：此处旧有的 try/except 永不可达），直接调用即可。
        key = self._norm(path)

        with self._SAVE_LOCK:
            # 读失败带毒守卫（code-review item 27a41212fb75）：拒绝以默认结构
            # 覆盖写回损坏/暂不可读的原始配置。
            data, load_error = self._load_for_write()
            if load_error is not None:
                return False, load_error
            ignored = data.get("ignored") or []
            if not isinstance(ignored, list):
                ignored = []
            if key in {self._norm(x) for x in ignored if x}:
                return False, f"项目已在忽略列表: {key}"
            ignored.append(key)
            data["ignored"] = ignored
            save_error = self._save_or_error(data)
            if save_error is not None:
                return False, save_error
            return True, f"已加入忽略列表: {key}"

    def is_ignored(self, path) -> bool:
        """查询某路径是否已被忽略（按规范化路径比较）。"""
        # _norm 恒返回 str（内部已吞 OSError），无需外层 try/except
        # （code-review item ff5c3d5d74d9）。
        key = self._norm(path)
        data = self.load()
        return key in {self._norm(x) for x in data.get("ignored", []) if x}

    def list_projects(self) -> list:
        """仅返回配置中显式注册的项目（供 --list-projects）。"""
        data = self.load()
        out = []
        for p in data.get("projects", []):
            if not isinstance(p, dict):
                continue
            out.append(
                {
                    "name": p.get("name"),
                    "path": p.get("path"),
                }
            )
        return out
