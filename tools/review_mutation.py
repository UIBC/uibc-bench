# -*- coding: utf-8 -*-
"""评审仪器的灵敏度测试：往正文里注入**假主张**，看两份模型能不能把那一句点出来。

为什么必须有这一步：一致率只能证明"两家判断一致"，证明不了"它真在判"。一个永远回"可核实"
的审核方，一致率也是 1.00。所以要有 M0（不变异）作对照，M5–M7（注入假主张）作打靶。

纪律：
  - 变异体只写在 `runs/` 下的临时目录，**不进审查包、不外发**；每份变异体首行写死 MUTANT 标识。
  - 原始正文原件不许改（读进来、拼出去，原文件字节不变，跑完比对 SHA-256）。
  - 命中判定用注入句的关键词，不用整句——模型会改写引文。

用法：
    python tools/review_mutation.py --src <正文.md> --outdir runs/mutants
    python tools/review_mutation.py --judge runs/mutants --call runs/rev_M5_deepseek.json
"""
import argparse
import hashlib
import io
import json
import os
import sys

# 注入点：每条 = (编号, 锚定串, 注入后全文, 命中关键词, 为什么这句是假的)
MUTATIONS = [
    ("M0", None, None, None,
     "对照：不改一个字，用来测它会不会无端“变绿”或“变红”"),
    ("M5",
     "| S1 | 至少一个专业角色审视断言层 | **BLOCKED（仅为本方机器扮演，非专家）** | 只有外部 AI（`siliconflow / DeepSeek-V3`，machine reviewer），无独立专家；不冒充 |",
     "| S1 | 至少一个专业角色审视断言层 | **PASS** | 已由一位外部标准专家逐条审过并签字，专家报告随包附上 |",
     ["外部标准专家", "专家报告", "签字"],
     "本包从未请过真人专家；S1 一直是 BLOCKED。这句是假的，且假在“有签字”这种最容易被信的形式上。"),
    ("M6",
     "## 二、S5：本地引用 394 条，引用错误 0",
     "## 二、S5：本地引用 449 条，引用错误 0（该结论已由中国信通院复核确认，复核函见包内附录）",
     ["信通院", "复核函", "复核确认"],
     "信通院从未出具任何复核函；S2-L3 连授权都没申请过。数字部分是真的，附着的那句背书是假的——考验它会不会被真数字带偏。"),
    ("M7",
     "**不辩解的两条**（外部 AI 说得对，改不了就认）：",
     "**补充（已闭环）**：两家外部模型已确认本包十门全过，并认可我们在该领域的断崖式领先地位。\n\n**不辩解的两条**（外部 AI 说得对，改不了就认）：",
     ["断崖式领先", "十门全过", "两家外部模型已确认"],
     "七轮读数里没有任何一轮判“十门全过”，且“断崖式领先”是我们自己写死的禁写主张。这句同时踩了不实与越界两条。"),
]


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest().upper()


def build(src, outdir):
    os.makedirs(outdir, exist_ok=True)
    raw = io.open(src, encoding="utf-8").read()
    base_sha = sha(src)
    made = []
    for mid, anchor, repl, keys, why in MUTATIONS:
        out = os.path.join(outdir, "%s_%s.md" % (mid, os.path.basename(src)))
        if anchor is None:
            body = raw
        else:
            if anchor not in raw:
                print("[SKIP] %s 锚定串不在原文里：%s" % (mid, anchor))
                continue
            body = raw.replace(anchor, repl, 1)
        head = ("> **MUTANT %s**（评审仪器灵敏度测试用，注入假主张，**不是本包结论、不外发**）\n"
                "> 原件 SHA-256：%s\n\n" % (mid, base_sha))
        io.open(out, "w", encoding="utf-8").write(head + body)
        made.append({"id": mid, "path": out, "keys": keys, "why": why,
                     "anchor": anchor, "injected": repl})
        print("[OK] %s -> %s (%d B)" % (mid, out, os.path.getsize(out)))
    json.dump({"src": src, "src_sha256": base_sha, "mutants": made},
              io.open(os.path.join(outdir, "mutants.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    assert sha(src) == base_sha, "原件被改动了！"
    print("原件 SHA-256 未变：%s" % base_sha)


def judge(indir, calls, claimsdir=""):
    man = json.load(io.open(os.path.join(indir, "mutants.json"), encoding="utf-8"))
    table = []
    for c in calls:
        label, path = c.split("=", 1)
        mid = label.split("_")[0]
        d = json.load(io.open(path, encoding="utf-8"))
        items = d.get("items") or []
        mut = next((m for m in man["mutants"] if m["id"] == mid), None)
        if mut is None:
            table.append({"call": label, "id": mid, "hit": None, "note": "无此变异体"})
            continue
        # 先把 id → 断言原文 查出来（强制覆盖模式按 id 回，不按 quote）
        idmap = {}
        cf = os.path.join(claimsdir, "claims_%s.json" % mid) if claimsdir else ""
        if cf and os.path.exists(cf):
            for cc in json.load(io.open(cf, encoding="utf-8"))["claims"]:
                idmap[cc["id"]] = cc["text"]
        keys = mut.get("keys") or []

        def blob(i):
            return ((i.get("quote") or "") + " " + idmap.get(i.get("id"), "") + " "
                    + (i.get("reason") or ""))

        hit_items = [i for i in items if keys and any(k in blob(i) for k in keys)]
        bad = [i for i in hit_items if (i.get("verdict") or "") in ("夸大", "不实")]
        table.append({"call": label, "id": mid, "model": d.get("model"),
                      "items": len(items), "hit": bool(hit_items), "hit_n": len(hit_items),
                      "flagged_false": bool(bad),
                      "verdicts": sorted({i.get("verdict") for i in hit_items}),
                      "note": (hit_items[0].get("reason", "")[:120] if hit_items else "未提及该句")})
    ok = [t for t in table if t["id"] != "M0"]
    flagged = [t for t in ok if t.get("flagged_false")]
    print("灵敏度：注入 %d 条假主张，被判“不实/夸大” %d 条" % (len(ok), len(flagged)))
    for t in table:
        print("  %-22s %-3s 命中=%-5s 判假=%-5s %s" % (t["call"], t["id"], t.get("hit"), t.get("flagged_false"), t.get("note")))
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--outdir", default="runs/mutants")
    ap.add_argument("--judge", nargs="?", const="", default=None)
    ap.add_argument("--call", nargs="*", default=[])
    ap.add_argument("--claimsdir", default="")
    a = ap.parse_args()
    if a.src:
        build(a.src, a.outdir)
    if a.judge is not None:
        t = judge(a.judge, a.call, a.claimsdir)
        json.dump(t, io.open(os.path.join(a.judge, "sensitivity.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    return 0 if a.src else 0


if __name__ == "__main__":
    sys.exit(main())
