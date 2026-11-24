# -*- coding: utf-8 -*-
"""被测仓统一解析：`UIBC_SUBJECT` 优先，其次 `<bench 根>/uibc-core-public`。

2026-11-24 的教训：s03/s04/s05/s07 曾各自硬写 `uibc-core-public`，于是
`UIBC_SUBJECT` 对它们无效——同一次 `python run.py` 里，一半组测 A 仓、一半组测 B 仓，
对外人来说就是"明明指了路径，一半组还是 BLOCKED"。现在只留一个入口。
"""
import os


def kit_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve(require=True):
    """返回被测仓绝对路径；找不到时 require=True 就抛出带操作指引的 RuntimeError。"""
    env = os.environ.get("UIBC_SUBJECT", "").strip()
    default = os.path.join(kit_root(), "uibc-core-public")
    cand = env or default
    if cand and os.path.isdir(cand) and os.path.isdir(os.path.join(cand, "uibc_core")):
        return os.path.abspath(cand)
    if not require:
        return None
    raise RuntimeError(
        "找不到被测仓（uibc-core 工作树）。\n"
        "  现在的取值：%s\n"
        "  三条路选一条：\n"
        "    python run.py --subject <uibc-core 目录>      （推荐，run.py 会替所有组传下去）\n"
        "    UIBC_SUBJECT=<目录> python run.py             （bash）\n"
        "    $env:UIBC_SUBJECT='<目录>'; python run.py     （PowerShell）\n"
        "  或者克隆到默认位置：git clone --depth 1 https://github.com/zhaoxinghua09-cell/uibc-core uibc-core-public"
        % (cand or "(未设置)"))
