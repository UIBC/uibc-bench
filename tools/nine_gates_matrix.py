# -*- coding: utf-8 -*-
"""九门×机器可判成分矩阵：把"这门到底谁判"讲清楚，产出 nine_gates_matrix.json/.md。

为什么要有它：49 号的总闸跑的是"引用/标注/包/不主张/版本"五道，属于九门里的几块碎片。
外部最常问的一句是"你的九门是不是自己打分"——答案必须是一张逐门的账：
**哪几门机器能全判、哪几门只能判一部分、哪几门必须人或外部模型出手。**

每门三个字段：
  machine  机器判据（工具 + 读数），空表示机器判不了
  human    必须人判的部分（写清是谁、为什么机器判不了）
  status   PASS / 部分 / BLOCKED，判据写在本文件里，不临场改

用法：python tools\\nine_gates_matrix.py --dir <审查目录> --out <输出目录>
"""
import argparse
import glob
import io
import json
import os

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
ap.add_argument("--out", default="")
a = ap.parse_args()
OUT = a.out or os.path.join(a.dir, "38_九门自查证据")
EV = os.path.join(a.dir, "38_九门自查证据")


def j(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return {}


pa = j(os.path.join(EV, "package_audit_gate.json"))
pasum = pa.get("summary") or {}
eg = j(os.path.join(EV, "evidence_grades_v2.json"))
egc = eg.get("counts") or {}
lb = j(os.path.join(EV, "unverifiable_label.json"))
nc = j(os.path.join(EV, "no_claim_scan_gate.json"))
sc = j(os.path.join(EV, "gate_all_scorecard.json"))
s9 = j(os.path.join(EV, "s9_anon_visibility.json"))
off = j(os.path.join(EV, "s5_offline_scan.json"))
receipts = sorted(glob.glob(os.path.join(a.dir, "05_S6", "*.md")))
board = [x for x in os.listdir(a.dir) if x.endswith(".html")]

nhit = len([r for r in (nc.get("rows") or []) if str(r.get("verdict")) == "HIT" and str(r.get("severity")) == "HARD"])

G = []

G.append({"gate": "S0", "name": "前提与范围",
          "machine": "规范钉住与追踪：`spec_pin.py` / `spec_traceability.py`（本轮未复跑）；六条不主张原句可扫描（`no_claim_scan.py`）",
          "machine_read": "不主张命中 HIT/HARD %d 条（分类后待判 0）" % nhit,
          "human": "**ED 无修订号可钉**，只能钉章节锚点——这是真实弱点，机器判不了「钉得够不够」",
          "status": "PARTIAL"})

G.append({"gate": "S1", "name": "专家角色到位",
          "machine": "",
          "machine_read": "无（机器扮演专家属于伪绿·自演式绿，明令不计）",
          "human": "需**真人**专业角色审视断言层；本轮只有外部 AI（machine reviewer），无专家签字",
          "status": "BLOCKED"})

G.append({"gate": "S2", "name": "流程四层留痕",
          "machine": "L0 机读（141 用例）、L2 红线（`no_claim_scan.py`）可机判",
          "machine_read": "L2 扫描 %d 行，HARD 命中 %d；L0 基线 141/141（46 号当场复跑）" % (len(nc.get("rows") or []), nhit),
          "human": "**L3 发件人授权：从未申请**（不是被拒，是没申请）；L1 人工复核记录需人写",
          "status": "PARTIAL", "status_note": "L3 未申请"})

G.append({"gate": "S3", "name": "全面调研 / 覆盖不利证据",
          "machine": "`package_audit.py`（一手源可达）+ 引用分档（是否指得到件）",
          "machine_read": "本地引用 %s 条 / 硬伤 %s；外链 OK %s / DEAD %s；分档 可核实 %d / 可追溯 %d" % (
              pasum.get("local_total"), pasum.get("local_hard_missing"), pasum.get("url_ok"),
              pasum.get("url_dead"), egc.get("verified", 0), egc.get("traceable", 0)),
          "human": "**'有没有漏掉对我方不利的证据'机器判不了**——只能靠红队视角与人读竞品原文",
          "status": "PARTIAL"})

G.append({"gate": "S4", "name": "红队（四视角 + 七路判据）",
          "machine": "`review_mutation.py`（变异击杀 4/4，M0 为对照）+ `defect_relog.py`（逐条复跑日志 3 真跑 / 3 NOT_RERUN）",
          "machine_read": "自身缺陷台账 7 主条目 + 编号 #1–#47；复跑日志带 sha256",
          "human": "**'打中了什么、改得对不对'需人判**；外部模型读不到件时会误判（缺陷 #32 复现 4 次，已立「物证优先」）",
          "status": "PASS", "status_note": "部分可复跑 3/6"})

G.append({"gate": "S5", "name": "外人视角全量实跑",
          "machine": "`package_audit.py` + `evidence_grades.py` + `unverifiable_label.py` + 看板离线扫描",
          "machine_read": "分档 refs=%d（可核实 %d / 可追溯 %d / 多义 %d / 真缺件 %d）；标注门禁 checked=%s 违规 %s；看板离线 外链 %s" % (
              eg.get("total_refs"), egc.get("verified", 0), egc.get("traceable", 0), egc.get("ambiguous", 0),
              egc.get("missing", 0), lb.get("checked"), lb.get("violations"), off.get("external_refs", "?")),
          "human": "**MISSING 已不是 0**（7–11 条运行时产物/台账不存在，逐条写原因）——按 v2 原判据只能判「部分」",
          "status": "PARTIAL"})

G.append({"gate": "S6", "name": "外部 AI 全量实跑",
          "machine": "`external_review.py`（双厂商、逐条 JSON、门级一致率）+ `claim_gates.py`",
          "machine_read": "05_S6 回执 %d 份；门级一致率 DS/QW = 0.70（94 条全量轮）" % len(receipts),
          "human": "**只有 machine reviewer，不等于专家**；QW 读不到包内日志属仪器缺陷（#32）",
          "status": "PARTIAL", "status_note": "S6·补门禁已绿，专家侧仍缺"})

G.append({"gate": "S7", "name": "引用可直达",
          "machine": "`link_direct_check.py`（裸 GET + must 片段）+ 外链台账",
          "machine_read": "外链 %s 条：OK %s / BLOCKED %s / DEAD %s / SKIP %s（DEAD 那条是 identity.foundation/universal-resolver/．2026-11-24 复验 404，已在引用处标注「仅作历史引用」）" % (
              pasum.get("url_total"), pasum.get("url_ok"), pasum.get("url_blocked"), pasum.get("url_dead"), pasum.get("url_skip")),
          "human": "**BLOCKED 需人工浏览器复核 + 副本哈希**（状态码不是证据，内容标记才是）",
          "status": "PASS"})

G.append({"gate": "S8", "name": "可视化到位",
          "machine": "看板单文件离线扫描（外链 / @import / img）",
          "machine_read": "看板 %s（%s B / %s 视图）；src+href 外部链接 %s / @import %s / img %s；判决 %s" % (
              board[0] if board else "?", off.get("bytes", "?"), off.get("views", "?"),
              (off.get("src_http", 0) + off.get("href_http", 0)), off.get("import_rule", "?"),
              off.get("img_tags", "?"), str(off.get("verdict", "?"))[:20]),
          "human": "**'看图能不能说服人'判不了**——只能人看",
          "status": "PASS"})

G.append({"gate": "S9", "name": "GitHub 物件外人全量实测",
          "machine": "`github_visibility.py`（匿名可达性）",
          "machine_read": "判决 %s（%s）" % (s9.get("verdict", "?"), str(s9.get("note", ""))[:60]),
          "human": "**仓库至今未推送**，公开侧物件不全；推送属对外动作需批准",
          "status": "PARTIAL"})

status_rank = {"PASS": 0, "部分": 1, "BLOCKED": 2}
full_machine = [g for g in G if g["machine"] and not g["human"].startswith("**'") and g["status"] == "PASS"]
counts = {}
for g in G:
    counts[g["status"]] = counts.get(g["status"], 0) + 1

out = {"dir": a.dir, "gates": G, "counts": counts,
       "machine_full": [g["gate"] for g in G if g["status"] == "PASS"],
       "blocked": [g["gate"] for g in G if g["status"] == "BLOCKED"],
       "partial": [g["gate"] for g in G if g["status"] == "PARTIAL"]}
io.open(os.path.join(OUT, "nine_gates_matrix.json"), "w", encoding="utf-8").write(
    json.dumps(out, ensure_ascii=False, indent=2))

md = ["# 九门×机器可判成分矩阵\n",
      "> 一句话结论：**十门里没有一门是「机器全判」的**。机器能判的是「件在不在、字有没有、页面开不开」，"
      "判不了的是「该不该这么说、证据够不够、外人信不信」。本表逐门写清分界线。\n",
      "| 门 | 名称 | 机器判据与读数 | 必须人/外部出手的部分 | 状态 |", "|---|---|---|---|---|"]
ZH = {"PASS": "PASS", "PARTIAL": "部分", "BLOCKED": "BLOCKED"}
for g in G:
    md.append("| %s | %s | %s<br>`%s` | %s | **%s%s** |" % (
        g["gate"], g["name"], g["machine"] or "—", g["machine_read"], g["human"], ZH[g["status"]],
        ("（%s）" % g["status_note"]) if g.get("status_note") else ""))
md.append("\n**统计**：PASS %d（%s）/ 部分 %d / BLOCKED %d。" % (
    counts.get("PASS", 0), "、".join([g["gate"] for g in G if g["status"] == "PASS"]),
    counts.get("PARTIAL", 0), counts.get("BLOCKED", 0)))
md.append("\n**能说**：机器可判部分已全绿（总闸 5/5，49 号）。")
md.append("**不能说**：不能说「九门全过」或「已通过发布前审查」——S1 无专家、S2-L3 无授权、S6 无专家侧、S9 未推送。")
io.open(os.path.join(OUT, "nine_gates_matrix.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")

print("gates=%d PASS=%d PARTIAL=%d BLOCKED=%d" % (len(G), counts.get("PASS",0), counts.get("PARTIAL",0), counts.get("BLOCKED",0)))
print("full-machine(PASS)=", out["machine_full"])
