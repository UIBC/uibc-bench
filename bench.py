# -*- coding: utf-8 -*-
"""测试台统一入口（基础设施版）。

设计目标：任何人拿到这个目录，一条命令就能跑；结果格式固定，便于比对与对外反馈。

  python bench.py list                      列出所有场景组与用例数
  python bench.py run [--only s01,s03] [--out runs/latest]
  python bench.py run --tag nightly         打标签，便于按批次归档
  python bench.py report <runDir>            生成可视化看板 summary.html
  python bench.py diff <runDirA> <runDirB>   两次运行逐用例比对
  python bench.py issues [--severity high]   导出缺陷台账（给人看/给信通院反馈）
  python bench.py verify-results <runDir>    按 results.schema.json 校验结果合法性

只依赖标准库；Python >= 3.10；Windows / Linux / macOS 同一套代码。
"""
import argparse, json, os, re, subprocess, sys, time, hashlib, html

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "harness")
KIT = HERE
VERDICTS = ("PASS", "FAIL", "WARN", "INFO", "BLOCKED", "ERROR")


# ---------------- 发现 ----------------
def discover():
    out = []
    for name in sorted(os.listdir(HARNESS)):
        if re.match(r"^s\d{2}[a-z]?_.*\.py$", name):
            out.append(dict(file=name, key=name.split("_")[0], path=os.path.join(HARNESS, name)))
    return out


def pyexe():
    v = os.path.join(KIT, ".venv", "Scripts", "python.exe")
    if os.path.exists(v):
        return v
    v2 = os.path.join(KIT, ".venv", "bin", "python")
    return v2 if os.path.exists(v2) else sys.executable


# ---------------- 运行 ----------------
def repo_problem():
    """仓库体检：缺 → 提示克隆；是符号链接 → 明确拒绝。

    为什么拒绝 symlink（2026-11-23 云主机实测）：
    被测仓库有一条 outsider_audit 用例，要求"审计必须由本仓代码裁决"，
    它会核对验证器文件是否来自仓内真实路径。符号链接会让模块路径与仓库
    realpath 不一致，从而被判成"外部注入"直接 exit=1。
    这不是对方苛刻，而是它在防"用别处代码冒充自审"——所以我们先自己守住。
    """
    repo = os.path.join(KIT, "uibc-core-public")
    if not os.path.exists(repo):
        return "MISSING"
    if os.path.islink(repo):
        return "SYMLINK"
    # Windows 还有"目录联接"(junction)，os.path.islink 对它返回 False，单独判
    if hasattr(os.path, "isjunction") and os.path.isjunction(repo):
        return "SYMLINK"
    return None


def cmd_run(args):
    tag = args.tag or "run"
    # 分发包不含被测仓库：依赖仓库的组先体检，缺仓库整组报 BLOCKED（附命令），不产生一堆 ERROR
    problem = repo_problem()
    repo_ok = problem is None
    NEEDS_REPO = {"s03", "s04", "s05", "s06", "s07"}
    run_dir = args.out or os.path.join(KIT, "runs", time.strftime("%Y%m%d_%H%M%S") + "_" + tag)
    os.makedirs(run_dir, exist_ok=True)
    groups = discover()
    if args.only:
        want = {w.strip().lower() for w in args.only.split(",")}
        groups = [g for g in groups if any(g["key"].lower().startswith(w) for w in want)]
    if not groups:
        print("没有匹配的场景组"); return 2
    logp = os.path.join(run_dir, "run.log")
    summary = dict(run=os.path.basename(run_dir), tag=tag,
                   started=time.strftime("%Y-%m-%dT%H:%M:%S"), python=pyexe(),
                   env=dict(platform=sys.platform, host=os.environ.get("COMPUTERNAME", "")),
                   groups=[], counts={}, schema="results.schema.json")
    with open(logp, "a", encoding="utf-8") as log:
        for g in groups:
            outp = os.path.join(run_dir, g["key"] + "_results.json")
            print("\n▶ %s" % g["file"])
            if g["key"] in NEEDS_REPO and not repo_ok:
                if problem == "SYMLINK":
                    msg = ("BLOCKED：uibc-core-public 是符号链接。被测仓库的自审计要求验证器来自仓内真实路径，"
                           "链接会被判为外部注入而拒绝（我们实测过：exit=1）。请用真实克隆："
                           "删除链接后执行 ./setup.ps1（或 git clone 到该目录）。")
                else:
                    msg = "BLOCKED：未找到 uibc-core-public，先执行 .\\setup.ps1 克隆被测仓库（依赖仓库的用例本组跳过）"
                print(msg)
                with open(outp, "w", encoding="utf-8") as f:
                    json.dump([dict(case="%s（整组）" % g["key"], verdict="BLOCKED", note=msg, extra={})],
                              f, ensure_ascii=False, indent=1)
                summary["groups"].append(dict(group=g["key"], file=g["file"], seconds=0, ok=False,
                                              counts={"BLOCKED": 1}, blocked=True))
                summary["counts"]["BLOCKED"] = summary["counts"].get("BLOCKED", 0) + 1
                log.write("\n=== %s BLOCKED (缺仓库) ===\n" % g["file"])
                continue
            t0 = time.time()
            p = subprocess.run([pyexe(), g["path"], outp], cwd=KIT,
                               capture_output=True, text=True, timeout=args.timeout)
            dur = time.time() - t0
            log.write("\n=== %s (%.1fs) ===\n%s\n%s\n" % (g["file"], dur, p.stdout, p.stderr))
            print(p.stdout.strip()[-1500:] if p.stdout else "(无输出)")
            row = dict(group=g["key"], file=g["file"], seconds=round(dur, 1),
                       ok=bool(p.returncode == 0 and os.path.exists(outp)),
                       counts={})
            if p.returncode != 0:
                print("[!] 退出码 %s\n%s" % (p.returncode, p.stderr.strip()[-400:]))
            if os.path.exists(outp):
                with open(outp, encoding="utf-8") as f:
                    items = json.load(f)
                c = {}
                for it in items:
                    c[it.get("verdict", "?")] = c.get(it.get("verdict", "?"), 0) + 1
                row["counts"] = c
                for k, v in c.items():
                    summary["counts"][k] = summary["counts"].get(k, 0) + v
            summary["groups"].append(row)
    summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    cmd_report(run_dir, auto=True)
    print("\n结果目录：%s" % run_dir)
    return 0


# ---------------- 收集 ----------------
def load_cases(run_dir):
    cases = []
    for name in sorted(os.listdir(run_dir)):
        if name.endswith("_results.json"):
            with open(os.path.join(run_dir, name), encoding="utf-8") as f:
                for it in json.load(f):
                    it["group"] = name.replace("_results.json", "")
                    cases.append(it)
    return cases


# ---------------- 报告 ----------------
CSS = """
:root{--bg:#0f1216;--card:#171c22;--line:#2a323c;--txt:#e6ebf2;--dim:#8f9bab;
--pass:#3ddc84;--fail:#ff5d5d;--warn:#ffb84d;--info:#6cb6ff;--blocked:#a98bff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:24px;margin:0 0 6px}h2{font-size:16px;margin:32px 0 12px;color:#c9d4e2}
.sub{color:var(--dim);font-size:13px;margin-bottom:24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .n{font-size:26px;font-weight:600;line-height:1.2}.card .l{color:var(--dim);font-size:12px;margin-top:4px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:9px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line);font-size:13px}
th{color:var(--dim);font-weight:500;background:#1b2129}
tr:last-child td{border-bottom:0}
td.case{width:34%}td.note{color:#c2ccd9}
.v{display:inline-block;min-width:62px;text-align:center;border-radius:6px;padding:1px 8px;font:600 11px/18px ui-monospace,monospace}
.PASS{background:rgba(61,220,132,.14);color:var(--pass)}.FAIL{background:rgba(255,93,93,.16);color:var(--fail)}
.WARN{background:rgba(255,184,77,.16);color:var(--warn)}.INFO{background:rgba(108,182,255,.14);color:var(--info)}
.BLOCKED{background:rgba(169,139,255,.16);color:var(--blocked)}.ERROR{background:#333;color:#aaa}
.bar{height:6px;border-radius:4px;background:#222a33;overflow:hidden;margin-top:10px}
.bar span{display:block;height:100%}
code{background:#12161b;border:1px solid var(--line);padding:1px 5px;border-radius:4px;font-size:12px}
.foot{margin-top:36px;color:var(--dim);font-size:12px}
"""


def cmd_report(run_dir, auto=False):
    cases = load_cases(run_dir)
    counts = {}
    for c in cases:
        counts[c.get("verdict", "?")] = counts.get(c.get("verdict", "?"), 0) + 1
    total = sum(counts.values())
    summ = {}
    sp = os.path.join(run_dir, "summary.json")
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            summ = json.load(f)
    rows = []
    for c in cases:
        ex = c.get("extra") or {}
        tags = []
        if ex.get("kind"):
            tags.append("类别：%s" % ex["kind"])
        if ex.get("severity"):
            tags.append("严重度：%s" % ex["severity"])
        note = html.escape(c.get("note", ""))
        rows.append("<tr><td class='case'><code>%s</code> %s</td><td><span class='v %s'>%s</span></td>"
                    "<td class='note'>%s%s</td></tr>" % (
                        html.escape(c.get("group", "")), html.escape(c.get("case", "")),
                        c.get("verdict", ""), c.get("verdict", ""), note,
                        ("<br><span style='color:#8f9bab'>" + html.escape(" · ".join(tags)) + "</span>") if tags else ""))
    color = dict(PASS="#3ddc84", FAIL="#ff5d5d", WARN="#ffb84d", INFO="#6cb6ff", BLOCKED="#a98bff", ERROR="#555")
    cards = "".join("<div class='card'><div class='n' style='color:%s'>%d</div><div class='l'>%s</div></div>"
                    % (color.get(k, "#ccc"), counts[k], k) for k in VERDICTS if k in counts)
    segs = "".join("<span style='width:%.2f%%;background:%s'></span>" % (counts[k] * 100.0 / max(total, 1), color[k])
                   for k in VERDICTS if k in counts)
    groups = "".join("<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        g["group"], "<span class='v %s'>%s</span>" % ("PASS" if g["ok"] else "FAIL", "OK" if g["ok"] else "中断"),
        g["seconds"], html.escape(json.dumps(g["counts"], ensure_ascii=False)))
        for g in summ.get("groups", []))
    title = "实测台结果 %s" % os.path.basename(run_dir)
    doc = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{title}</title><style>{css}</style></head><body><div class="wrap">
<h1>{title}</h1>
<div class="sub">生成于 {now} · 用例 {total} 条 · 环境 {host} / {plat} · 入口 <code>bench.py</code></div>
<div class="cards">{cards}</div><div class="bar">{segs}</div>
<h2>场景组</h2><table><tr><th>组</th><th>状态</th><th>用时(s)</th><th>判定分布</th></tr>{groups}</table>
<h2>逐条结果</h2><table><tr><th>用例</th><th>判定</th><th>说明</th></tr>{rows}</table>
<div class="foot">判定含义：PASS 通过 · FAIL 被测方问题 · WARN 需人工判断 · INFO 观测值 · BLOCKED 环境缺失 · ERROR 脚本自身出错。
本页由 <code>bench.py report</code> 生成，单文件自包含，可直接归档或发人。</div>
</div></body></html>""".format(title=title, css=CSS, now=time.strftime("%Y-%m-%d %H:%M"),
                             total=total, host=html.escape(str(summ.get("env", {}).get("host", ""))),
                             plat=html.escape(str(summ.get("env", {}).get("platform", ""))),
                             cards=cards, segs=segs, groups=groups, rows="".join(rows))
    outp = os.path.join(run_dir, "summary.html")
    with open(outp, "w", encoding="utf-8") as f:
        f.write(doc)
    print("看板：%s" % outp)
    return 0


# ---------------- 比对 ----------------
def cmd_diff(a, b):
    ca, cb = {(c["group"], c["case"]): c for c in load_cases(a)}, {(c["group"], c["case"]): c for c in load_cases(b)}
    regress, fixed, added, missing = [], [], [], []
    for k, v in cb.items():
        if k not in ca:
            added.append((k, v))
        elif ca[k]["verdict"] != v["verdict"]:
            (regress if v["verdict"] in ("FAIL", "ERROR") and ca[k]["verdict"] in ("PASS", "INFO", "WARN") else fixed).append((k, ca[k]["verdict"], v["verdict"]))
    for k in ca:
        if k not in cb:
            missing.append(k)
    print("A=%s  B=%s" % (a, b))
    print("新增 %d · 回归 %d · 变化 %d · 消失 %d" % (len(added), len(regress), len(fixed), len(missing)))
    for k, x, y in regress:
        print("  [回归] %s / %s : %s -> %s" % (k[0], k[1], x, y))
    for k, x, y in fixed:
        print("  [变化] %s / %s : %s -> %s" % (k[0], k[1], x, y))
    for k in missing:
        print("  [消失] %s / %s（用例不再产出，须解释）" % k)
    for k, v in added:
        print("  [新增] %s / %s %s" % (k[0], k[1], v["verdict"]))
    return 1 if regress else 0


# ---------------- 台账 ----------------
def cmd_issues(args):
    out = []
    for g in discover():
        pass
    # 从最近一次或指定 run 汇总 FAIL/WARN
    runs_root = os.path.join(KIT, "runs")
    dirs = sorted([os.path.join(runs_root, d) for d in os.listdir(runs_root)
                   if os.path.isdir(os.path.join(runs_root, d))]) if os.path.isdir(runs_root) else []
    run_dir = args.run or (dirs[-1] if dirs else None)
    if not run_dir or not os.path.isdir(run_dir):
        print("没有可用的运行结果"); return 2
    for c in load_cases(run_dir):
        if c.get("verdict") not in ("FAIL", "WARN"):
            continue
        ex = c.get("extra") or {}
        sev = ex.get("severity") or {"FAIL": "待定", "WARN": "待定"}[c["verdict"]]
        if args.severity and sev != args.severity:
            continue
        out.append(dict(case=c.get("case"), group=c.get("group"), verdict=c.get("verdict"),
                        severity=sev, kind=ex.get("kind", ""), note=c.get("note", "")))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


# ---------------- 校验 ----------------
def cmd_verify(run_dir):
    schema_path = os.path.join(KIT, "results.schema.json")
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    allowed = set(schema["items"]["properties"]["verdict"]["enum"])
    required = schema["items"]["required"]
    bad = []
    for c in load_cases(run_dir):
        for req in required:
            if req not in c:
                bad.append("%s: 缺字段 %s" % (c.get("case"), req))
        if c.get("verdict") not in allowed:
            bad.append("%s: 非法判定 %r" % (c.get("case"), c.get("verdict")))
    print("校验 %d 条，问题 %d 条" % (len(load_cases(run_dir)), len(bad)))
    for b in bad[:20]:
        print("  -", b)
    return 1 if bad else 0


# ---------------- 趋势 ----------------
def cmd_trend(args):
    """跨运行的同一用例热力表 + 每次运行判定分布。给人看"是在变好还是变坏"。"""
    runs_root = os.path.join(KIT, "runs")
    runs = sorted([d for d in os.listdir(runs_root) if os.path.isdir(os.path.join(runs_root, d))])
    if not runs:
        print("还没有历史运行"); return 2
    series, counts = [], {}
    for r in runs:
        cs = load_cases(os.path.join(runs_root, r))
        series.append((r, {(c.get("group"), c.get("case")): c.get("verdict") for c in cs}))
        counts[r] = {}
        for c in cs:
            counts[r][c.get("verdict")] = counts[r].get(c.get("verdict"), 0) + 1
    keys = sorted({k for _, m in series for k in m})
    color = dict(PASS="#3ddc84", FAIL="#ff5d5d", WARN="#ffb84d", INFO="#6cb6ff", BLOCKED="#a98bff", ERROR="#777")
    short = dict(PASS="P", FAIL="F", WARN="W", INFO="I", BLOCKED="B", ERROR="E")

    head = "".join("<th>%s</th>" % r.replace("20261123_", "") for r in runs)
    rows = []
    for k in keys:
        cells = []
        for r, m in series:
            v = m.get(k)
            cells.append("<td class='c'>%s</td>" % ("<span class='v %s'>%s</span>" % (v, short.get(v, "·")) if v else "<span class='none'>·</span>"))
        last = next((m.get(k) for r, m in reversed(series) if k in m), None)
        rows.append("<tr><td class='case'><span class='g'>%s</span> %s</td><td class='c'><span class='v %s'>%s</span></td>%s</tr>"
                    % (html.escape(k[0]), html.escape(k[1]), last or "INFO", last or "-", "".join(cells)))
    bars = []
    for r in runs:
        c = counts[r]
        tot = sum(c.values()) or 1
        seg = "".join("<i style='width:%.1f%%;background:%s'></i>" % (c.get(v, 0) * 100.0 / tot, color[v])
                      for v in VERDICTS if c.get(v))
        bars.append("<div class='run'><div class='rl'>%s<span>%d 条</span></div><div class='barline'>%s</div></div>"
                    % (r.replace("20261123_", "23/"), tot, seg))

    doc = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>实测台趋势</title>
<style>
:root{--bg:#0d1117;--panel:#151b23;--line:#293040;--txt:#e8edf4;--dim:#8b97a8}
body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:36px 20px 70px}
h1{font-size:22px;margin:0 0 6px}.sub{color:var(--dim);font-size:13px;margin-bottom:26px}
h2{font-size:15px;margin:30px 0 12px;color:#c9d4e2}
.run{margin:10px 0}
.rl{display:flex;justify-content:space-between;font:12px ui-monospace,monospace;color:var(--dim);margin-bottom:4px}
.barline{display:flex;height:8px;border-radius:4px;overflow:hidden;background:#202834}
.barline i{display:block;height:100%}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-top:10px}
th,td{padding:7px 9px;border-bottom:1px solid #222a35;font-size:12.5px;text-align:left}
th{background:#1b2129;color:var(--dim);font-weight:500}
td.case{width:34%}td.c{text-align:center;width:52px}
.v{display:inline-block;min-width:20px;border-radius:4px;font:600 11px/18px ui-monospace,monospace}
.PASS{background:rgba(61,220,132,.16);color:#3ddc84}.FAIL{background:rgba(255,93,93,.18);color:#ff5d5d}
.WARN{background:rgba(255,184,77,.18);color:#ffb84d}.INFO{background:rgba(108,182,255,.14);color:#6cb6ff}
.BLOCKED{background:rgba(169,139,255,.16);color:#a98bff}
.none{color:#3a4453}.g{color:#6b7688;font:11px ui-monospace,monospace}
.foot{margin-top:30px;color:#6b7688;font-size:12px}
</style></head><body><div class="wrap">
<h1>实测台 · 跨运行趋势</h1>
<div class="sub">共 @N@ 次运行 · 用例 @C@ 条 · 每行是一个用例，每列是一次运行（P 通过 / F 失败 / W 可疑 / I 观测 / B 受限）</div>
<h2>每次运行的判定分布</h2>@BARS@
<h2>同一用例的历史变化</h2>
<table><tr><th>用例</th><th>最新</th>@HEAD@</tr>@ROWS@</table>
<div class="foot">由 <code>bench.py trend</code> 生成 · 看某两次的具体差异用 <code>bench.py diff A B</code></div>
</div></body></html>"""
    doc = (doc.replace("@N@", str(len(runs))).replace("@C@", str(len(keys)))
           .replace("@BARS@", "".join(bars)).replace("@HEAD@", head).replace("@ROWS@", "".join(rows)))
    outp = os.path.join(runs_root, "trend.html")
    with open(outp, "w", encoding="utf-8") as f:
        f.write(doc)
    print("趋势页：%s（%d 次运行 / %d 条用例）" % (outp, len(runs), len(keys)))
    return 0


def cmd_list(args):
    for g in discover():
        print("%-6s %s" % (g["key"], g["file"]))
    return 0


def main():
    ap = argparse.ArgumentParser(prog="bench.py", description="uibc 实测台统一入口")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run"); r.add_argument("--only"); r.add_argument("--out"); r.add_argument("--tag"); r.add_argument("--timeout", type=int, default=1800)
    p = sub.add_parser("report"); p.add_argument("run")
    d = sub.add_parser("diff"); d.add_argument("a"); d.add_argument("b")
    i = sub.add_parser("issues"); i.add_argument("--run"); i.add_argument("--severity"); i.add_argument("--out")
    v = sub.add_parser("verify-results"); v.add_argument("run")
    t = sub.add_parser("trend")
    a = ap.parse_args()
    if a.cmd == "list": return cmd_list(a)
    if a.cmd == "run": return cmd_run(a)
    if a.cmd == "report": return cmd_report(a.run)
    if a.cmd == "diff": return cmd_diff(a.a, a.b)
    if a.cmd == "issues": return cmd_issues(a)
    if a.cmd == "verify-results": return cmd_verify(a.run)
    if a.cmd == "trend": return cmd_trend(a)


if __name__ == "__main__":
    sys.exit(main())
