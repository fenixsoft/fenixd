#!/usr/bin/env python3
"""bin/ocr_review.py — ocr 的 HOME 重定向包装器（add-impl-code-review-gate）。

用法：bin/ocr_review.py <args...>  ↔  等价于 ocr <args...>，但 HOME 被替换为
run 级隔离目录（环境变量 FENIX_OCR_HOME），底层 ocr 可执行文件路径由
FENIX_OCR_BIN 指定（缺省 "ocr"，经 PATH 搜索）。

为何必须重定向 HOME（design D2，实测证据）：
- ocr 的 LLM 端点解析优先级为：~/.opencodereview/config.json 配置文件 >
  OCR_LLM_* 环境变量 > ANTHROPIC_* 环境变量 > shell rc。只要
  $HOME/.opencodereview/config.json 存在，OCR_LLM_URL/TOKEN/MODEL 即被静默
  压制（实测：全局配置有效 + OCR_LLM_* 指向不存在模型，审查仍以全局配置成功
  执行）。因此纯环境变量方案在任何装过 ocr 的机器上必然静默走错 provider。
- OCR_CONFIG_PATH 环境变量对 `ocr review` 无效（review 只读硬编码的
  $HOME/.opencodereview/config.json，只有只读的 `ocr llm test` 认该变量）。
- run 级 HOME 是唯一能确定性覆盖配置文件的手段，且天然满足并发隔离
  （每 run 一个目录）与「不触碰用户全局配置」。

行为：
- FENIX_OCR_HOME 非空 → 把子进程 HOME 设为它（其下
  .opencodereview/config.json 由 runner 在派发时写入），然后以
  os.execvp（带 PATH 搜索）替换为底层 ocr，透传全部 argv 与退出码。
  MUST 用 execvp 而非 execv：execv 不搜索 PATH，FENIX_OCR_BIN 取缺省裸名
  "ocr" 时必然抛 FileNotFoundError（本机实测：os.execv("ocr",...) →
  [Errno 2] No such file or directory，而 shutil.which("ocr") →
  /usr/bin/ocr）——那会把「ocr 已装」误判成「环境不可用」并静默降级放行。
- FENIX_OCR_HOME 为空 → 直接透传执行（不设 HOME），使包装器在无注入环境下
  仍可用（行为等价于直接调 ocr）。
- 包装器不创建 HOME 目录也不落任何日志：HOME 不存在时底层 ocr 自身报错
  退出，由实现者按 status: "unavailable" + 非空 reason 降级。
"""

import os
import sys


def main() -> None:
    ocr_home = os.environ.get("FENIX_OCR_HOME", "")
    ocr_bin = os.environ.get("FENIX_OCR_BIN", "") or "ocr"
    argv = [ocr_bin] + sys.argv[1:]
    if ocr_home:
        # 在 exec 前把 HOME 指向 run 级目录（ocr 只读
        # $HOME/.opencodereview/config.json 一个硬编码路径）。
        os.environ["HOME"] = ocr_home
    os.execvp(ocr_bin, argv)


if __name__ == "__main__":
    main()
