# -*- coding: utf-8 -*-
"""登记预演：一份 resolver 清单进了官方套件，会真的产生用例吗？

背景（写清楚，避免误用）：官方套件 tests/helpers.js 的规则是
    methods = supportedDidMethods 里"有 did-methods/<method>.json 向量"的那些；
    missingDidMethods = 声明了但没有向量的那些（不进用例，只在报告里挂着）。
所以"在清单里多写一个方法"不等于"多测一个方法"。本工具把这条规则做成可复算的检查，
让你在提 PR 之前就知道：这次登记会新增几条用例、哪些声明是空头。

用法：
    python tools/registration_preflight.py --suite <套件目录> --resolver <清单.json>
    python tools/registration_preflight.py --suite <套件目录>          # 只盘点套件现状
输出：每个声明方法的命中/空缺、可用向量数、以及"本次登记新增用例数"。
退出码：0=有新增用例；1=声明里有空头（新增 0 条）；2=环境问题。
"""
import argparse
import json
import os
import sys


def load_methods(suite):
    d = os.path.join(suite, "did-methods")
    if not os.path.isdir(d):
        return None
    out = {}
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json"):
            continue
        method = "did:" + f[: -len(".json")]
        try:
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                obj = json.load(fh)
        except Exception as e:
            out[method] = {"error": str(e)}
            continue
        counts = {k: len(obj.get(k) or []) for k in ("valid", "notFound", "deactivated")}
        out[method] = counts
    return out


def load_resolver(path):
    with open(path, encoding="utf-8") as fh:
        r = json.load(fh)
    for key in ("name", "implementation", "endpoint", "supportedDidMethods"):
        if key not in r:
            raise ValueError("清单缺字段 %s" % key)
    if not isinstance(r["supportedDidMethods"], list) or not r["supportedDidMethods"]:
        raise ValueError("supportedDidMethods 必须是非空数组")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True)
    ap.add_argument("--resolver")
    ap.add_argument("--json")
    a = ap.parse_args()

    methods = load_methods(a.suite)
    if methods is None:
        print("[EXIT=2] %s 下没有 did-methods/，不像是官方套件目录" % a.suite)
        return 2

    print("== 套件现有向量（按方法）==")
    for m, c in methods.items():
        print("  %-12s %s" % (m, c))
    coverage = set(methods.keys())

    if not a.resolver:
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump({"suite": a.suite, "methods_in_suite": methods}, fh,
                          ensure_ascii=False, indent=1)
            print("json=%s" % a.json)
        return 0

    try:
        r = load_resolver(a.resolver)
    except Exception as e:
        print("[EXIT=2] 清单读不了：%s" % e)
        return 2

    print("\n== 本次登记的预演 ==")
    print("  name=%s" % r["name"])
    print("  endpoint=%s" % r["endpoint"])
    declared = r["supportedDidMethods"]
    missing = [m for m in declared if m not in coverage]
    hit = [m for m in declared if m in coverage]
    new_cases = 0
    for m in declared:
        if m in coverage:
            c = methods[m]
            n = sum(c.get(k, 0) for k in ("valid", "notFound", "deactivated"))
            new_cases += n
            print("  [命中] %-12s 向量 %s → 计入 %d 条用例" % (m, c, n))
        else:
            print("  [空头] %-12s 套件没有 did-methods/%s.json → 进 missingDidMethods，不产生用例"
                  % (m, m.split(":", 1)[1]))

    verdict = "会产生 %d 条用例" % new_cases if new_cases else "新增 0 条用例（声明是空头）"
    print("\n结论：%s" % verdict)
    if new_cases:
        print("      注意：方法被计入 ≠ 会通过；实现能不能解，跑一遍才知道。")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"suite": a.suite, "resolver": r, "methods_in_suite": methods,
                       "hit": hit, "missing": missing, "new_cases": new_cases,
                       "verdict": verdict}, fh, ensure_ascii=False, indent=1)
        print("json=%s" % a.json)
    return 0 if new_cases else 1


if __name__ == "__main__":
    sys.exit(main())
