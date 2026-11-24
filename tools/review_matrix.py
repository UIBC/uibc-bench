# -*- coding: utf-8 -*-
"""外部复核轮次对照矩阵（把"句子级判定"归一到"门级判定"，才敢跨轮比）。

为什么需要它：第八轮按句判出 17 条、第九轮 28 条、第十轮按行只判 10 条门。
条数不能直接比——**评审方换了判定单元，条数就变了**。这里做三件事：
  1. 用正则把每条判定归到 S0–S9 某一门（取 quote/assertion 里出现的门号）；
  2. 每门按"最不利判定优先"收敛成一个门级结论（无法核实 > 部分核实 > 可核实），
     另存票型分布，不掩盖分歧；
  3. 两轮之间按门做一致度（同判 / 不同判 / 一方无判定），输出一致率。

用法：
    python tools/review_matrix.py --rounds r8=runs/a.json r9=runs/b.json --out runs/matrix.json --md runs/matrix.md
"""
import argparse
import json
import os
import re
import sys
import collections

GATES = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"]
# 不利程度排序：数字越小越不利
RANK = {"无法核实": 1, "不实": 0, "夸大": 2, "部分核实": 3, "部分核实 ": 3, "可核实": 4}


def gate_of(text):
    m = re.findall(r"\bS([0-9])\b", text or "")
    if not m:
        return None
    # 取第一个出现的门号（引用句通常以门开头）
    return "S" + m[0]


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    items = [i for i in (d.get("items") or []) if i.get("quote") != "SUMMARY" and i.get("assertion") != "SUMMARY"]
    per = collections.defaultdict(list)
    for it in items:
        g = gate_of(it.get("quote") or it.get("assertion") or "")
        v = (it.get("verdict") or "").strip()
        if g and v:
            per[g].append(v)
    gate_verdict, dist = {}, {}
    for g in GATES:
        vs = per.get(g, [])
        dist[g] = dict(collections.Counter(vs))
        if vs:
            gate_verdict[g] = min(vs, key=lambda x: RANK.get(x, 5))
        else:
            gate_verdict[g] = ""
    return {"model": d.get("model"), "file": os.path.basename(path), "n_items": len(items),
            "evidence_pack": d.get("evidence_pack", ""), "elapsed_s": d.get("elapsed_s"),
            "usage": d.get("usage", {}), "gate_verdict": gate_verdict, "dist": dist,
            "progress": d.get("status")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", nargs="+", required=True, help="label=path 形式")
    ap.add_argument("--out", required=True)
    ap.add_argument("--md", default="")
    a = ap.parse_args()

    rounds = []
    for spec in a.rounds:
        label, path = spec.split("=", 1)
        r = load(path)
        r["label"] = label
        rounds.append(r)

    # 一致度：任意两轮逐门对照
    pairs = []
    for i in range(len(rounds)):
        for j in range(i + 1, len(rounds)):
            A, B = rounds[i], rounds[j]
            same = diff = miss = 0
            detail = []
            for g in GATES:
                va, vb = A["gate_verdict"][g], B["gate_verdict"][g]
                if not va or not vb:
                    miss += 1
                    detail.append({"gate": g, "a": va, "b": vb, "rel": "缺判"})
                elif va == vb:
                    same += 1
                    detail.append({"gate": g, "a": va, "b": vb, "rel": "同"})
                else:
                    diff += 1
                    detail.append({"gate": g, "a": va, "b": vb, "rel": "异"})
            pairs.append({"a": A["label"], "b": B["label"], "same": same, "diff": diff, "missing": miss,
                          "agree_rate": round(same / max(1, same + diff), 3), "detail": detail})

    out = {"gate_order": GATES, "rounds": rounds, "pairs": pairs}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("%-6s %-28s %-6s %s" % ("轮", "模型", "条数", "门级结论"))
    for r in rounds:
        print("%-6s %-28s %-6d %s" % (r["label"], (r["model"] or "")[:28], r["n_items"],
              " ".join("%s=%s" % (g, r["gate_verdict"][g] or "-") for g in GATES)))
    print("\n对照：")
    for p in pairs:
        print("%s vs %s：同 %d / 异 %d / 缺判 %d → 一致率 %.2f" %
              (p["a"], p["b"], p["same"], p["diff"], p["missing"], p["agree_rate"]))
        for d in p["detail"]:
            if d["rel"] == "异":
                print("   异：%s  %s(%s) vs %s(%s)" % (d["gate"], p["a"], d["a"], p["b"], d["b"]))
    print("json=%s" % a.out)

    if a.md:
        lines = ["# 复核对照矩阵（门级）", "",
                 "| 轮 | 模型 | 判定条数 | " + " | ".join(GATES) + " |",
                 "|---|---|---|" + "---|" * len(GATES)]
        for r in rounds:
            lines.append("| %s | %s | %d | %s |" % (r["label"], r["model"], r["n_items"],
                         " | ".join(r["gate_verdict"][g] or "-" for g in GATES)))
        lines += ["", "## 两两一致度", "", "| 对照 | 同 | 异 | 缺判 | 一致率 |", "|---|---|---|---|---|"]
        for p in pairs:
            lines.append("| %s vs %s | %d | %d | %d | %.2f |" % (p["a"], p["b"], p["same"], p["diff"], p["missing"], p["agree_rate"]))
        open(a.md, "w", encoding="utf-8").write("\n".join(lines))
        print("md=%s" % a.md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
