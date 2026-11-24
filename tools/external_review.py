# -*- coding: utf-8 -*-
"""S6 外部 AI 全量实跑 + S1 专家角色审视断言层（同一次调用链，两个角色分开记）。

纪律（照九门标准 v2 写死，不是可选项）：
  - 只喂**待审正文** + 一手源 URL，不喂我们的结论摘要、不喂看板。
  - 模型必须是**非本方模型**（这里用 siliconflow / DeepSeek-V3），子代理一律不算。
  - 逐句质疑要落到"哪句无法核实 / 缺哪份原文"，不接受"总体不错"。
  - 它说打不开，就记"没审"，不替换成 S4 成果。
  - 明文只在内网用于请求，不落盘、不打印。

用法：
    python tools/external_review.py --files a.md b.md --role s6 --out runs/xxx.json
    python tools/external_review.py --files a.md b.md --role s1 --out runs/yyy.json
"""
import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone

KEY_FILE = r"D:\标准\新建文本文档.txt"
API = "https://api.siliconflow.cn/v1/chat/completions"
MODEL = "deepseek-ai/DeepSeek-V3"

SYS = {
    "s6": """你是一位极其挑剔的外部评审，任务是逐句质疑一份发布前审查文档。
只依据文档正文与它给出的链接，不得替作者补理由，不得因为它自称严谨就放松。
对每一句实质性断言给出判定：可核实 / 无法核实 / 不实 / 夸大，并写明缺哪份原文或哪个数字。
特别注意：自称「全部通过」「没有任何问题」「已符合某规范」这类表述要单独挑战。
输出必须是 JSON 数组，每项字段：quote, verdict, reason, missing_source。
最后追加一项 quote=SUMMARY，字段 verdict 填 overall，reason 写不超过 120 字的总体判断。
""",
    "s1": """你是一位标准/法规方向的专业评审，职责是审视一份文档的断言层（不是文风，不是排版）。
对每条对外断言判断：它有没有可指到的一手源段落、证据层级够不够（自证 / 可复跑 / 第三方）。
输出必须是 JSON 数组，每项字段：assertion, evidence_level(自证|可复跑|第三方|无),
enough(是|否|部分), gap(缺哪份原文或哪个实验), fix(一句话怎么补)。
""",
}

USER_TMPL = """待审正文（全文，未删节）如下，文件：{names}

<<<BEGIN
{body}
END>>>

一手源清单（只给链接，不给结论）：
{sources}

请按系统提示的字段输出 JSON 数组，不要输出任何额外解释。"""


def load_key():
    raw = open(KEY_FILE, encoding="utf-8", errors="replace").read()
    toks = re.findall(r"[A-Za-z0-9_\-]{30,}", raw)
    if not toks:
        sys.exit("找不到 API key（文件里没有 30 字符以上的 token）")
    return max(toks, key=len)


def _fix_escapes(s):
    r"""模型常把 Windows 路径写成 `\evidence`（非法转义），先把非法反斜杠双写再解析。
    注意要成对吞掉合法的 `\\`，否则第二个反斜杠会被误当转义引导符（本工具第一版就栽在这）。"""
    valid = '"\\/bfnrtu'
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            nxt = s[i + 1] if i + 1 < n else ""
            if nxt == "\\":
                out.append("\\\\")
                i += 2
                continue
            if nxt and nxt not in valid:
                out.append("\\\\")
                i += 1
                continue
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def repair(content):
    """容忍被截断的 JSON 数组 + 非法转义：截到最后一个完整对象再补右括号。宁可少几条，不许整轮作废。"""
    s = re.sub(r"^```(json)?|```$", "", (content or "").strip(), flags=re.M).strip()
    for cand in (s, _fix_escapes(s)):
        try:
            return json.loads(cand), False
        except Exception:
            pass
    i = s.rfind("},")
    if i > 0:
        try:
            return json.loads(_fix_escapes(s[:i + 1] + "]")), True
        except Exception:
            pass
    i = s.rfind("}")
    if i > 0:
        try:
            return json.loads(_fix_escapes(s[:i + 1] + "]")), True
        except Exception:
            return None, False
    return None, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="+", required=True)
    ap.add_argument("--role", choices=["s6", "s1"], required=True)
    ap.add_argument("--sources", default="")
    ap.add_argument("--model", default=MODEL, help="可换厂商（对照实验用 Qwen3-32B / Kimi-K2.6）")
    ap.add_argument("--evidence", default="",
                    help="证据包 JSON（tools/evidence_pack.py 生成）；给了它=让评审方看到文件原文")
    ap.add_argument("--claims", default="",
                    help="断言清单 JSON（tools/claim_inventory.py 生成）；给了它=强制逐条覆盖")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()

    parts, names = [], []
    for f in a.files:
        parts.append(open(f, encoding="utf-8").read())
        names.append(os.path.basename(f))
    body = "\n\n".join(parts)
    src = a.sources or (
        "https://w3c.github.io/did-resolution/（ED，正文哈希见 39 号）\n"
        "https://www.w3.org/TR/did-core/\n"
        "https://github.com/w3c/did-resolution-test-suite @ 4b5a62e3019fa4f2e90c9b8c0e59d249b67eac10\n"
        "https://github.com/zhaoxinghua09-cell/uibc-core @ da0dc9be5b38f7c0515d5f4fec6e2fe64f1aef5a"
    )
    prompt = USER_TMPL.format(names="、".join(names), body=body, sources=src)
    if a.evidence:
        ev = json.load(open(a.evidence, encoding="utf-8"))
        blocks = []
        for gate, items in ev["gates"].items():
            for it in items:
                blocks.append("【%s】%s\n%s" % (gate, it["path"], it["excerpt"]))
        prompt += ("\n\n以下是一手证据的原文节选（未加工、未简化，就是包内文件的内容）：\n\n"
                   "<<<EVIDENCE\n" + "\n\n".join(blocks) + "\nEVIDENCE>>>\n\n"
                   "有了这些原件，请重新判定每一条：可核实=你在上面的节选里找到了对应记录；"
                   "无法核实=节选里确实没有。不要因为它自称有就判可核实，也不要因为节选被截断就判不实。")
    if a.claims:
        inv = json.load(open(a.claims, encoding="utf-8"))
        lines = []
        for c in inv["claims"]:
            lines.append("%s\t%s" % (c["id"], c["text"]))
        prompt += ("\n\n下面是本包正文的**编号断言清单**（共 %d 条），请**逐条**判定，不得跳过、不得只看表格：\n\n"
                   "<<<CLAIMS\n" % len(inv["claims"]) + "\n".join(lines) + "\nCLAIMS>>>\n\n"
                   "输出 JSON 数组，每项字段：id（照抄清单里的编号）、verdict（可核实/部分核实/无法核实/不实/夸大）、\n"
                   "reason、missing_source。清单里每一条都必须出现一次；你另外发现的、清单没列的问题，用 id=EXTRA-1、EXTRA-2 追加。")
    payload = {"model": a.model, "temperature": 0, "max_tokens": a.max_tokens,
               "messages": [{"role": "system", "content": SYS[a.role]},
                            {"role": "user", "content": prompt}]}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API, data=data,
                                 headers={"Authorization": "Bearer " + load_key(),
                                          "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=a.timeout, context=ssl.create_default_context()) as r:
            resp = json.loads(r.read().decode("utf-8"))
        content = resp["choices"][0]["message"]["content"]
        usage = resp.get("usage", {})
        status = "OK"
    except Exception as e:
        content, usage, status = "", {}, "ERR %s: %s" % (type(e).__name__, e)
    dt = round(time.time() - t0, 1)

    items, repaired = repair(content)

    coverage = None
    if a.claims:
        ids = [c["id"] for c in json.load(open(a.claims, encoding="utf-8"))["claims"]]
        got = {i.get("id") for i in (items or [])}
        coverage = {"expected": len(ids), "returned": len([x for x in ids if x in got]),
                    "missing_ids": [x for x in ids if x not in got][:10],
                    "extra": len([x for x in got if str(x).startswith("EXTRA")])}
    rec = {"role": a.role, "model": a.model, "endpoint": API, "status": status,
           "evidence_pack": os.path.basename(a.evidence) if a.evidence else "",
           "claims": os.path.basename(a.claims) if a.claims else "", "coverage": coverage,
           "item_count_before_repair": repaired,
           "time": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
           "elapsed_s": dt, "usage": usage,
           "files": names, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest().upper(),
           "prompt_chars": len(prompt),
           "items": items, "raw": content}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    json.dump(rec, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("status=%s elapsed=%ss usage=%s" % (status, dt, usage))
    if items:
        print("解析到 %d 条" % len(items))
        for it in items[:12]:
            print("-", json.dumps(it, ensure_ascii=False)[:160])
    else:
        print("未能解析为 JSON，原始前 300 字：")
        print(content[:300])
    print("json=%s" % a.out)
    return 0 if status == "OK" and items else 1


if __name__ == "__main__":
    sys.exit(main())
