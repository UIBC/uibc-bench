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


class WrongSubjectImported(RuntimeError):
    """import 到的是 uibc_core，但不是从定位到的被测仓来的。"""


def load(attr="did"):
    """从被测仓导入 uibc_core，并证明导进来的就是那棵树。

    2026-11-25 的教训（s02 组）。s02/s02b 原先自己硬写 sys.path 指向
    `../uibc-core-public`。当那个目录不存在时，sys.path 里那一行等于没写，
    `import uibc_core` 就落到解释器里已安装的那份——某台机器上是一个
    editable 安装，指向另一个检出。于是同一组用例在两台机器上测的是两棵
    不同的树，得出的却是同一个"结论"。定位得到、导入不到，就拒绝出结论。

    返回 (attr 指定的子模块, 被测仓绝对路径)。
    """
    import importlib
    import sys

    path = resolve()
    for name in [n for n in sys.modules if n == "uibc_core" or n.startswith("uibc_core.")]:
        del sys.modules[name]
    sys.path.insert(0, path)
    pkg = importlib.import_module("uibc_core")
    origin = os.path.abspath(getattr(pkg, "__file__", "") or "")
    if not (origin == path or origin.startswith(path + os.sep)):
        raise WrongSubjectImported(
            "定位到的被测仓是 %s，但 import 到的 uibc_core 来自 %s。本组拒绝在这个状态下出结论："
            "报告会落在没被要求测的那棵树上。" % (path, origin))
    mod = importlib.import_module("uibc_core." + attr)
    mod_origin = os.path.abspath(getattr(mod, "__file__", "") or "")
    if not (mod_origin == path or mod_origin.startswith(path + os.sep)):
        raise WrongSubjectImported(
            "定位到的被测仓是 %s，但 uibc_core.%s 来自 %s。" % (path, attr, mod_origin))
    return mod, path


def write_meta(out_path, subject, module, group):
    """在结果文件旁边写一份出处旁证，让报告能自证"测的是哪棵树"。

    写成旁挂文件而不是塞进 results 列表：用例清单必须正好等于本组断言的东西，
    baseline 才有意义。
    """
    import json
    import sys

    base = out_path[:-5] if out_path.endswith(".json") else out_path
    meta = {
        "group": group,
        "subject": subject,
        "uibc_core_file": os.path.abspath(getattr(module, "__file__", "") or ""),
        "python": sys.executable,
        "ui_env": os.environ.get("UIBC_SUBJECT", ""),
    }
    with open(base + ".subject.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return meta
