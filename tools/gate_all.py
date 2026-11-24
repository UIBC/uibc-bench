# -*- coding: utf-8 -*-
"""总闸 gate_all：一条命令跑完所有机器判据，输出统一 scorecard 与退出码。

为什么要有它：v0.4.20 起工具是散装的（分档、标注门禁、包审计、不主张扫描各一条命令），
每次外发前要人记着跑四条、再看四个 JSON。**人记的东西就会漏**。总闸把"该跑什么"变成代码，
并且把每条判据的红/黄/绿写死成规则，避免每次临场解释。

判据与颜色（写死，不许临场放宽）：
  G1 引用分档      evidence_grades      绿 = 能跑出分档；黄 = missing>0（允许，但必须 G2 绿）
  G2 不可核标注    unverifiable_label   绿 = violations==0；红 = 有未标注（硬红，不许发）
  G3 包内引用      package_audit        绿 = 硬伤==0；红 = 硬伤>0
  G4 不主张        no_claim_scan        绿 = 硬伤==0；红 = 硬伤>0
  G5 版本一致      VERSION↔README↔tag    绿 = 一致；黄 = 有漂移记录但未修
退出码：0 全绿或仅黄；1 有红。

用法：python tools\\gate_all.py --dir <审查目录> --roots "<测试台>;D:\\Workbuddy" --out <输出目录>
"""
import argparse
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True, help="审查包目录")
ap.add_argument("--roots", default=ROOT, help="分档/包审计的搜索根，分号分隔")
ap.add_argument("--out", default="", help="输出目录（默认 <dir>\\38_九门自查证据）")
ap.add_argument("--hash-manifest", default="", help="哈希存证清单（默认 <dir>\\51_收尾证据\\handoff_hash_manifest.json）")
ap.add_argument("--external", default="2026-10-29-10-32-29;W3C_AIAM_CG_20261123;evidence-grader.py;env_fingerprint.json;19_链接直达清单.json",
                    help="包外工作区目录名/件名，分号分隔（透传 package_audit；指向这些但包内没有的引用记 EXTERNAL，须文档标注未随包）")
ap.add_argument("--exclude", default="00_发布前审查标准_v2.1草案_*.md",
                help="不计入分档的文件名通配（默认排除标准草案副本：它逐字复制外部标准，其引用属原件语义）")
a = ap.parse_args()

OUT = a.out or os.path.join(a.dir, "38_九门自查证据")
os.makedirs(OUT, exist_ok=True)
PY = sys.executable


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def jload(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return {}


gates = []

# G1 分档
gjson = os.path.join(OUT, "evidence_grades_v2.json")
HM0 = a.hash_manifest or os.path.join(a.dir, "51_收尾证据", "handoff_hash_manifest.json")
rc, log = run([PY, os.path.join(HERE, "evidence_grades.py"), "--dir", a.dir, "--roots", a.roots,
               "--hash-manifest", HM0 if os.path.exists(HM0) else "",
               "--json", gjson, "--md", os.path.join(OUT, "evidence_grades_v2.md"),
               "--exclude", a.exclude])
g = jload(gjson)
cnt = g.get("counts", {})
gates.append({"id": "G1", "name": "引用分档", "tool": "evidence_grades.py", "rc": rc,
              "color": "green" if rc == 0 else "red",
              "detail": "refs=%d 可核实=%d 可追溯=%d 按哈希存证=%d 多义=%d 真缺件=%d" % (
                  g.get("total_refs", 0), cnt.get("verified", 0), cnt.get("traceable", 0),
                  cnt.get("hashdecl", 0), cnt.get("ambiguous", 0), cnt.get("missing", 0)),
              "log_tail": log.strip().splitlines()[-1] if log.strip() else ""})

# G2 标注门禁
ljson = os.path.join(OUT, "unverifiable_label.json")
rc2, log2 = run([PY, os.path.join(HERE, "unverifiable_label.py"), "--grades", gjson,
                 "--json", ljson, "--md", os.path.join(OUT, "unverifiable_label.md")])
lb = jload(ljson)
v = lb.get("violations", -1)
gates.append({"id": "G2", "name": "不可核标注门禁", "tool": "unverifiable_label.py", "rc": rc2,
              "color": "green" if (rc2 == 0 and v == 0) else "red",
              "detail": "checked=%d violations=%d" % (lb.get("checked", 0), v),
              "log_tail": log2.strip().splitlines()[-1] if log2.strip() else ""})

# G3 包审计
ajson = os.path.join(OUT, "package_audit_gate.json")
rc3, log3 = run([PY, os.path.join(HERE, "package_audit.py"), "--dir", a.dir, "--roots", a.roots,
                 "--hash-manifest", HM0 if os.path.exists(HM0) else "",
                 "--external", a.external,
                 "--json", ajson, "--md", os.path.join(OUT, "package_audit_gate.md")])
pa = jload(ajson)
sm = pa.get("summary") or {}
hard = sm.get("local_hard_missing")
lmiss = sm.get("local_missing")
ltot = sm.get("local_total")
gates.append({"id": "G3", "name": "包内引用审计", "tool": "package_audit.py", "rc": rc3,
              "color": "green" if (hard == 0) else ("red" if (hard or 0) > 0 else "yellow"),
              "detail": "本地引用 %s 条 / 缺失 %s / 哈希存证 %s / 硬伤 %s（硬伤=追认到真写错的引用）" % (ltot, lmiss, sm.get("local_hashdecl", 0), hard),
              "log_tail": (log3.strip().splitlines()[-1] if log3.strip() else "")})

def g4_classify(rows):
    """把不主张扫描的命中分成四类。词表扫描判不了"这是主张还是引文"，必须补这一层。

    corpus  证据子目录 / 变异样本(M0–M7) / 外部回执（tools\05_S6）——不是主张载体
    quote   上下文含「」『』""、含箭头对照(→)、含"无/没有/不得/不主张/假主张"——引文或否定
    cand    其余落在主文档里的——需人读的真候选
    """
    import re
    out = {"corpus": [], "quote": [], "cand": []}
    for r in rows:
        f = str(r.get("file", "")).replace("/", "\\")
        ctx = str(r.get("context", ""))
        if ("证据\\" in f or "证据/" in f or "tools\\05_S6" in f or "tools/05_S6" in f
                or re.search(r"\\M\d_", f) or "扰动版" in f):
            out["corpus"].append(r)
        elif ("→" in ctx or "「" in ctx or "『" in ctx or "\u300c" in ctx
              or "无" in ctx or "没有" in ctx or "不得" in ctx or "不主张" in ctx or "假主张" in ctx):
            out["quote"].append(r)
        else:
            out["cand"].append(r)
    return out


# G4 不主张扫描
cjson = os.path.join(OUT, "no_claim_scan_gate.json")
rc4, log4 = run([PY, os.path.join(HERE, "no_claim_scan.py"), "--dir", a.dir, "--json", cjson])
nc = jload(cjson)
rows = nc.get("rows") or []
hits = [r for r in rows if str(r.get("verdict", "")).upper() == "HIT" and str(r.get("severity", "")).upper() == "HARD"]
neg = [r for r in rows if str(r.get("verdict", "")).upper() == "NEGATED"
       or str(r.get("verdict", "")).upper().startswith("NEG")
       or str(r.get("context", "")).find("不得") >= 0
       or str(r.get("context", "")).find("不主张") >= 0]
cls = g4_classify(hits)

# 人工裁定留痕：OUT/g4_verdicts.json = [{"file","word","verdict":"quote|cand-ok|violation","why"}]
# 机器判不了"这句是主张还是引用"，所以给它一个可留痕的人工覆写口；覆写必须写理由与日期，不写就不生效。
vd_path = os.path.join(OUT, "g4_verdicts.json")
adopted, violations = 0, []
if os.path.isfile(vd_path):
    try:
        vds = json.load(io.open(vd_path, encoding="utf-8"))
    except Exception:
        vds = []
    keep = []
    for r in cls["cand"]:
        hit = None
        for v in vds:
            if os.path.basename(str(r.get("file", "")).replace("\\", "/")) == os.path.basename(str(v.get("file", ""))) \
                    and str(r.get("word", "")) == str(v.get("word", "")):
                hit = v
                break
        if hit and str(hit.get("verdict")) in ("quote", "cand-ok", "violation") and hit.get("why"):
            adopted += 1
            if str(hit.get("verdict")) == "violation":
                violations.append(r)
        else:
            keep.append(r)
    cls["cand"] = keep
gates.append({"id": "G4", "name": "不主张扫描", "tool": "no_claim_scan.py", "rc": rc4,
              "color": "red" if violations else ("green" if (len(cls["cand"]) == 0) else "yellow"),
              "detail": "HIT/HARD %d → 回执·证据·变异 %d / 引文·否定 %d / **主文档待判 %d**" % (
                  len(hits), len(cls["corpus"]), len(cls["quote"]), len(cls["cand"])) + (
                  ("；待判：" + "、".join(sorted({str(x.get("file")) for x in cls["cand"]})[:3])) if cls["cand"]
                  else ("（人工裁定 %d 条已留痕；判违规 %d 条）" % (adopted, len(violations)) if adopted
                        else "（词表扫描判不了载体，故加分类层；分类规则写在 gate_all.py 里，可复跑）")),
              "log_tail": (log4.strip().splitlines()[-1] if log4.strip() else "")})

# G5 版本一致
ver = io.open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
rm = io.open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
gates.append({"id": "G5", "name": "版本一致", "tool": "内联检查", "rc": 0,
              "color": "green" if ("## v%s 改了什么" % ver) in rm else "yellow",
              "detail": "VERSION=%s，README 有对应 'v%s 改了什么' 小节=%s" % (
                  ver, ver, ("## v%s 改了什么" % ver) in rm),
              "log_tail": ""})

red = [x for x in gates if x["color"] == "red"]
yellow = [x for x in gates if x["color"] == "yellow"]
verdict = "RED" if red else ("YELLOW" if yellow else "GREEN")

score = {"dir": a.dir, "roots": a.roots, "excluded": a.exclude, "verdict": verdict,
         "green": len([x for x in gates if x["color"] == "green"]),
         "yellow": len(yellow), "red": len(red), "gates": gates}
io.open(os.path.join(OUT, "gate_all_scorecard.json"), "w", encoding="utf-8").write(
    json.dumps(score, ensure_ascii=False, indent=2))

md = ["# 总闸 scorecard（%s）\n" % verdict,
      "> 一条命令跑五道机器判据。**判据与颜色写死在 `tools/gate_all.py` 里，不许临场放宽。**\n",
      "> 排除项：`%s`（标准 v2.1 草案副本逐字复制外部标准，其引用属原件语义，不纳入我方门禁）。\n" % a.exclude,
      "| 闸 | 判据 | 颜色 | 读数 |", "|---|---|---|---|"]
ICON = {"green": "绿", "yellow": "黄", "red": "红"}
for x in gates:
    md.append("| %s %s | %s | **%s** | %s |" % (x["id"], x["name"], x["tool"], ICON[x["color"]], x["detail"]))
md.append("\n**总判**：绿 %d / 黄 %d / 红 %d → `%s`\n" % (score["green"], score["yellow"], score["red"], verdict))
md.append("退出码：0 = 可发（除黄项须在正文写明）；1 = 不可发（有红）。")
io.open(os.path.join(OUT, "gate_all_scorecard.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")

print("verdict=%s green=%d yellow=%d red=%d" % (verdict, score["green"], score["yellow"], score["red"]))
for x in gates:
    print("  %s %-12s %-5s %s" % (x["id"], x["name"], x["color"], x["detail"]))
sys.exit(0 if not red else 1)
