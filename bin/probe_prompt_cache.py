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

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
if str(FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_ROOT))

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


def _build_request(provider: dict) -> dict:
    """构造带 cache_control 的请求体（system 段作缓存前缀）。

    模型名取 provider 的 model（缺失时回退 common/default 字段检查）。
    """
    model = provider.get("model") or provider.get("default_model")
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


def _post_once(provider: dict, body: dict) -> tuple:
    """向 provider 的 messages 端点发一次请求，返回 (parsed_response_body, raw)。

    第一元素是**完整响应体**的 JSON 解析结果（dict；usage 是其中的子字典，
    由调用方 ``parsed.get("usage")`` 自取），非 usage 载荷本身（code-review
    item b74eff2a140a：旧 docstring 称返回 usage_dict 与实现不符）。响应体
    非法 JSON 时上抛 JSONDecodeError（code-review item c744bef56b6d：旧实现
    回退伪 dict，使解析失败轮被当成全零 usage 成功轮、裁决违背 probe() 的
    unknown 契约；上抛后由调用方 except 分支归入失败轮）。

    使用 stdlib urllib，避免依赖 requests；超时 120s。
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
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    # 解析异常一并上抛（code-review item c744bef56b6d）：JSONDecodeError 由
    # probe() 的 except 分支按既有网络/HTTP 异常同款归入失败轮，裁决落 unknown。
    return json.loads(raw), raw


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
    import yaml

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
    # _build_request 对缺 model/default_model 的 provider 抛 ValueError，
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
            # usage 归一化在守卫外（code-review item 14a31e7379a3）：int() 遇
            # 非数值 usage 属编程/数据错误，应向上抛真实异常——收窄守卫区域
            # 到网络调用后不再被静默记成网络型轮错误、掩盖缺陷仍产出裁决。
            usage = parsed.get("usage") or {}
            rounds.append(
                {
                    "round": i,
                    "input_tokens": int(usage.get("input_tokens") or 0),
                    "cache_read_input_tokens": int(
                        usage.get("cache_read_input_tokens") or 0
                    ),
                    "cache_creation_input_tokens": int(
                        usage.get("cache_creation_input_tokens") or 0
                    ),
                }
            )

    # cache_supported 判据：第二轮有读取且第二轮 cache_read 显著（>0）。
    # 第1轮 cache_read 高而第2轮低（或恒 0）= 写入不可复用，不支持。
    # 失败轮 ≠ 阴性（code-review item d0ea5e53913c）：任一轮网络/HTTP/解析
    # 异常时该轮 usage 缺失、r2_cr 恒 0——旧实现把一次失败探测静默裁成
    # cache_supported=False、main() 还 exit 0，与「连接错误应 exit 1」的
    # 模块契约相悖。存在失败轮次时两轮协议未完成，裁决标 unknown（None），
    # main() 据此 exit 1（与下方 rounds_distinct 的「不可信」口径一致）。
    r2 = rounds[1] if len(rounds) > 1 else {}
    r2_cr = int(r2.get("cache_read_input_tokens") or 0)
    # 失败轮判定被下方 cache_supported 裁决与 rounds_distinct 跳过判定共用，
    # 提取局部变量避免两处口径静默分叉（code-review item b162aa42ec7f）。
    has_failed_round = any("error" in r for r in rounds)
    if has_failed_round:
        cache_supported = None
    else:
        cache_supported = r2_cr > 0

    evidence = {"rounds": rounds}
    if errors:
        evidence["errors"] = errors
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
    import yaml

    # 文件消失（TOCTOU）不再 return None（code-review item 40a170065cd9）：
    # probe() 首检已对文件缺失短路并输出专门错误，正常控制流到不了这里；
    # 旧实现返回 None 会走「provider 不在配置文件」的误导文案，与真实原因
    # （文件刚被删除）不符。改抛与首检一致的 ValueError，由 probe() 归入
    # 确定性 JSON 判据输出。
    if not config_path.exists():
        raise ValueError(f"配置文件不存在: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
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
        default=str(FRAMEWORK_ROOT / ".fenix" / "config.yaml"),
        help="配置文件路径（默认 .fenix/config.yaml）",
    )
    args = parser.parse_args()

    result = probe(args.provider, Path(args.config))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 网络/参数类硬错误（provider 缺失）退出码 1；判据结果（无论支持与否）为 0
    if result.get("cache_supported") is None:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())