"""self_update.py — 框架与 dsh-plugins 自动更新引擎（检查与状态面）。

add-auto-update SPEC 的更新引擎（检查侧）：版本发现、releases/latest 远端
查询、周期检查编排与框架级状态落盘。更新应用侧（下载换装编排）见
``core/self_update_apply.py``；dashboard 路由与 CLI（bin/fenix_update.py）
只消费本模块的编排入口，不含第二份实现。

关键纪律：
- 零第三方依赖（stdlib urllib + 既有 core 模块），框架 pip 依赖面零膨胀
  （design D1）；
- 时间一律经 ``core.timelib``（存储 aware UTC，``to_storage`` 序列化）；
- 原子写收口 ``core.fs_utils.atomic_write_text``（mkstemp + os.replace）；
- 互斥用同目录 O_EXCL 占位 lock 文件 + 陈锁清扫（与既有 spec 信号通道同族，
  design D3）——不用 flock：检查是低频轻量操作，占位文件语义即够，且
  Windows 后端 msvcrt.locking 语义差异无需引入；
- 检查失败静默留存原因（status.json ``last_error`` + 退避 ``next_check_after``），
  绝不打告警、绝不重试轰炸（design D2）。

状态文件位置（框架级、换装存续）：``~/.fenix/update/``——用户级目录不随
框架目录换装迁移，多项目 daemon 天然共享同一份状态（design D3）。
"""

import json
import logging
import math
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from core.config import USER_CONFIG_DIR, ConfigLoader
from core.fs_utils import atomic_write_text
from core.timelib import now_utc, parse_ts, to_storage

logger = logging.getLogger("fenixd.self_update")

# ── 常量 ──────────────────────────────────────────────────────────────────

# GitHub 仓库（spec：fenixd 公开仓匿名直查、dsh-plugins 双腿兼容）
FRAMEWORK_REPO = "fenixsoft/fenixd"
PLUGINS_REPO = "fenixsoft/dsh-plugins"
GITHUB_API_BASE = "https://api.github.com"
# 制品下载 URL 前缀（mirror 只替换该前缀，API 域名不替换，design D8）
GITHUB_DOWNLOAD_PREFIX = "https://github.com"

# 状态目录与文件（框架级共享；参数缺省绑定到模块全局，测试可 monkeypatch）
UPDATE_DIR = USER_CONFIG_DIR / "update"
STATUS_PATH = UPDATE_DIR / "status.json"
# 下载进度小文件（apply 分离进程高频覆写；UI 轮询仅在 apply 进行中读）。
# 独立于 status.json：不进 STATUS_LOCK_PATH 互斥面（见下），写失败只降级。
PROGRESS_PATH = UPDATE_DIR / "progress.json"
AUDITS_PATH = UPDATE_DIR / "audits.jsonl"
CHECK_LOCK_PATH = UPDATE_DIR / "check.lock"
APPLY_LOCK_PATH = UPDATE_DIR / "apply.lock"
# status.json 读合并写专用互斥（code-review item 1ec38cb01b7a）：check/apply
# 两条编排各持独立编排锁、互不互斥，但都经 update_status/mark_apply_phase
# 对同一份 status.json 做「读-合并-整写」；编排阶段可达分钟级，交叉并发下
# 陈旧读底覆写会互相丢状态。收敛为单一互斥面：本锁仅在 update_status 内部
# 短暂持有、内部不再取任何编排锁，锁序恒为编排锁→status.lock，无死锁面。
STATUS_LOCK_PATH = UPDATE_DIR / "status.lock"
# 持锁面毫秒级（读-合并-原子写），60s 陈锁清扫远超上界；等待超限降级为
# 无锁直写（不丢写，与既有无守卫行为等价）。
STATUS_LOCK_STALE_S = 60
STATUS_LOCK_WAIT_S = 2.0
STATUS_LOCK_POLL_S = 0.05

# 陈锁清扫阈值：check.lock 覆盖一次同步检查（网络超时量级），15 分钟远超上界；
# apply.lock 覆盖整次换装编排（下载+停起服务），正常分钟级，2 小时兜底
# 编排进程被 SIGKILL 留下的死锁（幂等恢复依赖陈锁清扫得以再次执行）。
CHECK_LOCK_STALE_S = 15 * 60
APPLY_LOCK_STALE_S = 2 * 3600

# 配置缺省值（design D8；config.user.template.yaml 只注释不固化，缺省由代码兜底）
UPDATE_ENABLED_DEFAULT = True
UPDATE_INTERVAL_HOURS_DEFAULT = 24.0
# 缺省下载通道（2026-11-28 实证：部分网络对 GitHub 直连不稳定——Connection
# reset / 慢速滴流，ghfast 镜像全量下载校验通过）：``update.mirror`` 键缺失
# 时缺省走镜像；显式 ``mirror: ""`` 才是官方直连（write_update_mirror 空串
# 持久化键，键缺失 ≠ 显式官方）。镜像下载失败自动回退官方直连（双通道候选
# 列表，download_channel_urls / self_update_apply 消费）。值必须为 gh-proxy
# 形态「镜像域名 + 完整原路径尾巴」（apply_mirror_url 只做前缀拼接）。
UPDATE_MIRROR_DEFAULT = "https://ghfast.top/https://github.com"
# 检查失败退避（小时）：2^(n-1) 小时起（1h/2h/4h…），封顶 interval_hours。
# 24h 周期 + 匿名限流 60/h 下远低于限流面（design D2 风险面）。
CHECK_FAILURE_BACKOFF_BASE_HOURS = 1.0

# 远端单次查询超时（秒，design D2「单次查询带超时」）
QUERY_TIMEOUT_S = 15.0

# 安装形态枚举
FORM_ARTIFACT = "artifact"
FORM_SOURCE = "source"

# dsh-plugins 目录名 → tag 解析（现状兼容主源：目录名 dsh-plugins-<tag>，
# design D1；制品根 VERSION 文件优先，为插件仓未来进包留兼容位）
PLUGINS_DIRNAME_RE = re.compile(r"^dsh-plugins-(.+)$")

# 状态文件 schema 版本（读侧以 schema 兼容判读；结构变更时递增）
STATUS_SCHEMA = 1

# apply 阶段枚举（self_update_apply 写侧与本模块读侧共享词表）
APPLY_PHASE_IDLE = "idle"
APPLY_PHASE_QUEUED = "queued"
APPLY_PHASE_RUNNING = "running"
APPLY_PHASE_SUCCESS = "success"
APPLY_PHASE_FAILED = "failed"


# ── 配置面（1.1）──────────────────────────────────────────────────────


@dataclass
class UpdateConfig:
    """``update:`` 配置段归一结果（键缺失/类型非法回退缺省，不抛异常）。

    ``mirror`` 字段语义（2026-11-28 默认镜像通道）：经 ``load_update_config``
    读出时键缺失/非字符串 → ``UPDATE_MIRROR_DEFAULT``（缺省镜像），显式
    ``""`` → 官方直连，其余字符串 → 用户配置的镜像。数据类自身缺省 ``""``
    仅表达「未配置」（引擎外的直接构造面，如测试注入）。
    """

    enabled: bool = UPDATE_ENABLED_DEFAULT
    interval_hours: float = UPDATE_INTERVAL_HOURS_DEFAULT
    mirror: str = ""


def _load_user_config_lenient() -> dict:
    """宽松读用户级 config.yaml（复用 ConfigLoader 既有加载路径）。

    走 ``ConfigLoader._load_optional_yaml``——resolve_config 对用户级文件的
    同一宽松入口（语法错误脱敏留痕、顶层非对象降级空 dict），更新引擎读
    配置 MUST NOT 因无关键的配置错误抛异常阻断检查。文件缺失返回 {}。
    """
    try:
        return ConfigLoader._load_optional_yaml(
            USER_CONFIG_DIR / "config.yaml", "用户级"
        )
    except Exception:  # noqa: BLE001 — 配置读取任何异常都不阻断更新检查
        return {}


def _coerce_bool(value, default: bool) -> bool:
    """宽松布尔归一：仅接受 bool，其余（含显式 null/字符串）回退缺省。"""
    if isinstance(value, bool):
        return value
    return default


def _coerce_positive_number(value, default: float) -> float:
    """宽松正数归一：接受 int/float 且 >0，否则回退缺省。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        try:
            v = float(value)
        except (OverflowError, ValueError):
            return default
        if math.isfinite(v) and v > 0:  # 排除 NaN/inf（inf 令 timedelta 抛 OverflowError）
            return v
    return default


def _coerce_str(value, default: str = "") -> str:
    """宽松字符串归一：str 原样（strip），其余回退缺省。"""
    if isinstance(value, str):
        return value.strip()
    return default


def load_update_config(config: Optional[dict] = None) -> UpdateConfig:
    """读 ``update:`` 段（enabled/interval_hours/mirror），非法值回退缺省。

    ``config`` 参数注入已解析的有效配置（测试缝/调用方已持配置时免重复读盘）；
    缺省宽松读用户级 ``~/.fenix/config.yaml``。update 段按 design D8 属用户级
    作用域——项目级配置不参与（更新是框架级语义）。
    """
    if config is None:
        config = _load_user_config_lenient()
    seg = config.get("update") if isinstance(config, dict) else None
    if not isinstance(seg, dict):
        seg = {}
    mirror_raw = seg.get("mirror")
    # 三态区分：字符串（含 ""=显式官方直连）原样采纳；键缺失/显式 null/
    # 非字符串垃圾值 → 缺省镜像通道（垃圾值 = 用户未表达通道选择，不静默
    # 落到直连这条已实证不稳的路径上）。
    if isinstance(mirror_raw, str):
        mirror = mirror_raw.strip()
    else:
        mirror = UPDATE_MIRROR_DEFAULT
    return UpdateConfig(
        enabled=_coerce_bool(seg.get("enabled"), UPDATE_ENABLED_DEFAULT),
        interval_hours=_coerce_positive_number(
            seg.get("interval_hours"), UPDATE_INTERVAL_HOURS_DEFAULT
        ),
        mirror=mirror,
    )


# ── 本地版本解析与比较（1.2）──────────────────────────────────────────


@dataclass
class LocalVersion:
    """本地版本解析结果：``version=None`` 表示无可判定版本（form=source 等）。"""

    version: Optional[str]
    form: str  # FORM_ARTIFACT / FORM_SOURCE / "unknown"


def read_framework_version(framework_root=None) -> LocalVersion:
    """框架本地版本：制品根 ``VERSION`` 文件单源，缺失/不可读即 source 形态。

    VERSION 内容为打包时写入的 Release tag（如 ``v0.1.7``，package.sh
    ``printf '%s\\n' "$V" > VERSION``）；读到的空白内容同样按缺失处理
    （半残制品宁可降级 source 也不误报版本）。
    """
    root = Path(framework_root) if framework_root else default_framework_root()
    vpath = root / "VERSION"
    try:
        text = vpath.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return LocalVersion(version=None, form=FORM_SOURCE)
    if not text or "\n" in text:
        # 空文件 / 异常多行内容按缺失处理（正常制品恒为单行 tag）
        return LocalVersion(version=None, form=FORM_SOURCE)
    return LocalVersion(version=text, form=FORM_ARTIFACT)


def default_framework_root() -> Path:
    """框架根缺省解析：core/ 的上一级（制品根 / 源码仓根同构）。"""
    return Path(__file__).resolve().parents[1]


def plugins_version_from_dirname(dirname: str) -> Optional[str]:
    """目录名 ``dsh-plugins-<tag>`` → tag（现状兼容主源，design D1）。

    非匹配形态（用户自起名目录）返回 None——解析不出版本就不做可更新判定，
    不猜测。
    """
    m = PLUGINS_DIRNAME_RE.match(str(dirname))
    if not m:
        return None
    tag = m.group(1).strip()
    return tag or None


def _plugins_version_for_link_target(target: str) -> Optional[str]:
    """link: 目标 → dsh-plugins 版本（目标目录名或其父目录名双探）。

    install.md §6c 的注册形态是逐插件 ``link:<plugins绝对路径>/<插件名>``，
    插件包目录的**父目录**才是 ``dsh-plugins-<tag>`` 版本根；spec Scenario
    亦描述了 link 直接指向 ``dsh-plugins-<tag>`` 目录本身的形态。两形态都
    要解析出版本，故先探目标目录名、再探父目录名。
    """
    path = Path(target)
    tag = plugins_version_from_dirname(path.name)
    if tag:
        return tag
    return plugins_version_from_dirname(path.parent.name)


def detect_plugins_version(plugin_root) -> LocalVersion:
    """dsh-plugins 本地版本双源：制品根 ``VERSION`` 优先，否则目录名解析。

    插件仓未来把 VERSION 打进包（design Open Question 预留）时本函数无需
    变更——VERSION 在场即以其为权威。
    """
    root = Path(plugin_root)
    vpath = root / "VERSION"
    try:
        text = vpath.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        text = ""
    if text and "\n" not in text:
        return LocalVersion(version=text, form=FORM_ARTIFACT)
    tag = plugins_version_from_dirname(root.name)
    if tag:
        return LocalVersion(version=tag, form=FORM_ARTIFACT)
    return LocalVersion(version=None, form="unknown")


def _version_core_segments(version: str) -> list:
    """版本串 → 可比较段元组列表。

    段规则（design D1「手写语义化数值 tuple 比较」）：剥 ``v`` 前缀、截断
    ``+`` 构建元数据后按 ``.`` 与 ``-`` 切段；纯数字段取 ``(0, int)``、其余
    ``(1, str)``——数字段恒排在字符串段前，保证混合形态的确定性全序；
    短串按 ``(0, 0)`` 补齐（``1.2`` == ``1.2.0``）。非数字段安全降级字符串
    比较（任务 1.2 口径）。
    """
    v = version.strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    v = v.split("+", 1)[0]
    raw_segments = re.split(r"[.\-]", v)
    segments = []
    for seg in raw_segments:
        # isascii 前置：isdigit 对部分 Unicode 数字（如 "²"）为 True 但
        # int() 抛 ValueError，非 ASCII 数字段安全降级字符串比较
        if seg.isascii() and seg.isdigit():
            segments.append((0, int(seg)))
        else:
            segments.append((1, seg.lower()))
    if not segments:
        segments = [(1, "")]
    return segments


def compare_versions(a: str, b: str) -> int:
    """语义化版本比较：返回 -1/0/1（a<b / 相等 / a>b）。

    数值逐段比较（``v0.1.10 > v0.1.7``，禁止字典序）；解析失败（空段表）
    的输入按最小段处理，比较结果仍确定。
    """
    sa = _version_core_segments(a) if a else [(1, "")]
    sb = _version_core_segments(b) if b else [(1, "")]
    length = max(len(sa), len(sb))
    pad = (0, 0)
    for i in range(length):
        ea = sa[i] if i < len(sa) else pad
        eb = sb[i] if i < len(sb) else pad
        if ea < eb:
            return -1
        if ea > eb:
            return 1
    return 0


def is_update_available(local: Optional[str], remote: Optional[str]) -> bool:
    """可更新判定：本地与远端均可解析且远端严格大于本地。

    任一端缺失（source 形态 / 远端查询失败）一律 False——不判定不误导。
    """
    if not local or not remote:
        return False
    return compare_versions(remote, local) > 0


# ── 远端查询（1.3）────────────────────────────────────────────────────


@dataclass
class ReleaseInfo:
    """``releases/latest`` 查询结果（tag + 制品资产下载 URL）。"""

    repo: str
    tag_name: str
    assets: dict  # asset 文件名 -> browser_download_url

    @property
    def tarball_url(self) -> Optional[str]:
        """tar.gz 资产 URL（Linux/macOS 制品；无该资产返回 None）。"""
        for name, url in self.assets.items():
            if name.endswith(".tar.gz"):
                return url
        return None

    @property
    def zip_url(self) -> Optional[str]:
        """zip 资产 URL（Windows 制品；无该资产返回 None）。"""
        for name, url in self.assets.items():
            if name.endswith(".zip") and not name.endswith(".tar.zip"):
                return url
        return None

    def asset_url(self, name: str) -> Optional[str]:
        return self.assets.get(name)


class QueryError(Exception):
    """远端查询失败（网络不可达 / 限流 / 响应畸形），reason 可读。"""


def _http_get(url: str, headers: Optional[dict] = None,
              timeout_s: float = QUERY_TIMEOUT_S) -> "tuple[int, bytes]":
    """单次 HTTP GET（测试缝：返回 (status, body)，HTTP 错误码不抛异常）。

    urllib HTTPError 转为 (code, body) 返回——双腿回退判定需要读状态码；
    其余网络异常（URLError/超时/DNS 失败）原样上抛由调用方归因为
    QueryError。UA 必带：GitHub API 对缺 UA 的请求直接 403。
    """
    req = urllib.request.Request(url, headers={"User-Agent": "fenixd-self-update",
                                               **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:  # noqa: BLE001 — body 读取失败不掩盖状态码
            body = b""
        return int(e.code), body


def _gh_token_via_gh_cli(timeout_s: float = 10.0) -> Optional[str]:
    """凭证腿一：``gh auth token``（gh CLI 登录态，只读、不落盘 token）。"""
    try:
        r = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True,
            timeout=timeout_s, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    token = (r.stdout or "").strip()
    if r.returncode == 0 and token:
        return token
    return None


def _gh_token_via_git_credential(timeout_s: float = 10.0) -> Optional[str]:
    """凭证腿二：``git credential fill``（credential helper，只读使用）。

    对 ``https://github.com`` 询问凭证；helper（store/cache/manager 等）
    无凭证时 git 以非零码退出，返回 None。token 仅内存传递，不持久化。
    """
    try:
        r = subprocess.run(
            ["git", "credential", "fill"],
            input="url=https://github.com\n\n",
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    for line in (r.stdout or "").splitlines():
        if line.startswith("password="):
            token = line[len("password="):].strip()
            if token:
                return token
    return None


def _fallback_github_token() -> Optional[str]:
    """双腿凭证解析（design D2）：gh CLI 优先，失败再 git credential helper。"""
    token = _gh_token_via_gh_cli()
    if token:
        return token
    return _gh_token_via_git_credential()


def fetch_latest_release(
    repo: str,
    *,
    timeout_s: float = QUERY_TIMEOUT_S,
    http_get: Optional[Callable] = None,
    token_provider: Optional[Callable[[], Optional[str]]] = None,
) -> ReleaseInfo:
    """查询 ``releases/latest``：匿名先行，401/404 回退凭证腿（design D2）。

    该端点天然排除 draft 与 prerelease = stable 渠道语义（spec：prerelease
    不触发可更新判定）。匿名 401/404（私库特征）且本机有凭证时带
    ``Authorization: Bearer`` 重试一次；双腿全败抛 QueryError 留存原因。
    其余状态码（403 限流 / 404 匿名不可见等）不重试——限流下重试轰炸违反
    design D2。
    """
    getter = http_get or _http_get
    url = f"{GITHUB_API_BASE}/repos/{repo}/releases/latest"
    status, body = getter(url, None, timeout_s)
    if status in (401, 404):
        token = (token_provider or _fallback_github_token)()
        if token:
            status, body = getter(url, {"Authorization": f"Bearer {token}"}, timeout_s)
    if status != 200:
        reason = {
            401: "需要凭证（私库且双腿鉴权未取得可用 token）",
            403: "GitHub API 限流或拒绝（匿名 60/h 上限）",
            404: "仓库不存在或无权访问（匿名与凭证均不可见）",
        }.get(status, f"HTTP {status}")
        raise QueryError(f"查询 {repo} releases/latest 失败: {reason}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise QueryError(f"查询 {repo} 响应非合法 JSON: {e}") from e
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise QueryError(f"查询 {repo} 响应缺 tag_name（非 releases/latest 形态）")
    assets = {}
    for asset in payload.get("assets") or []:
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if isinstance(name, str) and isinstance(url, str):
            assets[name] = url
    return ReleaseInfo(repo=repo, tag_name=tag.strip(), assets=assets)


def apply_mirror_url(url: Optional[str], mirror: str) -> Optional[str]:
    """mirror 前缀替换：仅替换制品下载 URL 前缀（API 域名不替换，design D8）。

    ``https://github.com/owner/repo/releases/download/...`` →
    ``<mirror>/owner/repo/releases/download/...``；非 GitHub 下载前缀的 URL
    原样返回（sha256 资产与制品同源，一并走镜像；API 查询永不走镜像）。
    mirror 为空返回原 URL。
    """
    if not url:
        return url
    mirror = (mirror or "").strip().rstrip("/")
    if not mirror:
        return url
    if url.startswith(GITHUB_DOWNLOAD_PREFIX + "/"):
        return mirror + url[len(GITHUB_DOWNLOAD_PREFIX):]
    return url


def download_channel_urls(url: Optional[str], mirror: str) -> list:
    """资产下载候选通道列表（去重保序，self_update_apply 逐通道消费）。

    mirror 非空 → ``[镜像 URL, 官方直连 URL]``：镜像在前（默认通道），
    镜像停服/损坏时直连兜底——直连 reset 与镜像停服是双向故障面
    （2026-11-28 实证），单通道缺省都会整体失败。mirror 为空（显式官方
    直连）→ 仅官方通道，不静默绕道镜像（用户显式选择必须尊重）。
    非制品 URL（apply_mirror_url 不替换）或 url 为空 → 单元素列表。
    """
    if not url:
        return []
    mirror = (mirror or "").strip().rstrip("/")
    if not mirror:
        return [url]
    mirrored = apply_mirror_url(url, mirror)
    if mirrored == url:
        return [url]
    return [mirrored, url]


# ── 下载源自选（2026-11-28 dashboard 设置页；实测口径见 docs/help/13-self-update.md）──

# 下载源预设：label 由前端 i18n 按 id 映射（引擎不背文案）；url 为
# update.mirror 的实际配置值——gh-proxy 形态镜像须带 ``/https://github.com``
# 尾巴（mirror 前缀替换的产物才是「镜像域名 + 完整原路径」的可用形态）。
UPDATE_MIRROR_PRESETS = [
    {"id": "official", "url": ""},
    {"id": "ghfast", "url": "https://ghfast.top/https://github.com"},
    {"id": "ghproxy", "url": "https://ghproxy.net/https://github.com"},
]

# mirror 是下载 URL 的前缀拼接值（apply_mirror_url 直接 string 拼接），宽松
# 注入面一律收死：仅 https 主机（可带端口）+ 可选路径尾巴；拒绝用户信息、
# 查询、片段与百分号编码字符。
_MIRROR_VALUE_RE = re.compile(
    r"^https://[A-Za-z0-9.-]+(?::\d{2,5})?(/[A-Za-z0-9._~:/-]*)?$"
)


def normalize_mirror(value: object) -> Optional[str]:
    """校验/归一 ``update.mirror`` 配置值；非法返回 ``None``。

    ``""`` = 官方直连（合法）；非空值仅接受 https 主机前缀（可带 gh-proxy
    形态路径尾巴，如 ``https://ghfast.top/https://github.com``）。
    """
    if not isinstance(value, str):
        return None
    v = value.strip().rstrip("/")
    if not v:
        return ""
    if not _MIRROR_VALUE_RE.fullmatch(v):
        return None
    return v


# 镜像探测超时（秒）：Range GET 1 字节的轻量请求，不应拖慢检查面；
# 亦远小于 apply 面的 600s 墙钟——探测只回答「现在通不通」。
_MIRROR_PROBE_TIMEOUT_S = 10.0


def _probe_mirror_url(url: Optional[str], *,
                      http_get: Optional[Callable] = None,
                      timeout_s: float = _MIRROR_PROBE_TIMEOUT_S) -> Optional[str]:
    """镜像形态轻量探测（Range GET 1 字节）；返回 ``None``＝可用。

    客户端实证（2026-11-28 分析报告根因二配套）：镜像通道是否健康在
    check 阶段不可见——应用失败时才暴露（reset/超时/停服）。检查侧用
    1 字节 Range GET 探测 zip_url 的镜像形态产物：2xx/3xx 任一状态码
    ＝通道可用（含 302 跳 CDN，不跟随）；404/4xx/5xx/网络异常＝返回
    不可用原因字符串，由 run_check 写入 ``status.mirror_warning``（UI
    与排障均可见），不改变 update_available 判定、不阻断检查。

    ``http_get`` 为既有测试缝（``(url, headers, timeout_s) -> (status, body)``
    形态）；缺省 ``_http_get``。getter 网络异常在此归因为原因串而非上抛
    ——探测失败本质是「告警信息」而非「检查失败」。
    """
    if not url:
        return None
    getter = http_get or _http_get
    try:
        status, _ = getter(url, {"Range": "bytes=0-0"}, timeout_s)
    except Exception as e:  # noqa: BLE001 — 网络异常→告警原因串
        return f"镜像探测失败（网络异常）: {e}"
    if 200 <= status < 400:
        return None
    return f"镜像探测异常（HTTP {status}）——镜像源可能停服或路径不可用"


# ── 锁（1.4，O_EXCL 占位 + 陈锁清扫）──────────────────────────────────


class UpdateLock:
    """O_EXCL 占位 lock 文件（同目录、与 spec 信号通道同族，design D3）。

    ``acquire()`` 原子「检查+占位」：占位失败（他方持锁）返回 False；发现
    陈锁（mtime 超龄 = 持锁进程已死）清扫后重试一次。锁文件内容记 pid 与
    时刻（排障可读）。``release()`` 按 inode 复核 unlink（防陈锁清扫竞态下
    误删他人新锁）。
    """

    def __init__(self, path, stale_s: float):
        self.path = Path(path)
        self.stale_s = float(stale_s)
        self._fd: Optional[int] = None
        self._ino: Optional[int] = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"pid": os.getpid(), "created": to_storage(now_utc())},
            ensure_ascii=False,
        ).encode("utf-8")
        for attempt in (0, 1):
            try:
                fd = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError:
                if self._sweep_stale() and attempt == 0:
                    continue
                return False
            except OSError:
                # 无 O_EXCL 语义的异常文件系统等：按未取到锁降级（检查可放弃，
                # 应用侧调用方以 409 语义响应），不抛异常阻断主链路
                return False
            try:
                os.write(fd, payload)
                self._ino = os.fstat(fd).st_ino
            except OSError:
                # 写占位失败（如磁盘满）：文件已在盘但本进程未持锁，unlink
                # 自清理后按未取到锁降级，避免悬挂占位令后续触发被判 conflict
                self._ino = None
                try:
                    os.unlink(self.path)
                except OSError:
                    pass
                return False
            finally:
                os.close(fd)
            self._fd = fd  # 仅作已占用标记（写后即关，占位语义由文件存在承载）
            return True
        return False

    def _sweep_stale(self) -> bool:
        """陈锁清扫：mtime 超龄 unlink（持锁进程死亡的死锁自愈）。

        unlink 前 inode 复核（对齐 ``release()`` 口径）：并发清扫竞态下他方
        可能已删旧锁并占位新锁，路径 inode 与先前 stat 不一致即放弃清扫，
        防误删他方新锁导致双持锁。
        """
        try:
            st = self.path.stat()
        except OSError:
            return True  # 已消失，可重试
        age = now_utc().timestamp() - st.st_mtime
        if age <= self.stale_s:
            return False
        try:
            cur = self.path.stat()
        except OSError:
            return True  # 已消失（他方已清扫/释放），可重试
        if cur.st_ino != st.st_ino:
            return False  # 已换为他方新占位锁，放弃清扫
        try:
            self.path.unlink()
            logger.info("self_update: 清扫陈锁 %s（age=%.0fs）", self.path, age)
            return True
        except OSError:
            return False

    def release(self) -> None:
        if self._fd is None:
            return
        self._fd = None
        try:
            st = self.path.stat()
        except OSError:
            return
        # inode 复核：仅删除自家占位（陈锁清扫与并发占位的交错窗口防线）
        if self._ino is not None and st.st_ino != self._ino:
            return
        try:
            self.path.unlink()
        except OSError:
            pass

    @staticmethod
    def is_locked(path) -> bool:
        """锁是否在位（他方持锁判定；dashboard 409 预检用，不清理）。"""
        try:
            Path(path).stat()
            return True
        except OSError:
            return False


# ── 状态与审计（1.4）──────────────────────────────────────────────────


def read_status(status_path=None) -> Optional[dict]:
    """读框架级更新状态文件；缺失/损坏返回 None（never-checked 形态）。"""
    path = Path(status_path) if status_path else STATUS_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        st = json.loads(raw)
    except ValueError:
        return None
    return st if isinstance(st, dict) else None


def _merge_status(base: Optional[dict], updates: dict) -> dict:
    """浅层段级合并：顶层键整段覆盖（framework/plugins/apply 内部由写方整段构造）。"""
    st = dict(base) if isinstance(base, dict) else {}
    st["schema"] = STATUS_SCHEMA
    st.update(updates)
    return st


def write_status(status: dict, status_path=None) -> None:
    """原子写状态文件（fs_utils 收口：mkstemp + os.replace + fsync）。"""
    path = Path(status_path) if status_path else STATUS_PATH
    atomic_write_text(path, json.dumps(status, ensure_ascii=False, indent=1))


def _status_write_lock(status_path=None):
    """status.json 读合并写专用互斥（UpdateLock 占位锁，等待上限内轮询重试）。

    与编排锁无交叉（本锁只在 update_status 内部短暂持有），等待超限返回
    None（调用方降级无锁直写，不丢写、与既有无守卫行为等价）。
    """
    path = Path(status_path) if status_path else STATUS_PATH
    lock_path = path.parent / "status.lock"
    lock = UpdateLock(lock_path, STATUS_LOCK_STALE_S)
    deadline = time.monotonic() + STATUS_LOCK_WAIT_S
    while True:
        if lock.acquire():
            return lock
        if time.monotonic() >= deadline:
            return None
        time.sleep(STATUS_LOCK_POLL_S)


def update_status(updates: dict, status_path=None) -> dict:
    """读-合并-原子写状态（读侧 None 按空 dict 兜底）。返回合并后的完整状态。

    读合并写经 status.lock 单一互斥面收敛（code-review item 1ec38cb01b7a：
    check/apply 编排锁互不互斥，交叉并发下陈旧读底覆写会互相丢状态）；
    等待超限降级无锁直写。status_path 指定时锁文件落同目录（测试隔离）。
    """
    lock = _status_write_lock(status_path)
    try:
        st = _merge_status(read_status(status_path), updates)
        write_status(st, status_path)
    finally:
        if lock is not None:
            lock.release()
    return st


def mark_apply_phase(phase: str, updates: Optional[dict] = None,
                     status_path=None) -> dict:
    """更新 apply 段阶段字段（编排全程进度/结果落盘，design D4）。"""
    apply_seg = {"phase": phase}
    if updates:
        apply_seg.update(updates)
    return update_status({"apply": apply_seg}, status_path)


def append_audit(entry: dict, audits_path=None) -> None:
    """追加一行审计到 ``audits.jsonl``（尽力而为，失败不阻断主流程）。

    审计在 check/apply 锁内写入（调用方约束）；单行 json 追加在 POSIX
    O_APPEND 语义下原子。文件按既有产物保留策略由外部清理（design D9）。
    """
    path = Path(audits_path) if audits_path else AUDITS_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        logger.debug("self_update: 审计写入失败（不阻断主流程）: %s", e)


# ── 检查编排（1.4/1.5）────────────────────────────────────────────────


def _backoff_hours(failure_count: int, interval_hours: float) -> float:
    """检查失败退避（小时）：2^(n-1) 起，封顶 interval。"""
    backoff = CHECK_FAILURE_BACKOFF_BASE_HOURS * (2 ** max(0, failure_count - 1))
    return min(backoff, max(interval_hours, CHECK_FAILURE_BACKOFF_BASE_HOURS))


def _check_framework(framework_root, cfg: UpdateConfig,
                     http_get: Optional[Callable]) -> dict:
    """框架单目标检查：本地版本 + 远端 latest（source 形态免远端查询）。"""
    local = read_framework_version(framework_root)
    seg = {"form": local.form, "local_version": local.version,
           "remote_version": None, "remote_tag": None,
           "tarball_url": None, "zip_url": None, "update_available": False}
    if local.form == FORM_SOURCE:
        seg["reason"] = "源码形态（无 VERSION 文件），不参与自动更新"
        return seg
    info = fetch_latest_release(FRAMEWORK_REPO, http_get=http_get)
    seg["remote_version"] = info.tag_name
    seg["remote_tag"] = info.tag_name
    seg["tarball_url"] = apply_mirror_url(info.tarball_url, cfg.mirror)
    seg["zip_url"] = apply_mirror_url(info.zip_url, cfg.mirror)
    seg["update_available"] = is_update_available(local.version, info.tag_name)
    return seg


def detect_plugins_state(profiles_dir=None) -> dict:
    """扫描 dsh profiles 的 link: 依赖，解析 dsh-plugins 本地安装态。

    ``profiles_dir`` 参数 = profiles **目录本身**（``~/.dsh/profiles``；
    缺省经 ``resolve_dsh_home()/profiles`` 单源解析）。

    Returns: ``{"profiles": {<profile>: {"plugin_root": Path|None,
    "version": str|None, "form": str}}, "version": 全部 profile 中最新版本,
    "form": "artifact"/"unknown"}``。目录不存在 → profiles 空表
    （dsh harness 未使用，插件更新面整体 absent）。
    """
    from core.dsh_session_tidy import resolve_dsh_home  # 既有单源（~/.dsh 缺省解析）

    profiles_root = (Path(profiles_dir) if profiles_dir
                     else resolve_dsh_home() / "profiles")
    result = {"profiles": {}, "version": None, "form": "unknown"}
    try:
        entries = sorted(p for p in profiles_root.iterdir() if p.is_dir())
    except OSError:
        return result
    found = []
    for pdir in entries:
        pkg = pdir / "package.json"
        info = {"plugin_root": None, "version": None, "form": "unknown"}
        try:
            payload = json.loads(pkg.read_text(encoding="utf-8"))
            deps = payload.get("dependencies") if isinstance(payload, dict) else None
        except (OSError, ValueError, UnicodeDecodeError):
            deps = None
        if isinstance(deps, dict):
            for _name, ref in deps.items():
                if not (isinstance(ref, str) and ref.startswith("link:")):
                    continue
                target = ref[len("link:"):]
                if not target:
                    continue
                tag = _plugins_version_for_link_target(target)
                if tag:
                    info = {"plugin_root": str(Path(target).resolve())
                            if Path(target).exists() else str(target),
                            "version": tag, "form": FORM_ARTIFACT}
                    found.append(tag)
                    break
        result["profiles"][pdir.name] = info
    if found:
        result["version"] = max(found, key=_version_core_segments)
        result["form"] = FORM_ARTIFACT
    return result


def _check_plugins(profiles_dir, cfg: UpdateConfig,
                   http_get: Optional[Callable]) -> dict:
    """插件单目标检查：profiles 双源本地版本 + 远端 latest。"""
    state = detect_plugins_state(profiles_dir)
    seg = {"form": state.get("form"), "local_version": state.get("version"),
           "remote_version": None, "remote_tag": None,
           "zip_url": None, "update_available": False,
           "profiles": state.get("profiles") or {}}
    if not state.get("version"):
        seg["reason"] = (
            "未在任何 dsh profile 中发现 link: 指向 dsh-plugins-* 的插件"
            if seg["form"] != "unknown" else "未发现 dsh profiles（dsh harness 未使用）"
        )
        return seg
    info = fetch_latest_release(PLUGINS_REPO, http_get=http_get)
    seg["remote_version"] = info.tag_name
    seg["remote_tag"] = info.tag_name
    seg["zip_url"] = apply_mirror_url(info.zip_url, cfg.mirror)
    seg["update_available"] = is_update_available(state.get("version"),
                                                  info.tag_name)
    return seg


def run_check(
    source: str = "manual",
    *,
    framework_root=None,
    profiles_dir=None,
    update_dir=None,
    config: Optional[UpdateConfig] = None,
    http_get: Optional[Callable] = None,
    now=None,
) -> dict:
    """执行一次完整检查（框架 + 插件），落盘状态与审计；并发互斥。

    检查锁被占（他方检查进行中）→ 不重复发起，返回 ``{"skipped":
    "locked"}`` 并附现有状态（多 daemon 幂等共享，spec 周期检查 Scenario）。
    框架与插件两目标独立捕获失败：单边失败不阻断另一边；全部所需查询失败
    才计入失败退避。

    Returns: 落盘后的完整状态 dict（或 skipped 短路结果）。
    """
    udir = Path(update_dir) if update_dir else UPDATE_DIR
    status_path = udir / "status.json"
    audits_path = udir / "audits.jsonl"
    lock = UpdateLock(udir / "check.lock", CHECK_LOCK_STALE_S)
    cfg = config or load_update_config()
    started = now or now_utc()

    if not lock.acquire():
        existing = read_status(status_path) or {}
        result = {"skipped": "locked", "status": existing}
        append_audit({
            "kind": "check", "source": source,
            "ts": to_storage(started),
            "result": "skipped-locked", "reason": "检查锁被占（他方检查进行中）",
        }, audits_path)
        return result

    try:
        fw_error = None
        plugins_error = None
        fw_seg = {}
        plugins_seg = {}
        try:
            fw_seg = _check_framework(framework_root, cfg, http_get)
        except Exception as e:  # noqa: BLE001 — 单边失败独立留存
            fw_error = str(e)
            logger.debug("self_update: 框架检查失败: %s", e)
        try:
            plugins_seg = _check_plugins(profiles_dir, cfg, http_get)
        except Exception as e:  # noqa: BLE001
            plugins_error = str(e)
            logger.debug("self_update: 插件检查失败: %s", e)

        # 镜像健康探测（2026-11-28 客户端分析报告建议）：镜像通道健康在
        # check 面不可见、应用失败才暴露——框架检查成功且走镜像形态时，
        # 对 zip_url 做 1 字节 Range 探测，失败写入 mirror_warning 告警
        # （不改变 update_available、不阻断检查）。恒写键：mirror 为空或
        # 探测通过时写 None，清除上次遗留告警。
        mirror_warning = None
        if cfg.mirror and fw_error is None:
            probe_url = fw_seg.get("zip_url") or fw_seg.get("tarball_url")
            if probe_url:
                mirror_warning = _probe_mirror_url(probe_url, http_get=http_get)
                if mirror_warning:
                    logger.warning("self_update: %s", mirror_warning)

        errors = [e for e in (fw_error, plugins_error) if e]
        failure_count = 0
        if errors:
            prev = read_status(status_path) or {}
            try:
                # 状态文件 failure_count 脏值（非数值）回退 0，不穿透手动入口
                failure_count = int(prev.get("failure_count") or 0) + 1
            except (TypeError, ValueError):
                failure_count = 1
        finished = now_utc()
        reason = "；".join(errors) if errors else None
        updates = {
            "last_check_at": to_storage(finished),
            "last_error": reason,
            "failure_count": failure_count,
            "next_check_after": None,
            "mirror_warning": mirror_warning,
        }
        # 失败侧不写该段（_merge_status 浅合并整段覆盖）：保留上次成功检查
        # 留下的持久版本信息；失败原因已由 last_error 承载，不依赖空段表达
        if fw_error is None:
            updates["framework"] = fw_seg
        if plugins_error is None:
            updates["plugins"] = plugins_seg
        # 失败退避：next_check_after = finished + backoff；成功则保持清空
        if errors:
            backoff = _backoff_hours(failure_count, cfg.interval_hours)
            updates["next_check_after"] = to_storage(finished + timedelta(hours=backoff))
        else:
            updates["last_success_at"] = to_storage(finished)
        status = update_status(updates, status_path)
        append_audit({
            "kind": "check", "source": source, "ts": to_storage(finished),
            "result": "failure" if errors else "success",
            "reason": reason,
            "framework_local": fw_seg.get("local_version"),
            "framework_remote": fw_seg.get("remote_version"),
            "plugins_local": plugins_seg.get("local_version"),
            "plugins_remote": plugins_seg.get("remote_version"),
            "elapsed_ms": int((finished - started).total_seconds() * 1000),
        }, audits_path)
        return status
    finally:
        lock.release()


def run_scheduled_check(
    source: str = "daemon",
    *,
    framework_root=None,
    profiles_dir=None,
    update_dir=None,
    config: Optional[UpdateConfig] = None,
    http_get: Optional[Callable] = None,
    now=None,
    config_loader: Optional[Callable[[], UpdateConfig]] = None,
) -> dict:
    """周期检查入口（daemon 周期任务挂接点，任务 1.5/1.7）。

    - ``update.enabled=false`` → 直接返回（手动检查入口不受影响，design D8）；
    - 按 status.json 的上次检查时刻与 ``interval_hours`` 判到期；失败退避
      （``next_check_after`` 未到不重试）；
    - 到期才真正发起检查（复用 ``run_check``，含并发互斥）；未到期返回
      ``{"skipped": "not-due"}``；
    - 绝不抛异常、绝不打告警：一切失败静默落 status/audit 后返回
      （daemon 主循环调用方仍自带 try/except 双保险，不中断调度链）。
    """
    try:
        cfg = (config_loader or load_update_config)()
        if config is not None:
            cfg = config
        if not cfg.enabled:
            return {"skipped": "disabled"}
        udir = Path(update_dir) if update_dir else UPDATE_DIR
        status_path = udir / "status.json"
        moment = now or now_utc()
        st = read_status(status_path)
        if st is not None:
            # 失败退避窗：next_check_after 未到不重试（防止外部触发源密集轮询
            # 时的重试轰炸）
            next_after = parse_ts(st.get("next_check_after") or "") if st.get(
                "next_check_after") else None
            if next_after is not None and moment < next_after:
                return {"skipped": "backoff"}
            base = parse_ts(st.get("last_check_at") or "") if st.get(
                "last_check_at") else None
            if base is not None:
                if moment - base < timedelta(hours=cfg.interval_hours):
                    return {"skipped": "not-due"}
        # 从未检查过（无状态文件）→ 首检即到期（启动延迟由 daemon 挂接点控制）
        return run_check(
            source, framework_root=framework_root, profiles_dir=profiles_dir,
            update_dir=update_dir, config=cfg, http_get=http_get, now=moment,
        )
    except Exception as e:  # noqa: BLE001 — 周期入口顶层自吞（绝不抛告警）
        logger.debug("self_update: 周期检查静默失败: %s", e)
        return {"error": str(e)}
