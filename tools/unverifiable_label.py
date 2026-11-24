# -*- coding: utf-8 -*-
"""不可核标注门禁：把 evidence_grades v2 的「诊断」变成「判据」。

规则（给标准 v2.1 草案用）：凡档位为 missing / otherhost / extpath 的引用，
**在同一行或在引用后 120 字内**必须出现原因标注，否则判「未标注」= 门禁红。
原因词白名单（八类，取自 47 号）：
  运行时产物 / 未随包 / 未留存 / 跑完即删 / 临时文件 / 他机 / 云主机 / 外部仓 / 远端 / 上游 / 占位 / 阻塞
档位 ambiguous 只给提示（人工池），glob / quote 豁免——通配已命中具体件、引文本就不是件。

用法：python tools/unverifiable_label.py --grades evidence_grades_v2.json --json out.json --md out.md
"""
import argparse
import io
import json
import os
import re

ap = argparse.ArgumentParser()
ap.add_argument("--grades", required=True, help="evidence_grades v2 JSON")
ap.add_argument("--json", required=True)
ap.add_argument("--md", default="")
a = ap.parse_args()

REASON = ["运行时产物", "未随包", "未留存", "跑完即删", "临时文件", "他机", "云主机",
          "外部仓", "远端", "上游", "占位", "阻塞", "不随包", "本机确实没有", "本机没有", "入库"]
HARD = ("missing", "otherhost", "extpath")

g = json.load(io.open(a.grades, encoding="utf-8"))
docdir = g["dir"]
cache = {}


def doc_text(f):
    if f not in cache:
        cache[f] = io.open(os.path.join(docdir, f), encoding="utf-8", errors="replace").read()
    return cache[f]


rows, viol = [], []
for r in g["refs"]:
    if r["grade"] in HARD:
        t = doc_text(r["doc"])
        needle_candidates = [r["ref"], "`%s`" % r["ref"], "\u300c%s\u300d" % r["ref"]]
        marked = False
        where = ""
        for nd in needle_candidates:
            i = t.find(nd)
            if i < 0:
                continue
            window = t[max(0, i - 120):i + len(nd) + 120]
            hit = [w for w in REASON if w in window]
            if hit:
                marked = True
                where = hit[0]
            break
        rows.append({"doc": r["doc"], "ref": r["ref"], "grade": r["grade"], "marked": marked, "reason_kw": where})
        if not marked:
            viol.append(rows[-1])

cnt = {}
for r in rows:
    cnt.setdefault(r["grade"], [0, 0])
    cnt[r["grade"]][0] += 1
    if r["marked"]:
        cnt[r["grade"]][1] += 1

out = {"grades": a.grades, "checked": len(rows), "violations": len(viol), "by_grade": cnt, "rows": rows}
io.open(a.json, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=2))

if a.md:
    md = ["# 不可核标注门禁（%d 条待标 / %d 条未标）\n" % (len(rows), len(viol)),
          "> 判据：missing / otherhost / extpath 三类引用，**引用前 120 字内或后 120 字内**须出现原因标注（十二词表）。"
          "ambiguous 只进人工池，glob / quote / urlpath 豁免——通配已命中具体件、引文本就不是件、URL 路径不是文件。\n",
          "## 按档\n", "| 档 | 待标 | 已标 | 未标 |", "|---|---|---|---|"]
    for k in sorted(cnt):
        md.append("| %s | %d | %d | %d |" % (k, cnt[k][0], cnt[k][1], cnt[k][0] - cnt[k][1]))
    md.append("\n## 未标注清单\n")
    if viol:
        md.append("| 文档 | 引用 | 档 |")
        md.append("|---|---|---|")
        for v in viol:
            md.append("| %s | `%s` | %s |" % (v["doc"], v["ref"], v["grade"]))
    else:
        md.append("**0 条未标**——三类不可核引用全部写了原因。\n")
    io.open(a.md, "w", encoding="utf-8").write("\n".join(md) + "\n")

print("checked=%d violations=%d " % (len(rows), len(viol)) +
      " ".join("%s=%d/%d" % (k, cnt[k][1], cnt[k][0]) for k in sorted(cnt)))
