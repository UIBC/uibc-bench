# -*- coding: utf-8 -*-
"""把一次运行的结果与 baseline.json 比对，得出：回归 / 修复 / 新增 / 消失。

基线只记"每个用例当前公认的判定"，不记细节。用例消失（脚本不再产出）会被单独报出来，
防止"删掉失败用例让结果变绿"。
"""
import argparse, json, os, sys, time

KIT = os.path.dirname(os.path.abspath(__file__))
OK = {"PASS", "INFO"}


def load_run(run_dir):
    out = {}
    for n in sorted(os.listdir(run_dir)):
        if n.endswith("_results.json"):
            with open(os.path.join(run_dir, n), encoding="utf-8") as f:
                for it in json.load(f):
                    out[it["case"]] = dict(verdict=it["verdict"], group=n.replace("_results.json", ""),
                                           note=it.get("note", ""), extra=it.get("extra") or {})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--baseline", default=os.path.join(KIT, "baseline.json"))
    ap.add_argument("--update", action="store_true")
    a = ap.parse_args()
    run = load_run(a.run)
    base = {}
    bp = a.baseline
    if os.path.exists(bp):
        with open(bp, encoding="utf-8") as f:
            base = json.load(f)
    prev = {c["case"]: c for c in base.get("cases", [])}

    regress, fixed, added, missing, same = [], [], [], [], 0
    for k, v in run.items():
        p = prev.get(k)
        if not p:
            added.append((k, v))
        elif p["verdict"] == v["verdict"]:
            same += 1
        elif v["verdict"] in ("FAIL", "ERROR") and p["verdict"] in OK:
            regress.append((k, p["verdict"], v["verdict"]))
        else:
            fixed.append((k, p["verdict"], v["verdict"]))
    for k in prev:
        if k not in run:
            missing.append(k)

    print("基线 %s · 本次 %d 条 · 一致 %d · 回归 %d · 变化 %d · 新增 %d · 消失 %d"
          % (os.path.basename(bp), len(run), same, len(regress), len(fixed), len(added), len(missing)))
    for k, x, y in regress:
        print("  [回归] %s: %s -> %s  %s" % (k, x, y, run[k]["note"][:110]))
    for k, x, y in fixed:
        print("  [变化] %s: %s -> %s  %s" % (k, x, y, run[k]["note"][:110]))
    for k in missing:
        print("  [消失] %s（基线有、本次没有产出，须解释）" % k)
    for k, v in added:
        print("  [新增] %s %s  %s" % (k, v["verdict"], v["note"][:100]))

    diff = dict(at=os.path.basename(a.run), same=same,
                regress=[dict(case=k, was=x, now=y) for k, x, y in regress],
                changed=[dict(case=k, was=x, now=y) for k, x, y in fixed],
                added=[dict(case=k, verdict=v["verdict"]) for k, v in added],
                missing=missing)
    with open(os.path.join(a.run, "baseline_diff.json"), "w", encoding="utf-8") as f:
        json.dump(diff, f, ensure_ascii=False, indent=1)

    if a.update:
        base.setdefault("cases", [])
        by_case = {c["case"]: c for c in base["cases"]}
        for k, v in run.items():
            by_case[k] = dict(case=k, verdict=v["verdict"], group=v["group"], note=v["note"][:300])
        base["cases"] = [by_case[k] for k in sorted(by_case)]
        base["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        base["source_run"] = os.path.basename(a.run)
        with open(bp, "w", encoding="utf-8") as f:
            json.dump(base, f, ensure_ascii=False, indent=1)
        print("基线已刷新：%s" % bp)
    return 1 if (regress or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
