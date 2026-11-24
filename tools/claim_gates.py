# -*- coding: utf-8 -*-
"""全文级读数：把"逐条断言的判定"归到 S0–S9，出每门的覆盖率、判定分布、最不利结论、跨厂商一致度。

它与 review_matrix.py 的分工：review_matrix 比的是"整份文档/某轮的门级结论"（表级、旧问法），
本工具比的是"同一份编号清单上，两家逐条回完之后的门级结论"（全文级、规格 v4）。
两者不可混用：一个的分母是十门表，一个的分母是 90+ 条断言。

用法：
    python tools/claim_gates.py --claims runs/claims38_full.json \
        --reviews "ds=runs/revF_full_ds.json" "qw=runs/revF_full_qw.json" \
        --out runs/gates_full.json --md runs/gates_full.md
"""
import argparse
import collections
import json
import os
import sys

GATES = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"]
RANK = {"不实": 0, "夸大": 1, "无法核实": 2, "部分核实": 3, "可核实": 4}


def load(claims_path, reviews):
    claims = {c["id"]: c for c in json.load(open(claims_path, encoding="utf-8"))["claims"]}
    out = []
    for spec in reviews:
        label, path = spec.split("=", 1)
        d = json.load(open(path, encoding="utf-8"))
        verdicts = {str(i.get("id")): (i.get("verdict") or "").strip() for i in (d.get("items") or [])}
        out.append({"label": label, "model": d.get("model"), "path": os.path.basename(path),
                    "status": d.get("status"), "verdicts": verdicts, "coverage": d.get("coverage")})
    return claims, out


def summarize(claims, rounds):
    rows = []
    for r in rounds:
        per = collections.defaultdict(list)
        miss = collections.defaultdict(int)
        for cid, c in claims.items():
            g = c.get("gate") or ""
            if not g:
                continue
            v = r["verdicts"].get(cid)
            if not v:
                miss[g] += 1
                continue
            per[g].append(v)
        gate = {}
        for g in GATES:
            vs = per.get(g, [])
            if vs:
                worst = min(vs, key=lambda x: RANK.get(x, 9))
                gate[g] = {"n": len(vs), "missing": miss.get(g, 0), "worst": worst,
                           "dist": dict(collections.Counter(vs))}
            else:
                gate[g] = {"n": 0, "missing": miss.get(g, 0), "worst": "", "dist": {}}
        rows.append({"label": r["label"], "model": r["model"], "status": r["status"],
                     "coverage": r["coverage"], "gate": gate})
    return rows


def agree(rows):
    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            A, B = rows[i], rows[j]
            same = diff = 0
            detail = []
            for g in GATES:
                a, b = A["gate"][g]["worst"], B["gate"][g]["worst"]
                if not a or not b:
                    continue
                if a == b:
                    same += 1
                else:
                    diff += 1
                detail.append({"gate": g, "a": a, "b": b, "same": a == b})
            pairs.append({"a": A["label"], "b": B["label"], "same": same, "diff": diff,
                          "rate": round(same / max(1, same + diff), 3), "detail": detail})
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claims", required=True)
    ap.add_argument("--reviews", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--md", default="")
    a = ap.parse_args()

    claims, rounds = load(a.claims, a.reviews)
    rows = summarize(claims, rounds)
    pairs = agree(rows)

    print("%-4s %-30s %s" % ("轮", "模型", "门级最不利结论（全文级）"))
    for r in rows:
        cov = r["coverage"] or {}
        print("%-4s %-30s cov=%s/%s  %s" % (r["label"], (r["model"] or "")[:30],
              cov.get("returned"), cov.get("expected"),
              " ".join("%s=%s" % (g, r["gate"][g]["worst"] or "-") for g in GATES)))
    for p in pairs:
        print("%s vs %s：同 %d / 异 %d → 一致率 %.2f" % (p["a"], p["b"], p["same"], p["diff"], p["rate"]))

    out = {"claims": a.claims, "rounds": rows, "pairs": pairs, "gate_order": GATES}
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if a.md:
        lines = ["# 全文级门读数（断言级 → 门级）", "",
                 "| 轮 | 模型 | 覆盖率 | " + " | ".join(GATES) + " |",
                 "|---|---|---|" + "---|" * len(GATES)]
        for r in rows:
            cov = r["coverage"] or {}
            lines.append("| %s | %s | %s/%s | %s |" % (r["label"], r["model"], cov.get("returned"),
                         cov.get("expected"), " | ".join(r["gate"][g]["worst"] or "-" for g in GATES)))
        lines += ["", "## 每门明细（条数 / 判定分布）", "",
                  "| 门 | " + " | ".join(r["label"] for r in rows) + " |",
                  "|---|" + "---|" * len(rows)]
        for g in GATES:
            cells = []
            for r in rows:
                d = r["gate"][g]
                cells.append("n=%d %s" % (d["n"], json.dumps(d["dist"], ensure_ascii=False)))
            lines.append("| %s | %s |" % (g, " | ".join(cells)))
        if pairs:
            lines += ["", "## 一致度", "", "| 对照 | 同 | 异 | 一致率 |", "|---|---|---|---|"]
            for p in pairs:
                lines.append("| %s vs %s | %d | %d | %.2f |" % (p["a"], p["b"], p["same"], p["diff"], p["rate"]))
        open(a.md, "w", encoding="utf-8").write("\n".join(lines))
        print("md=%s" % a.md)
    print("json=%s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
