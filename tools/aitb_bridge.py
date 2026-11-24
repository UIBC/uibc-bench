# -*- coding: utf-8 -*-
"""AITB 桥：把 UIBC 实测台接成 AITB 的一条 preset（清单在 AITB 的 presets/uibc.json）。

为什么要有这层：AITB（试真台）是统一槽位，它只认四态 PASS/FAIL/SKIP/BLOCKED 与退出码；
本台内部有 PASS/FAIL/WARN/INFO/BLOCKED/SKIP 六态。桥只做两件事——
  1) 把内部结果压成 AITB 能判的一行（含关键数字，供 expect 子串匹配）；
  2) 提供一个负对照（T1）：故意造一条回归，证明比对器真的会红。

子命令：
  full     跑全组 + 与 baseline 逐条比对，输出 RESULT 行
  interop  只跑 I 组互操作，输出 INTEROP 行
  negctl   负对照：伪造一次"有 1 条回归"的运行，比对器必须报 回归>=1 并 exit 1
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(cmd, cwd=KIT, timeout=1200):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def cmd_full(tag):
    rc, out = run([PY, "bench.py", "run", "--tag", tag])
    m = list(re.finditer(r"结果目录：(.+)", out))
    if not m:
        print("AITB:uibc RESULT failed=1 reason=no-run-directory")
        return 2
    rdir = m[-1].group(1).strip()
    rc2, out2 = run([PY, "compare_baseline.py", rdir])
    line = [l for l in out2.splitlines() if l.startswith("基线")]
    # 基线 ... · 本次 N 条 · 一致 X · 回归 R · 变化 C · 新增 A · 消失 M
    nums = {}
    if line:
        for k in ("本次", "一致", "回归", "变化", "新增", "消失"):
            mm = re.search(k + r"\s*(\d+)", line[0])
            nums[k] = int(mm.group(1)) if mm else -1
    counts = {}
    sj = os.path.join(rdir, "summary.json")
    if os.path.exists(sj):
        counts = json.load(open(sj, encoding="utf-8")).get("counts", {})
    print("AITB:uibc RESULT run=%s total=%s consistent=%s regression=%s changed=%s added=%s missing=%s "
          "pass=%s fail=%s warn=%s info=%s skip=%s blocked=%s error=%s bench_rc=%d cmp_rc=%d"
          % (os.path.basename(rdir), nums.get("本次", -1), nums.get("一致", -1), nums.get("回归", -1),
             nums.get("变化", -1), nums.get("新增", -1), nums.get("消失", -1),
             counts.get("PASS", 0), counts.get("FAIL", 0), counts.get("WARN", 0),
             counts.get("INFO", 0), counts.get("SKIP", 0), counts.get("BLOCKED", 0),
             counts.get("ERROR", 0), rc, rc2))
    ok = nums.get("回归", 99) == 0 and nums.get("消失", 99) == 0 and nums.get("一致", 0) > 0
    # AITB 的 expect 只做子串匹配、一条检查一个期望串：这里给一条紧凑的判定行，便于清单侧断言
    print("AITB:uibc VERDICT regression=%s missing=%s consistent=%s error=%s total=%s"
          % (nums.get("回归", -1), nums.get("消失", -1), nums.get("一致", -1),
             counts.get("ERROR", 0), nums.get("本次", -1)))
    return 0 if ok else 1


def cmd_interop():
    rc, out = run([PY, os.path.join("harness", "s09_interop_third_party.py")], timeout=400)
    m = list(re.finditer(r"=== 汇总 (\{.*?\}) ===", out))
    counts = json.loads(m[-1].group(1).replace("'", '"')) if m else {}
    print("AITB:uibc INTEROP pass=%s fail=%s blocked=%s warn=%s info=%s rc=%d"
          % (counts.get("PASS", 0), counts.get("FAIL", 0), counts.get("BLOCKED", 0),
             counts.get("WARN", 0), counts.get("INFO", 0), rc))
    ok = counts.get("PASS", 0) >= 6 and counts.get("FAIL", 0) == 0 and rc == 0
    return 0 if ok else 1


def cmd_negctl():
    """负对照：从基线复制一次运行，把 1 条 PASS 改成 FAIL，比对器必须报回归并 exit 1。"""
    base = json.load(open(os.path.join(KIT, "baseline.json"), encoding="utf-8"))
    cases = base.get("cases", [])
    tmp = tempfile.mkdtemp(prefix="aitb_negctl_")
    try:
        rows, flipped = [], None
        for c in cases:
            v = c["verdict"]
            if flipped is None and v in ("PASS", "INFO"):
                flipped = c["case"]
                v = "FAIL"
            rows.append(dict(case=c["case"], verdict=v, note="负对照：人为翻转", extra={}))
        grp = os.path.join(tmp, "s00_negctl_results.json")
        json.dump(rows, open(grp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        rc, out = run([PY, "compare_baseline.py", tmp], timeout=120)
        m = re.search(r"回归\s*(\d+)", out)
        n = int(m.group(1)) if m else -1
        print("AITB:uibc NEGCTL flipped=%s regression=%d cmp_rc=%d expect_rc=1" % (flipped, n, rc))
        # 这个子命令是"验证比对器会红"的检查器：它自己必须绿（exit 0）才能算这项通过，
        # 红的证据写成 cmp_rc=1 让清单断言；比对器没红则以 2 退出（AITB 记 FAIL）。
        return 0 if (rc == 1 and n >= 1) else 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_last():
    """读最近一次运行目录的 summary，供门禁做轻量复核（不重跑）。"""
    runs = os.path.join(KIT, "runs")
    ds = [os.path.join(runs, d) for d in os.listdir(runs)
          if os.path.isdir(os.path.join(runs, d)) and d[:8].isdigit()]
    if not ds:
        print("AITB:uibc LAST none=1")
        return 2
    d = max(ds, key=os.path.getmtime)
    sj = os.path.join(d, "summary.json")
    counts = json.load(open(sj, encoding="utf-8")).get("counts", {}) if os.path.exists(sj) else {}
    print("AITB:uibc LAST run=%s total=%s error=%s fail=%s pass=%s"
          % (os.path.basename(d), sum(counts.values()), counts.get("ERROR", 0),
             counts.get("FAIL", 0), counts.get("PASS", 0)))
    return 0 if counts.get("ERROR", 0) == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["full", "interop", "negctl", "last"])
    ap.add_argument("--tag", default="aitb")
    a = ap.parse_args()
    sys.exit({"full": lambda: cmd_full(a.tag), "interop": cmd_interop,
              "negctl": cmd_negctl, "last": cmd_last}[a.cmd]())
