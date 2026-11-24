#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一次运行的结果导出成三种外人能直接消费的形态。

为什么单独一个文件：`run.py` 负责"跑"，这里负责"交出去"。一致性测试台的竞争力不在
跑得多快，而在**结论能不能被别人拿去用**——接进 CI、贴到评审会、被第三方复算哈希。

- `results.junit.xml`：JUnit XML，GitHub Actions / Jenkins / GitLab 直接读取，不需要写适配器
- `report.html`：单文件、无外链、可直接发给人看
- `ATTEST.json` / `ATTEST.md`：本次全部产物的 sha256 + 环境指纹 + 被测仓提交号，
  第三方拿到目录就能复算（对应 CNCF "any end user can confirm by running the identical
  open source application" 的口径）

只依赖标准库。
"""
import hashlib
import html
import json
import os
import platform
import subprocess
import time

VERDICT_TO_JUNIT = {
    "PASS": "pass",
    "INFO": "pass",
    "REFERENCE": "pass",
    "FAIL": "failure",
    "ERROR": "error",
    "TIMEOUT": "error",
    "BLOCKED": "skipped",
    "SKIP": "skipped",
    "WARN": "pass",
}


def _runs():
    """当前环境指纹，写进 attest 与报告页脚。"""
    return {
        "os": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "impl": platform.python_implementation(),
        "node": _node_version(),
    }


def _node_version():
    try:
        out = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10)
        return (out.stdout or "").strip() or None
    except Exception:
        return None


def git_head(path):
    """被测仓提交号：没有 .git 就返回 None（公开 tarball 场景属正常）。"""
    if not path:
        return None
    try:
        out = subprocess.run(["git", "-C", path, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=15)
        if out.returncode == 0:
            return (out.stdout or "").strip() or None
        # 工作树不在 .git 里时，退回读 harness 落在 _env_fingerprint 的 repo_head
    except Exception:
        pass
    return None


def load_cases(out_dir):
    """按组读回每个用例，供 JUnit 与 HTML 使用。返回 {组名: [case...]}。"""
    groups = {}
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith("_results.json"):
            continue
        g = name[: -len("_results.json")]
        try:
            with open(os.path.join(out_dir, name), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        rows = data if isinstance(data, list) else (data.get("results") or data.get("cases") or [])
        if isinstance(rows, list):
            groups[g] = [r for r in rows if isinstance(r, dict)]
    return groups


def write_junit(out_dir, summary, groups):
    """JUnit XML。判词映射：FAIL→failure、ERROR/TIMEOUT→error、BLOCKED/SKIP→skipped，
    其余（PASS/INFO/REFERENCE/WARN）算通过——WARN 的本意是"需要人看一眼"，不是红。"""
    esc = html.escape
    suites = []
    total_tests = total_fail = total_err = total_skip = 0
    for g in summary.get("groups", []):
        cases = groups.get(g["group"], [])
        if not cases:
            # 组坏了但没产出用例：造一条 error 用例，否则 CI 会以为这组全绿
            cases = [{"case": "%s (no results)" % g["group"],
                      "verdict": "ERROR",
                      "note": "组状态 %s，未产出用例；看 run.log" % g.get("status")}]
        body, nf, ne, ns = [], 0, 0, 0
        for c in cases:
            v = str(c.get("verdict") or "INFO").upper()
            kind = VERDICT_TO_JUNIT.get(v, "pass")
            name, note = c.get("case", "(unnamed)"), c.get("note", "")
            nf += kind == "failure"
            ne += kind == "error"
            ns += kind == "skipped"
            ms = c.get("ms")
            t = "%.3f" % (float(ms) / 1000.0) if isinstance(ms, (int, float)) else "0"
            body.append('    <testcase classname="%s" name="%s" time="%s">' % (esc(g["group"]), esc(name), t))
            if kind == "failure":
                body.append('      <failure message="%s"/>' % esc(note[:500]))
            elif kind == "error":
                body.append('      <error message="%s"/>' % esc(note[:500]))
            elif kind == "skipped":
                body.append('      <skipped message="%s"/>' % esc(note[:500]))
            else:
                body.append('      <system-out>%s</system-out>' % esc(note[:500]))
            body.append("    </testcase>")
        n = len(cases)
        total_tests += n
        total_fail += nf
        total_err += ne
        total_skip += ns
        suites.append('\n'.join([
            '  <testsuite name="%s" tests="%d" failures="%d" errors="%d" skipped="%d" time="%.3f">'
            % (esc(g["group"]), n, nf, ne, ns, float(g.get("seconds") or 0)),
            "\n".join(body),
            "  </testsuite>",
        ]))
    xml = "\n".join([
        '<?xml version="1.0" encoding="utf-8"?>',
        '<testsuites name="uibc-bench" tests="%d" failures="%d" errors="%d" skipped="%d">'
        % (total_tests, total_fail, total_err, total_skip),
        "\n".join(suites),
        "</testsuites>",
        "",
    ])
    path = os.path.join(out_dir, "results.junit.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path


CSS = """
body{font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:0;background:#f6f7f9;color:#1b1f24}
.wrap{max-width:1080px;margin:0 auto;padding:28px 22px 60px}
h1{font-size:22px;margin:0 0 6px}h2{font-size:17px;margin:30px 0 10px}
.meta{color:#5b6570;font-size:13px}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 6px}
.card{background:#fff;border:1px solid #e3e6ea;border-radius:8px;padding:10px 14px;min-width:104px}
.card b{display:block;font-size:20px}.card span{color:#5b6570;font-size:12px}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e3e6ea;border-radius:8px;overflow:hidden}
th,td{padding:7px 10px;border-bottom:1px solid #eef0f3;text-align:left;vertical-align:top;font-size:13px}
th{background:#fafbfc;font-weight:600}
tr:last-child td{border-bottom:0}
.ok{color:#1a7f37;font-weight:600}.bad{color:#b42318;font-weight:600}.warn{color:#9a6700;font-weight:600}
.mut{color:#6b7280}
pre{background:#fff;border:1px solid #e3e6ea;border-radius:8px;padding:10px;overflow:auto;font-size:12.5px}
.foot{margin-top:26px;color:#6b7280;font-size:12px}
"""


def _verdict_cell(v):
    cls = {"PASS": "ok", "FAIL": "bad", "ERROR": "bad", "TIMEOUT": "bad",
           "BLOCKED": "mut", "SKIP": "mut", "WARN": "warn", "INFO": "mut", "REFERENCE": "mut"}.get(v, "")
    return '<td class="%s">%s</td>' % (cls, html.escape(v))


def write_html(out_dir, summary, diff, groups, subject_head=None, baseline_name=None):
    esc = html.escape
    env = _runs()
    totals = summary.get("totals") or {}
    cards = "".join(
        '<div class="card"><b>%d</b><span>%s</span></div>' % (totals[k], esc(k))
        for k in ("PASS", "FAIL", "BLOCKED", "SKIP", "REFERENCE", "TIMEOUT") if totals.get(k)
    )
    rows = []
    for g in summary.get("groups", []):
        c = g.get("counts") or {}
        badge = '<td class="%s">%s</td>' % ("ok" if g.get("status") == "ok" else "bad", esc(g.get("status", "")))
        rows.append("<tr><td>%s</td><td>%.1fs</td>%s<td>%s</td></tr>" % (
            esc(g["group"]), float(g.get("seconds") or 0), badge,
            " ".join("%s=%d" % (k, c[k]) for k in ("PASS", "FAIL", "BLOCKED", "SKIP", "REFERENCE", "TIMEOUT") if c.get(k)) or "-"))
    d = diff or {}
    diff_html = ""
    if diff is not None:
        diff_html = "<h2>基线比对</h2><p class='meta'>基线 <code>%s</code>：回归 %d、消失 %d、新增 %d、变化 %d</p>" % (
            esc(baseline_name or "baseline.json"), len(d.get("regress") or []),
            len(d.get("missing") or []), len(d.get("added") or []), len(d.get("changed") or []))
        items = []
        for x in (d.get("regress") or [])[:20]:
            items.append("<li>回归 · %s（%s → %s）</li>" % (
                esc(x.get("case", "")), esc(str(x.get("was", ""))), esc(str(x.get("now", "")))))
        for x in (d.get("missing") or [])[:20]:
            items.append("<li class='mut'>消失 · %s（基线有、本次没产出）</li>" % esc(x))
        if items:
            diff_html += "<ul>" + "".join(items) + "</ul>"

    # 逐组逐条明细
    detail = []
    for g in summary.get("groups", []):
        cases = groups.get(g["group"], [])
        if not cases:
            continue
        trs = []
        for c in cases:
            v = str(c.get("verdict") or "INFO").upper()
            trs.append("<tr>%s<td>%s</td><td class='mut'>%s</td></tr>" % (
                _verdict_cell(v), esc(c.get("case", "")), esc(str(c.get("note", ""))[:400])))
        detail.append("<h2>%s</h2><table><tr><th style='width:88px'>判定</th><th style='width:38%%'>用例</th><th>说明</th></tr>%s</table>"
                      % (esc(g["group"]), "".join(trs)))

    page = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>uibc-bench 实测报告 %(when)s</title><style>%(css)s</style></head><body><div class="wrap">
<h1>uibc-bench 实测报告</h1>
<p class="meta">%(when)s · 被测仓 %(subj)s · 每组超时 %(timeout)ss · 判定词：PASS 通过 / FAIL 被测方缺陷 / BLOCKED 缺前置 / SKIP 本平台不适用 / REFERENCE 引用第三方 / TIMEOUT 超时被杀</p>
<div class="cards">%(cards)s</div>
<h2>分组结果</h2><table><tr><th>组</th><th style="width:80px">用时</th><th style="width:84px">台子状态</th><th>判定统计</th></tr>%(rows)s</table>
<h2>结论怎么读</h2><p class="meta">退出码 0 只表示<b>台子本身正常</b>（每组都有产物、无超时、相对基线无回归）；用例级 FAIL 是被测仓的结论，不等于台子坏了。要判"基线用例消失即失败"，用 <code>--strict</code>。</p>
%(diff)s
%(detail)s
<p class="foot">环境：%(os)s / %(machine)s / Python %(py)s / Node %(node)s。<br>
本文件由 <code>run.py</code> 自动生成，同目录另有 <code>summary.json</code>（机读）、<code>results.junit.xml</code>（CI 用）、
<code>ATTEST.json</code>（产物哈希，供第三方复算）。</p>
</div></body></html>
""" % dict(when=esc(summary.get("when", "")), css=CSS, subj=esc(str(summary.get("subject"))),
           timeout=summary.get("timeout"), cards=cards, rows="".join(rows), diff=diff_html,
           detail="".join(detail), os=esc(env["os"]), machine=esc(env["machine"]),
           py=esc(env["python"]), node=esc(str(env["node"])))
    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_attest(out_dir, summary, subject_head=None, bench_version=None, extra=None):
    """给整份产物做哈希清单。别人拿到目录 → 重算 sha256 → 和清单比，就知道有没有被改过。"""
    files = []
    for root, _dirs, names in os.walk(out_dir):
        for n in sorted(names):
            p = os.path.join(root, n)
            rel = os.path.relpath(p, out_dir).replace(os.sep, "/")
            if rel in ("ATTEST.json", "ATTEST.md"):
                continue
            files.append({"path": rel, "bytes": os.path.getsize(p), "sha256": _sha256(p)})
    files.sort(key=lambda x: x["path"])
    manifest_digest = hashlib.sha256(
        "".join("%s  %s\n" % (f["sha256"], f["path"]) for f in files).encode("utf-8")).hexdigest()
    att = {
        "bench_version": bench_version,
        "platform": _runs(),
        "subject": summary.get("subject"),
        "subject_head": subject_head,
        "when": summary.get("when"),
        "timeout_sec": summary.get("timeout"),
        "totals": summary.get("totals"),
        "manifest_sha256": manifest_digest,
        "files": files,
    }
    if extra:
        att.update(extra)
    with open(os.path.join(out_dir, "ATTEST.json"), "w", encoding="utf-8") as f:
        json.dump(att, f, ensure_ascii=False, indent=1)
    lines = [
        "# 运行存证（ATTEST）",
        "",
        "- 台子版本：%s" % (bench_version or "-"),
        "- 时间：%s" % (summary.get("when") or "-"),
        "- 被测仓：%s（提交 %s）" % (summary.get("subject") or "-", subject_head or "工作树无 .git / 未知"),
        "- 平台：%s / %s / Python %s" % (_runs()["os"], _runs()["machine"], _runs()["python"]),
        "- 判定合计：%s" % json.dumps(summary.get("totals") or {}, ensure_ascii=False),
        "- 清单摘要（manifest_sha256）：`%s`" % manifest_digest,
        "",
        "复算方法：在本目录执行 `sha256sum -c` 等价操作——按下表逐条重算 sha256 与 `manifest_sha256` 比对。",
        "",
        "| 文件 | 字节 | sha256 |",
        "|---|---|---|",
    ]
    for f in files:
        lines.append("| `%s` | %d | `%s` |" % (f["path"], f["bytes"], f["sha256"]))
    with open(os.path.join(out_dir, "ATTEST.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return os.path.join(out_dir, "ATTEST.json"), os.path.join(out_dir, "ATTEST.md"), manifest_digest
