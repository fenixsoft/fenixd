"""scenario_static_check.py — 场景集静态缺陷扫描器（scenario-static-defect-scan）。

模式表驱动的静态扫描：场景执行前对场景集做机械可查的缺陷模式匹配，
findings 结构化落盘 ``scenario_static_findings.json`` 并注入 judge prompt
定向情报段。**只做情报不拦截执行**——执行证据（report/截图）是 judge 修复
的依据。

fail-open 边界（design D3/D4）：
- 任何异常记 WARNING 并返回空 findings（不抛出、不阻断验证主流程）；
- serving 端口未知（None/空串）时端口比对类模式整体跳过，纯文本模式仍执行。

模式表（design D4）：模块级数据结构（rule_id / 适用 kind / 匹配函数），
新增模式 = 增加表项，不动扫描器主体。初始钉死三条：
  1. ``stale_literal_port``   — cli/api 场景 command/stdin 字面端口 ≠ serving 端口
  2. ``stale_navigate_port``  — web navigate URL 字面端口 ≠ serving 端口
  3. ``double_han_text_selector`` — 双汉字文本选择器（antd autoInsertSpace
     渲染为「X X」，二字断言文本必失配的历史坑）
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

logger = logging.getLogger("verify_engine.scenario_static_check")

# ── 端口相关确定性模式（D4：纯正则）─────────────────────────────
# URL 形 ``http://127.0.0.1:57905/...`` 与裸 host:port 形（seed stdin 代码
# 内部经变量拼接的 URL 往往不带 scheme）；``--port/-p`` 命令行标志位；
# 端口变量绑定字面量（本次事故根因形态：``os.environ.get(
# 'FENIX_VERIFY_PORT', '57905')`` 兜底），以 PORT 标记 + 邻近数字字面量捕捉。
_URL_PORT_RE = re.compile(r"(?:https?://[^/\s\"]*:)(\d{2,5})")
_HOST_PORT_RE = re.compile(
    r"(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|localhost|[a-zA-Z][a-zA-Z0-9\-]*):(\d{2,5})")
_FLAG_PORT_RE = re.compile(r"(?:--port|-p|--port=|-p=)(?:\s|=)?(\d{2,5})")
_PORT_VAR_RE = re.compile(
    r"PORT[^\w]*(?:[\"']?\s*,\s*[\"']?|[\"']?)[^\w]{0,6}(\d{2,5})")
_PORT_PATTERNS = (_URL_PORT_RE, _HOST_PORT_RE, _FLAG_PORT_RE, _PORT_VAR_RE)

# ── 双汉字文本选择器模式（antd autoInsertSpace：二字按钮渲染为「X X」）──
# 覆盖 ``:has-text("确定")`` / ``text=确定`` / 引号裸文本选择器；统一从
# 引号字面量与 ``text=`` 取值中提取候选文本再判汉字数。
_TEXT_LITERAL_RES = (
    re.compile(r':has-text\(\s*["\']([^"\']+)["\']\s*\)'),
    re.compile(r"(?:^|[\s\.]):?text[:=]\(?[\"']?([^\"'\s,)】]+)"),
    re.compile(r'["\']([^"\']{1,32})["\']'),
)

_HAN_CHAR_RE = re.compile(r"[一-鿿]")


@dataclass
class StaticFinding:
    """单条静态缺陷扫描结果。"""

    scenario_id: str
    rule_id: str
    location: str    # 如 "steps[0].command" / "assertions[1].selector"
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def _matching_ports(text: str) -> list[str]:
    """提取文本中的字面端口号（去重、保持出现序）。

    只收确定性规则（design D4 Risk：初始模式只收确定性规则、防误报磨掉
    judge 信任）：端口值须落在高端口区间 1024–65535——serving 实例端口来自
    find_free_port（临时端口，恒 >1024），事故端口（57905/39781）亦在此区间；
    时间戳形态 ``T08:00:00``/``00`` 等低值（<1024）天然排除，不误报。
    """
    out: list[str] = []
    seen: set[str] = set()
    for pat in _PORT_PATTERNS:
        for m in pat.finditer(text):
            port = m.group(1)
            if not port.isdigit():
                continue
            pv = int(port)
            if pv < 1024 or pv > 65535:
                continue  # 特权端口/时间戳形态（:00/:08/:30）非 serving 端口
            if port not in seen:
                seen.add(port)
                out.append(port)
    return out


def _extract_han_literals(text: str) -> list[str]:
    """提取文本中候选文本字面量（:has-text("X") / text=X / 引号裸文本）。

    原始字段值本身也作为候选（断言 ``expected`` 直接承载裸文本、无引号包裹时
    须以字段值整体判双汉字风险）；去重、保持出现序。
    """
    lits: list[str] = []
    seen: set[str] = set()
    for pat in _TEXT_LITERAL_RES:
        for m in pat.finditer(text):
            lit = m.group(1)
            if lit not in seen:
                seen.add(lit)
                lits.append(lit)
    # 断言 expected/label 等可能为裸文本（无引号/选择器语法），
    # 以字段值本身作为候选字面量（:has-text("X") 中 X 有引号包裹、
    # 裸文本没有——前者已由上方正则捕获，后者此处补入）
    if text not in seen and len(text.strip()) <= 32:
        seen.add(text)
        lits.append(text)
    return lits


def _is_exact_2_han(text: str) -> bool:
    """判断文本是否恰好由 2 个汉字组成（无空格/ASCII/标点）。

    antd autoInsertSpace 仅对恰含 2 个汉字且无其他字符的按钮文本触发渲染
    空格（「确定」→「确 定」）；含非汉字（如"归档 SPEC"）或已含空格
    （如"保 存"——已应用 workaround）的文本不受影响。
    """
    stripped = text.strip()
    if not stripped or len(stripped) != 2:
        return False
    return len(_HAN_CHAR_RE.findall(stripped)) == 2


def _flagged_2han_literals(text: str) -> list[str]:
    """从选择器文本中提取全部触发双汉字风险的文本字面量（去重、保序）。"""
    out: list[str] = []
    seen: set[str] = set()
    for lit in _extract_han_literals(text):
        if _is_exact_2_han(lit) and lit not in seen:
            seen.add(lit)
            out.append(lit)
    return out


def _rule_stale_literal_port(scenario: dict,
                             serving_port: str | None) -> list[StaticFinding]:
    """① cli/api 场景 command/stdin/http_request url 字面端口 ≠ serving 端口。

    本次事故根因：跨轮 replan 原样写回已裁决场景，seed stdign 内嵌上一轮
    serving 字面端口 → 新一轮端口不同 → 夹具未建成 → 下游连锁失败。cli 场景扫
    ``command``/``stdin`` 步骤字段，api 场景扫 ``http_request``/``sse_connect``
    步骤 url 字段。serving 端口未知时不触发（上层已按表项 need_port 跳过）。
    """
    sid = str(scenario.get("id") or "?")
    findings: list[StaticFinding] = []
    kind = scenario.get("kind")
    steps: list = scenario.get("steps") or []
    if kind == "cli":
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            for field in ("command", "stdin"):
                text = step.get(field)
                if not isinstance(text, str) or not text:
                    continue
                for port in _matching_ports(text):
                    if serving_port and port == str(serving_port):
                        continue
                    findings.append(StaticFinding(
                        scenario_id=sid,
                        rule_id="stale_literal_port",
                        location=f"steps[{i}].{field}",
                        message=(
                            f"场景 {field} 内嵌字面端口 {port} ≠ 本轮 serving 端口 "
                            f"{serving_port or '未知'}（跨轮端口残留）。cli 步骤应以 "
                            f"FENIX_VERIFY_PORT/FENIX_VERIFY_BASE_URL 环境变量取本轮"
                            f"端口，勿硬编码字面端口——否则夹具/seed 实际未往本轮实例建。"
                        ),
                    ))
    elif kind == "api":
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            if step.get("action") not in ("http_request", "sse_connect"):
                continue
            url = step.get("url")
            if not isinstance(url, str) or not url:
                continue
            for port in _matching_ports(url):
                if serving_port and port == str(serving_port):
                    continue
                findings.append(StaticFinding(
                    scenario_id=sid,
                    rule_id="stale_literal_port",
                    location=f"steps[{i}].url",
                    message=(
                        f"api 步骤 url 字面端口 {port} ≠ 本轮 serving 端口 "
                        f"{serving_port or '未知'}（跨轮端口残留）。api 场景应打"
                        f"本轮实例地址（FENIX_VERIFY_PORT），勿硬编码字面端口。"
                    ),
                ))
    return findings


def _rule_stale_navigate_port(scenario: dict,
                              serving_port: str | None) -> list[StaticFinding]:
    """② web navigate URL 字面端口 ≠ serving 端口（误导性情报级）。

    web_runner 执行时以契约 base_url 为准，navigate 字面端口仅作回退考古——
    属误导性情报而非硬缺陷，但会干扰调试取证与外部读者判断真实地址。
    """
    sid = str(scenario.get("id") or "?")
    findings: list[StaticFinding] = []
    steps: list = scenario.get("steps") or []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        if step.get("action") != "navigate":
            continue
        url = step.get("value") or step.get("url") or step.get("target") or ""
        if not isinstance(url, str) or not url:
            continue
        for port in _matching_ports(url):
            if serving_port and port == str(serving_port):
                continue
            findings.append(StaticFinding(
                scenario_id=sid,
                rule_id="stale_navigate_port",
                location=f"steps[{i}].value",
                message=(
                    f"navigate URL 字面端口 {port} ≠ 本轮 serving 端口 "
                    f"{serving_port or '未知'}。web 执行以契约 base_url 为准、"
                    f"字面端口仅回退考古——误导性情报，建议按本轮端口改写以利取证。"
                ),
            ))
    return findings


def _rule_double_han_text_selector(scenario: dict,
                                   serving_port: str | None) -> list[StaticFinding]:
    """③ 双汉字文本选择器（antd autoInsertSpace：二字按钮渲染为「X X」）。

    扫描 web 场景断言 selector/text/expected 与步骤 target/value 中候选
    文本字面量，恰含 2 个汉字时报告——antd Button 对恰 2 汉字文本自动插入
    空格（「确定」→「确 定」），按原文字匹配/断言必失配（历史 touch-expand
    /antd 系列事故积累）。1/3 汉字不报（autoInsertSpace 仅二字触发）。
    """
    sid = str(scenario.get("id") or "?")
    findings: list[StaticFinding] = []
    if scenario.get("kind") != "web":
        return findings
    assertions: list = scenario.get("assertions") or []
    for i, asc in enumerate(assertions):
        if not isinstance(asc, dict):
            continue
        for field in ("selector", "text", "expected"):
            text = asc.get(field)
            if not isinstance(text, str) or not text:
                continue
            for lit in _flagged_2han_literals(text):
                findings.append(StaticFinding(
                    scenario_id=sid,
                    rule_id="double_han_text_selector",
                    location=f"assertions[{i}].{field}",
                    message=(
                        f"断言 {field} 含恰 2 汉字文本选择器 "
                        f"`{lit}`——antd autoInsertSpace 会把二字文本渲染为「X X」"
                        f"（如「确定」→「确 定」），按原文匹配必失配。建议改用 "
                        f"data-testid 或含非汉字/更长文本的选择器。"
                    ),
                ))
    for i, step in enumerate(scenario.get("steps") or []):
        if not isinstance(step, dict):
            continue
        for field in ("target", "value"):
            text = step.get(field)
            if not isinstance(text, str) or not text:
                continue
            for lit in _flagged_2han_literals(text):
                findings.append(StaticFinding(
                    scenario_id=sid,
                    rule_id="double_han_text_selector",
                    location=f"steps[{i}].{field}",
                    message=(
                        f"步骤 {field} 含恰 2 汉字文本选择器 "
                        f"`{lit}`——antd autoInsertSpace 会把二字文本渲染为「X X」"
                        f"（如「确定」→「确 定」），点击/断言必失配。建议改用 "
                        f"data-testid 或含非汉字/更长文本的选择器。"
                    ),
                ))
    return findings


# ── 模式表（模块级数据结构，design D4：新增模式 = 增加表项）──────────
# need_port=True 的表项在 serving 端口未知时整体跳过。
PATTERN_TABLE: list[dict] = [
    {
        "rule_id": "stale_literal_port",
        "kinds": {"cli", "api"},
        "need_port": True,
        "match": _rule_stale_literal_port,
    },
    {
        "rule_id": "stale_navigate_port",
        "kinds": {"web"},
        "need_port": True,
        "match": _rule_stale_navigate_port,
    },
    {
        "rule_id": "double_han_text_selector",
        "kinds": {"web"},
        "need_port": False,
        "match": _rule_double_han_text_selector,
    },
]


def scan_scenarios(scenarios: Sequence[Any],
                   serving_port: str | int | None = None) -> list[StaticFinding]:
    """模式表驱动扫描场景集（fail-open：任何异常记 WARNING 返回空 findings）。

    Args:
        scenarios: test_scenarios.json 解析出的场景列表。
        serving_port: 本轮 serving 端口（None/空串/0 → 端口类模式整体跳过，
            纯文本模式仍执行）。

    Returns:
        findings 列表；任意规则/场景异常被隔离捕获（WARNING 留痕），
        顶层再兜底捕获一次保证绝不抛出。
    """
    serving = str(serving_port) if serving_port else None
    port_known = bool(serving)
    findings: list[StaticFinding] = []
    try:
        for rule in PATTERN_TABLE:
            if rule["need_port"] and not port_known:
                continue
            for sc in scenarios:
                if not isinstance(sc, dict):
                    continue
                kind = sc.get("kind") or "web"
                if kind not in rule["kinds"]:
                    continue
                try:
                    findings.extend(rule["match"](sc, serving))
                except Exception as e:  # noqa: BLE001 — fail-open 设计
                    logger.warning(
                        "scenario_static_check",
                        f"规则 {rule['rule_id']} 扫描场景 {sc.get('id', '?')} 异常"
                        f"（fail-open，跳过该场景）: {type(e).__name__}: {e}",
                    )
    except Exception as e:  # noqa: BLE001 — fail-open 设计
        logger.warning(
            "scenario_static_check",
            f"静态扫描整体异常（fail-open，返回空 findings）: "
            f"{type(e).__name__}: {e}",
        )
        return []
    return findings


def write_findings(project_root: Path, spec_name: str,
                   findings: Sequence[StaticFinding]) -> None:
    """findings 覆盖写 ``.fenix/verify-progress/<spec>/scenario_static_findings.json``。

    写失败仅 WARNING，不阻断验证（fail-open）。
    """
    target = (
        Path(project_root) / ".fenix" / "verify-progress"
        / spec_name / "scenario_static_findings.json"
    )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = [f.to_dict() for f in findings]
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001 — fail-open 设计
        logger.warning(
            "scenario_static_check",
            f"静态扫描 findings 落盘失败 '{spec_name}'（写失败仅 WARNING，不阻断）: "
            f"{type(e).__name__}: {e}",
        )


def load_findings(project_root: Path, spec_name: str) -> list[dict]:
    """读取 findings 文件（prompt 情报段注入用）。

    文件缺失/损坏/非 list → 返回空列表（零注入，fail-open）。
    """
    path = (
        Path(project_root) / ".fenix" / "verify-progress"
        / spec_name / "scenario_static_findings.json"
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    except Exception:  # noqa: BLE001 — fail-open 设计
        return []


# ── 契约只读一致性检查（planner-contract-findings，design D4）──────────────
# 与场景静态扫描同一情报注入机制（contract_findings.json + prompt 注入），
# 但契约检查与场景无关，独立扫描函数不混入场景扫描器。fail-open：任何异常
# 记 WARNING 返回空 findings，不阻断出题。

CONTRACT_FINDINGS_FILENAME = "contract_findings.json"


def _package_start_entry(project_root: Path) -> str | None:
    """读 package.json 的 start script 入口路径（string 命令形态）。

    仅支持 start script 为字符串形态（``"start": "node dist/server.js"``）；
    对象形态（platform 分派）/缺失/损坏返回 None（跳过该规则比对）。
    """
    try:
        pkg = json.loads((Path(project_root) / "package.json").read_text(
            encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(pkg, dict):
        return None
    scripts = pkg.get("scripts")
    if not isinstance(scripts, dict):
        return None
    start = scripts.get("start")
    if not isinstance(start, str) or not start.strip():
        return None
    return start.strip()


def scan_contract(project_root: Path) -> list[dict]:
    """契约只读一致性检查（planner 出题期，零 token 纯机械）。

    初始规则表（design D4，机械可查、误报即删）：
    1. ``serve_entry_missing``（high）：serve.cmd 入口（D1 同源解析器）文件不存在；
    2. ``serve_entry_vs_start_mismatch``（info）：serve.cmd 入口 ≠ package.json
       start script 入口（差异可能是合法设计，仅提示不拦截）；
    3. ``serve_entry_no_port_injection``（info）：cmd 无 {port} 且无
       $FENIX_VERIFY_PORT（与 load 侧 warning 同判据，补落盘让 admin 可见）。

    Returns:
        findings 列表（每条 {rule_id, severity, message, evidence}）；
        解析失败/异常记 WARNING 返回空列表（fail-open）。
    """
    findings: list[dict] = []
    try:
        from core.verify_contract import (
            entry_preflight_error,
            load_verify_contract,
            resolve_entry_path,
        )
        project_root = Path(project_root)
        contract = load_verify_contract(project_root)
        serve = contract.serve if contract is not None else None
        if serve is None or serve.kind != "command" or not serve.cmd.strip():
            return findings  # 非 command 形态 / 无契约：契约检查不适用
        cmd = serve.cmd.strip()
        entry = resolve_entry_path(cmd, project_root)
        # ① 入口存在性（与预检同源解析器，出题期提前暴露）
        if entry is not None and not Path(entry).is_file():
            # 与预检同款候选提示（entry_preflight_error 的判定+提示逻辑）
            preflight = entry_preflight_error(cmd, project_root)
            evidence = (preflight if preflight
                        else f"cmd={cmd!r}; cwd={project_root}")
            findings.append(dict(
                rule_id="serve_entry_missing",
                severity="high",
                message=(
                    f"serve.cmd 入口不存在: {entry}（cmd={cmd!r}）——场景执行将在"
                    f"spawn 前被入口存在性预检 fail-fast 拦截，建议先修正入口路径"
                    f"或确认构建产物已生成"),
                evidence=evidence,
            ))
        # ② serve.cmd 入口 vs package.json start script 入口
        start_cmd = _package_start_entry(project_root)
        start_entry = (resolve_entry_path(start_cmd, project_root)
                       if start_cmd else None)
        if (entry is not None and start_entry is not None
                and Path(entry) != Path(start_entry)):
            findings.append(dict(
                rule_id="serve_entry_vs_start_mismatch",
                severity="info",
                message=(
                    f"serve.cmd 入口 {entry} ≠ package.json start script 入口 "
                    f"{start_entry}——两者可能是合法设计（start 为 dev 形态、serve "
                    f"为构建产物形态），仅提示；若本意一致建议对齐"),
                evidence=(
                    f"serve.cmd={cmd!r}; package.json start={start_cmd!r}; "
                    f"pkg 入口={start_entry}"),
            ))
        # ③ 端口注入缺失（与 load 侧 warning 同判据，落盘让 admin 可见）
        if "{port}" not in cmd and "$FENIX_VERIFY_PORT" not in cmd:
            findings.append(dict(
                rule_id="serve_entry_no_port_injection",
                severity="info",
                message=(
                    "serve.cmd 未引用端口注入（{port} 占位符或 $FENIX_VERIFY_PORT "
                    "环境变量）——验证实例将与既有实例争抢固定端口（dashboard 端口"
                    "独占语义下 = 杀占用者接管）。建议迁移：cmd 中的端口写作 {port}"),
                evidence=(
                    f"cmd={cmd!r}; 缺 '{{port}}' 与 '$FENIX_VERIFY_PORT' "
                    f"（与 load 侧 warning 同判据）"),
            ))
    except Exception as e:  # noqa: BLE001 — fail-open 设计
        logger.warning(
            "scenario_static_check",
            f"契约静态检查异常（fail-open，返回空 findings）: "
            f"{type(e).__name__}: {e}",
        )
        return []
    return findings


def write_contract_findings(project_root: Path, spec_name: str,
                            findings: Sequence[dict]) -> None:
    """findings 覆盖写 ``.fenix/verify-progress/<spec>/contract_findings.json``。

    与 scenario 静态 findings 文件名分离（design D4：命名空间隔离比混表干净，
    注入段各自独立）。写失败仅 WARNING，不阻断出题（fail-open）。
    """
    target = (
        Path(project_root) / ".fenix" / "verify-progress"
        / spec_name / CONTRACT_FINDINGS_FILENAME
    )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(list(findings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001 — fail-open 设计
        logger.warning(
            "scenario_static_check",
            f"契约检查 findings 落盘失败 '{spec_name}'（写失败仅 WARNING，"
            f"不阻断）: {type(e).__name__}: {e}",
        )