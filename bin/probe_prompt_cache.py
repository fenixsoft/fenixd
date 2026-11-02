#!/usr/bin/env python3
"""bin/probe_prompt_cache.py — 网关前缀缓存能力探针（fix-agent-lane-efficiency D3）。

对指定 provider 发送带 cache_control 的稳定前缀两轮请求，解析第二轮的
usage.cache_read_input_tokens，输出确定性 JSON 判据（provider / cache_supported /
evidence），用于判定该网关是否产生可复用的前缀缓存命中。

定案（2026-09-20 探针实测）：网关接受 cache_control 并写入缓存（第1次
cache_read≈6144），但写入的缓存不可复用（第2次 cache_read≈113 或恒 0）；
全 provider 一致。框架侧不做缓存优化（Non-Goals）。本探针保留以供网关升级
后复验。

用法：
    python3 bin/probe_prompt_cache.py --provider <provider-name>
    python3 bin/probe_prompt_cache.py --provider inferaiapi.com --config .fenix/config.yaml

选项：
    --provider  provider 名称（对应 llm.providers[].name）
    --config    配置文件路径（默认 .fenix/config.yaml）

退出码：0 = 成功（含 cache_supported=false），1 = 参数/连接错误。
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 项目根（.absolute() 不跟随软链接：经项目内 .fenix/bin/ 软链调用时 = 项目目录）。
# 与 fenix_dashboard.py 的项目资源口径一致——FRAMEWORK_ROOT 的 .resolve() 会
# 跟随软链回到框架主树（定位框架自身资源用），项目配置等资源须用项目根。
_THIS_DIR = Path(__file__).absolute().parent
_FENIX_DIR = _THIS_DIR.parent
PROJECT_ROOT = _FENIX_DIR.parent if _FENIX_DIR.name == ".fenix" else _FENIX_DIR

# ── 稳定前缀（约 5.8K 字符，按常见分词约 1.4-1.6K tokens，用于两次请求的比较）──
# 规模口径提醒（code-review item 395c8e4f7d2f）：旧注释写「~6K tokens」实为
# 字符数。前缀缓存普遍有最小可缓存长度门槛（如 Anthropic 1024 tokens），
# 若网关门槛高于此规模，缓存根本不会写入，探针会把「前缀太短不缓存」系统性
# 误判为「不支持缓存」的假阴性——复验时须结合 evidence.rounds[].input_tokens
# 的实际规模判读。
STABLE_PREFIX = (
    "You are a helpful assistant. " * 200
    + "Answer with a single word."
)

# cache_supported 相对阈值判据（code-review item 26112b3db466）：模块 docstring
# 定案「写入的缓存不可复用（第2次 cache_read≈113 或恒 0）」——113 这类零头远
# 小于前缀规模（约 1.4-1.6K tokens），旧判据 `r2_cr > 0` 会把小额命中误裁成
# 「支持」。改为相对阈值：第二轮 cache_read 须达到 max(绝对下限, 当轮
# input_tokens 的比例下限) 才认定命中可复用。
MIN_CACHE_HIT_TOKENS = 1024  # 网关最小可缓存长度量级（Anthropic 门槛，见上）
CACHE_HIT_INPUT_RATIO = 0.5  # 命中须达到当轮 input_tokens 的比例下限


def _build_request(provider: dict) -> dict:
    """构造带 cache_control 的请求体（user 消息前缀作缓存段）。

    模型名取 provider 的 model，缺失时抛 ValueError 走确定性 JSON 判据输出。
    """
    model = provider.get("model")
    if not model:
        raise ValueError(
            f"provider '{provider.get('name')}' 缺 model 字段，无法构造探针请求"
        )
    return {
        "model": model,
        "max_tokens": 10,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": STABLE_PREFIX,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ],
    }


# 响应体读取有界性（code-review item 2c32a36e73e5）：urlopen(timeout=) 是
# socket 单次操作超时而非总时限，探针直连的待诊断网关行为本不可信——若其以
# 慢速滴漏方式返回响应体（每次读取间隔小于 timeout），裸 resp.read() 永不
# 返回，两轮探测协议被无限期悬挂；响应体也无大小上限，超大 body 无界占用
# 内存。改为分块读取 + 总 deadline + 字节封顶兜底，超限抛 ValueError，由
# probe() 的 except 分支按既有网络/HTTP/解析异常同款归入失败轮（裁决落
# unknown、exit 1），不改变模块错误分类口径。
MAX_BODY_BYTES = 1 << 20  # 1 MiB：探针响应体（JSON usage 摘要）远小于此量级
BODY_READ_DEADLINE_SECONDS = 120  # 与 urlopen timeout 同口径的总时限


def _read_bounded(resp) -> bytes:
    """有界读取响应体：字节封顶 MAX_BODY_BYTES，总时限 BODY_READ_DEADLINE_SECONDS。

    单次 socket 操作超时仍由 urlopen(timeout=) 把守，这里补的是「多次操作
    累计」维度：慢速滴漏响应会先撞总 deadline，超大 body 先撞字节上限，
    两者都以 ValueError 收场，读入内存至多封顶值 + 单块。
    """
    deadline = time.monotonic() + BODY_READ_DEADLINE_SECONDS
    chunks = []
    total = 0
    while True:
        if time.monotonic() >= deadline:
            raise ValueError(
                f"响应体读取超出总时限 {BODY_READ_DEADLINE_SECONDS}s，按失败轮处理"
            )
        # 多读 1 字节以便响应体恰好等于上限时仍能探测 EOF（避免把恰在上限的
        # 合法 body 误判成超限）。
        chunk = resp.read(min(65536, MAX_BODY_BYTES - total + 1))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise ValueError(f"响应体超过 {MAX_BODY_BYTES} 字节上限，按失败轮处理")
    return b"".join(chunks)


def _post_once(provider: dict, body: dict) -> tuple:
    """向 provider 的 messages 端点发一次请求，返回 (parsed_response_body, raw)。

    第一元素是**完整响应体**的 JSON 解析结果（dict；usage 是其中的子字典，
    由调用方 ``parsed.get("usage")`` 自取），非 usage 载荷本身（code-review
    item b74eff2a140a：旧 docstring 称返回 usage_dict 与实现不符）。响应体
    非法 JSON 时上抛 JSONDecodeError（code-review item c744bef56b6d：旧实现
    回退伪 dict，使解析失败轮被当成全零 usage 成功轮、裁决违背 probe() 的
    unknown 契约；上抛后由调用方 except 分支归入失败轮）。

    使用 stdlib urllib，避免依赖 requests；超时 120s。响应体经 _read_bounded
    有界读取（字节封顶 + 总 deadline），超限抛 ValueError 归入失败轮。
    """
    import urllib.error
    import urllib.request

    baseurl = provider.get("baseurl", "").rstrip("/")
    if not baseurl:
        raise ValueError("provider 缺 baseurl")
    url = baseurl + "/v1/messages"
    api_key = provider.get("apikey") or provider.get("api_key")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": (api_key or ""),
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(
        req, timeout=BODY_READ_DEADLINE_SECONDS
    ) as resp:
        raw = _read_bounded(resp).decode("utf-8", errors="replace")
    # 解析异常一并上抛（code-review item c744bef56b6d）：JSONDecodeError 由
    # probe() 的 except 分支按既有网络/HTTP 异常同款归入失败轮，裁决落 unknown。
    parsed = json.loads(raw)
    # 顶层非对象同款归一（code-review item e83ef211a67e）：网关异常时可能返回
    # 合法 JSON 的标量/数组/字符串，probe() else 分支的 parsed.get 会抛
    # AttributeError 且不在 try 覆盖内，裸 traceback 破坏「确定性 JSON 判据」
    # 契约；转 ValueError 走同一失败轮路径，裁决落 unknown。
    if not isinstance(parsed, dict):
        raise ValueError(
            f"响应体顶层不是 JSON 对象（{type(parsed).__name__}）"
        )
    return parsed, raw


def probe(provider_name: str, config_path: Path) -> dict:
    """对指定 provider 执行前缀缓存探针。

    返回 JSON 判据 dict：
        provider: str
        cache_supported: bool
        evidence: dict（round1 / round2 usage 摘要）
    """
    # 配置文件缺失与 provider 名缺失区分（code-review item 9c3cc76cd230）：
    # 两者此前同返 None，probe() 恒报「provider 不在配置文件」——--config
    # 路径给错时诊断指向错误原因。文件缺失先行短路并如实报错。
    if not config_path.exists():
        return {
            "provider": provider_name,
            "cache_supported": None,
            "error": f"配置文件不存在: {config_path}",
        }
    # 配置文件解析失败同口径走 JSON 判据输出（code-review item 35e6d25230fd）：
    # yaml.safe_load 遇语法非法的 config.yaml 抛 YAMLError，不捕获则 main()
    # 直接 traceback 崩溃且 stdout 无 JSON，破坏模块「确定性 JSON 判据」契约；
    # 归为 cache_supported=None，main() 据此 exit 1（参数类硬错误同口径）。
    # ImportError 同口径（code-review item dd185b9d9c1c）：PyYAML 缺失的环境
    # 里裸 import 以 traceback 收场、stdout 无 JSON，同样破坏「确定性 JSON
    # 判据」契约；口径对齐 bin/test_for.py load_test_map（延迟导入+降级、把
    # PyYAML 缺失当真实场景），移入 try 归为 cache_supported=None 的判据 JSON。
    try:
        import yaml
    except ImportError as e:
        return {
            "provider": provider_name,
            "cache_supported": None,
            "error": f"PyYAML 依赖缺失，无法解析配置文件: {e}",
        }

    try:
        provider = _load_provider(config_path, provider_name)
    except yaml.YAMLError as e:
        return {
            "provider": provider_name,
            "cache_supported": None,
            "error": f"配置文件解析失败: {e}",
        }
    except ValueError as e:
        # 顶层非映射的结构漂移同口径走 JSON 判据输出（code-review item
        # fa9052277343）：与 _build_request 的 ValueError 同通道，归为
        # cache_supported=None，main() 据此 exit 1（参数类硬错误同口径）。
        return {
            "provider": provider_name,
            "cache_supported": None,
            "error": str(e),
        }
    if provider is None:
        return {
            "provider": provider_name,
            "cache_supported": None,
            "error": f"provider '{provider_name}' 不在配置文件 {config_path} 中",
        }
    # 参数类错误也走 JSON 判据输出路径（code-review item a3d3577dfe29）：
    # _build_request 对缺 model 的 provider 抛 ValueError，
    # 不捕获则 main() 直接 traceback 崩溃，破坏模块「确定性 JSON 判据」契约；
    # 归为 cache_supported=None，main() 据此 exit 1（参数类硬错误同口径）。
    try:
        body = _build_request(provider)
    except ValueError as e:
        return {
            "provider": provider_name,
            "cache_supported": None,
            "error": str(e),
        }

    rounds = []
    errors = []
    for i in (1, 2):
        # 两轮间隔前置并跳过首轮（code-review item 5db314ddc9fb）：sleep 放
        # 循环末尾会让最后一轮完成后仍无条件多等 1 秒才退出。
        if i > 1:
            time.sleep(1)
        try:
            parsed, _raw = _post_once(provider, body)
        except Exception as e:  # 网络/解析/HTTP 错误：round 留空并记录
            errors.append(f"round{i}: {e!r}")
            rounds.append({"round": i, "error": f"{e!r}"})
        else:
            # usage 归一化口径（code-review item 14a31e7379a3）：守卫区域收窄
            # 到网络调用，网络失败按网络型轮错误记录、不静默产出裁决。
            # 4ec7141a6b35 修订：usage 数据来自被探针直连的待诊断网关
            # （_read_bounded 注释已承认该网关行为不可信），truthy 非字典或
            # token 字段不可 int() 属**外部数据错误**而非本模块编程错误——
            # 按失败轮记 error 并保留 raw 供诊断，维持「确定性 JSON 判据 +
            # 契约退出码」；本模块编程错误（如键名笔误抛的 AttributeError）
            # 仍裸上抛，不与外部数据错误混为一谈。
            usage = parsed.get("usage") or {}
            if not isinstance(usage, dict):
                err = f"usage 不是 JSON 对象（{type(usage).__name__}）"
                errors.append(f"round{i}: {err}")
                rounds.append({"round": i, "error": err, "raw": _raw})
                continue
            try:
                input_tokens = int(usage.get("input_tokens") or 0)
                cache_read_tokens = int(usage.get("cache_read_input_tokens") or 0)
                cache_creation_tokens = int(
                    usage.get("cache_creation_input_tokens") or 0
                )
            except (TypeError, ValueError) as e:
                # token 字段为不可 int() 的值（如 "1e3"、列表）：外部数据错误
                # 同款归失败轮，raw 原文随轮保留供诊断。
                errors.append(f"round{i}: {e!r}")
                rounds.append({"round": i, "error": f"{e!r}", "raw": _raw})
            else:
                rounds.append(
                    {
                        "round": i,
                        "input_tokens": input_tokens,
                        "cache_read_input_tokens": cache_read_tokens,
                        "cache_creation_input_tokens": cache_creation_tokens,
                    }
                )

    # cache_supported 判据：第二轮 cache_read 达到相对阈值（不低于 max(
    # MIN_CACHE_HIT_TOKENS, 当轮 input_tokens × CACHE_HIT_INPUT_RATIO)）；
    # 只 >0 的小额零头（定案中的 ≈113）不算可复用命中。
    # 第1轮 cache_read 高而第2轮低（或恒 0）= 写入不可复用，不支持。
    # 失败轮 ≠ 阴性（code-review item d0ea5e53913c）：任一轮网络/HTTP/解析
    # 异常时该轮 usage 缺失、r2_cr 恒 0——旧实现把一次失败探测静默裁成
    # cache_supported=False、main() 还 exit 0，与「连接错误应 exit 1」的
    # 模块契约相悖。存在失败轮次时两轮协议未完成，裁决标 unknown（None），
    # main() 据此 exit 1（与下方 rounds_distinct 的「不可信」口径一致）。
    r2 = rounds[1] if len(rounds) > 1 else {}
    r2_cr = int(r2.get("cache_read_input_tokens") or 0)
    r2_input = int(r2.get("input_tokens") or 0)
    # 失败轮判定被下方 cache_supported 裁决与 rounds_distinct 跳过判定共用，
    # 提取局部变量避免两处口径静默分叉（code-review item b162aa42ec7f）。
    has_failed_round = any("error" in r for r in rounds)
    cache_hit_threshold = None
    if has_failed_round:
        cache_supported = None
    else:
        cache_hit_threshold = max(
            MIN_CACHE_HIT_TOKENS, r2_input * CACHE_HIT_INPUT_RATIO
        )
        cache_supported = r2_cr >= cache_hit_threshold

    evidence = {"rounds": rounds}
    if errors:
        evidence["errors"] = errors
    # 裁决依据透明化（code-review item 26112b3db466）：evidence 并列记录本轮
    # 判据所用阈值与 r2 两侧用量（r1/r2 的 cache_read 与 input_tokens 已在
    # rounds[] 全量给出），供复验脚本按定案口径复核而非只看布尔结论。
    evidence["cache_hit_threshold"] = cache_hit_threshold
    evidence["r2_cache_read_input_tokens"] = r2_cr
    evidence["r2_input_tokens"] = r2_input
    # D3 定案记录：网关不接受可复用前缀缓存时输出 false 与实测差异。
    # 任一轮失败时差异不可判定（成功轮子集可能缩成单元素，把真实差异
    # 掩盖为「相同」），显式标注跳过而非给出误导性 distinct=False。
    if has_failed_round:
        evidence["rounds_distinct"] = None
        evidence["rounds_distinct_note"] = "存在失败轮次，差异判定不可信，已跳过"
    else:
        distinct = len(set(
            int(r.get("cache_read_input_tokens") or 0) for r in rounds
        )) > 1
        evidence["rounds_distinct"] = distinct
    return {
        "provider": provider_name,
        "cache_supported": cache_supported,
        "evidence": evidence,
    }


def _load_provider(config_path: Path, provider_name: str):
    """从配置文件中提取指定 provider 的连接信息。"""
    # ImportError 归一（code-review item dd185b9d9c1c）：PyYAML 缺失时裸
    # import 抛 ImportError，不在 probe() 捕获的 (yaml.YAMLError, ValueError)
    # 之列，会裸 traceback 破坏「确定性 JSON 判据」契约；与下方 OSError 处理
    # 同口径转 ValueError，由调用方转 cache_supported=None 的判据 JSON。
    try:
        import yaml
    except ImportError as e:
        raise ValueError(f"PyYAML 依赖缺失，无法解析配置文件: {e}") from e

    # 文件消失（TOCTOU）不再 return None（code-review item 40a170065cd9）：
    # probe() 首检已对文件缺失短路并输出专门错误，正常控制流到不了这里；
    # 旧实现返回 None 会走「provider 不在配置文件」的误导文案，与真实原因
    # （文件刚被删除）不符。改抛与首检一致的 ValueError，由 probe() 归入
    # 确定性 JSON 判据输出。
    if not config_path.exists():
        raise ValueError(f"配置文件不存在: {config_path}")
    # 存在但不可读/IO 错误归一（code-review item 820f8b6902c8）：open 抛出的
    # PermissionError 等 OSError 族不在 probe() 捕获的 (yaml.YAMLError,
    # ValueError) 之列，会裸 traceback 破坏「确定性 JSON 判据」契约；与下方
    # 结构漂移处理同口径转 ValueError（UnicodeDecodeError 属 ValueError 族
    # 已天然覆盖，此处只补 OSError 缺口）。
    try:
        with config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except OSError as e:
        raise ValueError(f"配置文件无法读取: {e}") from e
    # 顶层非映射归一（code-review item fa9052277343）：config.yaml 顶层是
    # 列表/标量（合法 YAML 但结构漂移）时 raw.get 抛 AttributeError 逃过
    # probe() 的判据转换，转 ValueError 由调用方转确定性 JSON 判据。
    if not isinstance(raw, dict):
        raise ValueError(
            f"配置文件顶层不是映射（{type(raw).__name__}）: {config_path}"
        )
    # llm 段与 providers 结构漂移归一（code-review item 634ca53039cf）：
    # llm 为列表/标量（truthy）时 llm.get 抛 AttributeError、providers 为
    # 标量时 for 循环抛 TypeError，均不在 probe() 捕获的
    # (yaml.YAMLError, ValueError) 之列，会裸 traceback 破坏「确定性 JSON
    # 判据」契约。与上方顶层处理同口径转 ValueError。
    llm = raw.get("llm") or {}
    if not isinstance(llm, dict):
        raise ValueError(
            f"配置文件 llm 段不是映射（{type(llm).__name__}）: {config_path}"
        )
    providers = llm.get("providers") or []
    if not isinstance(providers, list):
        raise ValueError(
            f"配置文件 llm.providers 不是列表"
            f"（{type(providers).__name__}）: {config_path}"
        )
    for p in providers:
        if isinstance(p, dict) and p.get("name") == provider_name:
            return p
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="网关前缀缓存能力探针")
    parser.add_argument("--provider", required=True, help="provider 名称")
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / ".fenix" / "config.yaml"),
        help="配置文件路径（默认 .fenix/config.yaml）",
    )
    args = parser.parse_args()

    # expanduser（code-review item 8bf4a423c4ef）：引号包裹传入的 ~ 开头路径
    # 按字面落盘会误报「配置文件不存在」，口径对齐 bin/fenix_detect_artifacts.py
    try:
        # 路径解析收口进 try（与 fenix_detect_artifacts.py/fenix_verify_contract.py
        # 同场景防护对齐）：expanduser 解析不出家目录抛 RuntimeError、含空字节
        # 路径在构造/resolve 阶段抛 ValueError，裸抛会以 traceback 收场、
        # stdout 无 JSON，破坏模块「确定性 JSON 判据」契约
        config_path = Path(args.config).expanduser().resolve()
    except (ValueError, OSError, RuntimeError) as e:
        print(f"错误: 配置文件路径无法解析: {e}", file=sys.stderr)
        return 1

    result = probe(args.provider, config_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 网络/参数类硬错误（provider 缺失）退出码 1；判据结果（无论支持与否）为 0
    if result.get("cache_supported") is None:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())