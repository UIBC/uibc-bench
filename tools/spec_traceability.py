# -*- coding: utf-8 -*-
"""规范追踪矩阵：官方 23 条断言 ↔ 本测试台 141 条用例，逐条对齐。

存在意义：只报"通过率"说明不了覆盖。评审真正问的是"规范里这一条，你用什么测的？"。
这个工具把官方报告里每条断言的规范深链，和我们的用例名放在一张表上，并**机械校验**：
  · 官方报告里有几条断言、映射表是不是一一对应（多/少都报错）
  · 映射引用的用例名是否真的存在于 baseline.json（防写不存在的东西）
  · 判定分布（direct / partial / suite-only / carrier / info）
  · bench 里有多少条用例**不对应任何官方断言**（这是我们超出套件的部分）

人工只负责写 tools/spec_map.json（每条的 kind 与 cases），解释不外包给工具。

用法：
  python tools/spec_traceability.py --report <官方 index.json> --baseline baseline.json \
      --map tools/spec_map.json --json out.json --md out.md
退出码：0 校验通过；1 有校验错误（映射缺行/多行/用例名不存在）
"""
import argparse
import json
import sys

KIND_LABEL = {
    "bench-direct": "bench 直接覆盖",
    "bench-partial": "bench 相邻覆盖",
    "carrier": "载体变异已证敏感",
    "suite-only": "仅套件覆盖",
    "info": "套件前置条件",
}


def load_official(path):
    j = json.load(open(path, encoding="utf-8"))
    rows = []
    for m in j.get("matrices", []):
        title = m.get("title", "")
        if title.startswith("At Risk"):      # 空壳矩阵，跳过
            continue
        for r in m.get("rows") or []:
            if isinstance(r, dict) and r.get("id"):
                rows.append(dict(matrix=title, id=r["id"], link=r.get("link", "")))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--map", required=True)
    ap.add_argument("--json", default="spec_trace.json")
    ap.add_argument("--md", default="")
    ap.add_argument("--probe", default="", help="binding_probe 结果 JSON（可选）；给了就按探针 id 判定覆盖")
    a = ap.parse_args()

    probe = {}
    if a.probe:
        pj = json.load(open(a.probe, encoding="utf-8"))
        probe = {r["id"].split(" ")[0]: bool(r["ok"]) for r in pj["results"]}

    official = load_official(a.report)
    baseline = json.load(open(a.baseline, encoding="utf-8"))["cases"]
    known = {c["case"] for c in baseline}
    mapping = json.load(open(a.map, encoding="utf-8"))["rows"]

    errors, warns = [], []
    off_ids = [r["id"] for r in official]
    if len(off_ids) != len(set(off_ids)):
        errors.append("官方报告里出现重复断言 id")
    missing_rows = [i for i in off_ids if i not in mapping]
    extra_rows = [k for k in mapping if k not in off_ids]
    if missing_rows:
        errors.append("映射表缺 %d 条官方断言：%s" % (len(missing_rows), missing_rows[:3]))
    if extra_rows:
        errors.append("映射表多出 %d 条不在官方报告里的条目：%s" % (len(extra_rows), extra_rows[:3]))

    for k, v in mapping.items():
        for c in v.get("cases", []):
            if c not in known:
                errors.append("用例名不存在于 baseline：%s（映射条目：%s）" % (c, k[:40]))

    used = set()
    rows_out = []
    for r in official:
        m = mapping.get(r["id"], {})
        kind = m.get("kind", "suite-only")
        cases = m.get("cases", [])
        pits = m.get("probe", [])
        used |= set(cases)
        probe_state = ""
        if pits:
            missing = [p for p in pits if p not in probe]
            bad = [p for p in pits if p in probe and not probe[p]]
            if missing:
                errors.append("映射引用的探针 id 不在结果里：%s（%s）" % (missing, r["id"][:40]))
            probe_state = "probe-pass" if (not missing and not bad) else "probe-fail"
        rows_out.append(dict(
            matrix=r["matrix"], requirement=r["id"], spec_link=r["link"],
            kind=kind, kind_label=KIND_LABEL.get(kind, kind),
            bench_cases=cases, probe_ids=pits, probe_state=probe_state,
            note=m.get("note", ""),
        ))

    # 有效覆盖：bench 直接 / 探针实测通过 / 载体变异 / 其余
    def effective(r):
        if r["kind"] == "bench-direct":
            return "bench-direct"
        if r["probe_state"] == "probe-pass":
            return "probe-direct"
        return r["kind"]

    dist = {}
    for r in rows_out:
        e = effective(r)
        dist[e] = dist.get(e, 0) + 1
        r["effective"] = e

    # 额外覆盖：不对应任何官方断言的用例
    extra = [c for c in baseline if c["case"] not in used]
    extra_by_group = {}
    for c in extra:
        extra_by_group[c["group"]] = extra_by_group.get(c["group"], 0) + 1

    out = dict(
        generated_from=dict(report=a.report, baseline=a.baseline, map=a.map),
        official_assertions=len(rows_out),
        bench_cases_total=len(baseline),
        bench_cases_mapped=len([c for c in baseline if c["case"] in used]),
        bench_cases_extra=len(extra),
        extra_by_group=extra_by_group,
        distribution=dist,
        errors=errors,
        rows=rows_out,
    )
    json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    lines = []
    lines.append("# 规范追踪矩阵（官方 %d 条断言 × 本测试台 %d 条用例）\n" % (len(rows_out), len(baseline)))
    lines.append("| # | 官方断言 | 规范锚点 | 判定 | 我们的对应用例 |")
    lines.append("|---|---|---|---|---|")
    for i, r in enumerate(rows_out, 1):
        anchor = r["spec_link"].split("#")[-1] if r["spec_link"] else "—"
        cases = "；".join(r["bench_cases"]) if r["bench_cases"] else "—"
        if r["probe_ids"]:
            cases = (cases + " ｜ 探针 " + "、".join(r["probe_ids"])) if cases != "—" \
                else "探针 " + "、".join(r["probe_ids"])
        lines.append("| %d | %s | `%s` | %s | %s |" % (i, r["requirement"], anchor, KIND_LABEL.get(r["effective"], r["effective"]), cases))
    lines.append("")
    lines.append("覆盖分布（有效口径）：%s" % json.dumps(dist, ensure_ascii=False))
    lines.append("原始判定分布：%s"
                 % json.dumps({k: sum(1 for r in rows_out if r["kind"] == k) for k in KIND_LABEL},
                              ensure_ascii=False))
    lines.append("额外覆盖（不对应任何官方断言的本台用例）：%d 条，分组 %s"
                 % (len(extra), json.dumps(extra_by_group, ensure_ascii=False)))
    if a.md:
        open(a.md, "w", encoding="utf-8").write("\n".join(lines) + "\n")

    print("官方断言=%d  映射行=%d  bench 总数=%d  有效覆盖：bench直连=%d 探针实测=%d 载体=%d 仅套件=%d 前置=%d"
          % (len(rows_out), len(mapping), len(baseline),
             dist.get("bench-direct", 0), dist.get("probe-direct", 0),
             dist.get("carrier", 0), dist.get("suite-only", 0), dist.get("info", 0)))
    print("额外覆盖=%d 条（不对应任何官方断言）" % len(extra))
    if errors:
        for e in errors:
            print("[ERROR]", e)
        return 1
    print("[OK] 映射一一对应，引用的用例名全部存在于 baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
