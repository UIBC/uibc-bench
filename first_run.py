# -*- coding: utf-8 -*-
"""一键首跑：给完全陌生的人用。

目标（外部评审外人镜唯一未过项）：**30 分钟内**在本机跑出与报告一致的结论，
不需要读文档、不需要懂内部结构。

用法（三选一）：
    python first_run.py              # 默认：快跑（s01/s02b/s03/s07，约 3–6 分钟）
    python first_run.py --full       # 全量（含 s04 全量单测，约 10–20 分钟）
    python first_run.py --no-venv    # 不建虚拟环境，用当前解释器

它做的事只有 5 步，每步都会打印"正在做什么 / 结果"：
    1 体检（python 版本、node、被测仓库是否存在/是否符号链接）
    2 克隆被测仓库（缺则 depth=1；发现符号链接直接拒绝并说明原因）
    3 建虚拟环境并装附加依赖（可选）
    4 跑场景组并落盘
    5 打印一句话结论 + 看板路径
"""
import os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = HERE
REPO = os.path.join(KIT, "uibc-core-public")
URL = "https://github.com/zhaoxinghua09-cell/uibc-core"


def say(msg):
    print("[first-run] %s" % msg, flush=True)


def run(args, cwd=None, timeout=None, check=False):
    p = subprocess.run(args, cwd=cwd or KIT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if check and p.returncode != 0:
        say("命令失败（exit=%s）：%s" % (p.returncode, " ".join(args)))
        print((p.stdout or "")[-600:])
        print((p.stderr or "")[-600:])
        raise SystemExit(1)
    return p


def step1_env():
    say("1/5 体检")
    if sys.version_info < (3, 10):
        say("Python 版本过低：需要 3.10+，当前 %s" % sys.version.split()[0]); raise SystemExit(1)
    say("   python %s (%s)" % (sys.version.split()[0], sys.executable))
    node = shutil_which("node")
    say("   node %s" % ("有" if node else "无（JS 侧用例会记 BLOCKED，不影响其他组）"))
    if os.path.islink(REPO):
        say("   被测仓库目录是符号链接 —— 会被对方自审计拒绝，请删掉链接后重跑")
        raise SystemExit(1)
    say("   仓库：%s" % ("已存在" if os.path.isdir(REPO) else "缺失，下一步克隆"))


def shutil_which(name):
    import shutil
    return shutil.which(name)


def step2_clone():
    say("2/5 取得被测仓库")
    if os.path.isdir(REPO):
        h = run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"]).stdout.strip()
        say("   跳过克隆，HEAD=%s（需要更新请手动 fetch，避免覆盖实测现场）" % h)
        return
    git = shutil_which("git")
    if not git:
        say("   没有 git：请先安装，或手动下载仓库放到 %s" % REPO); raise SystemExit(1)
    say("   克隆 %s（depth=1，约 10–30 秒）" % URL)
    p = run([git, "clone", "--depth", "1", URL, REPO], timeout=600)
    if p.returncode != 0:
        say("   克隆失败（网络？）：%s" % (p.stderr or p.stdout)[-300:]); raise SystemExit(1)
    say("   HEAD=%s" % run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"]).stdout.strip())


def step3_venv(no_venv):
    say("3/5 解释器与依赖")
    if no_venv:
        say("   --no-venv：用当前解释器 %s" % sys.executable)
        return sys.executable
    vdir = os.path.join(KIT, ".venv")
    vpy = os.path.join(vdir, "Scripts", "python.exe") if os.name == "nt" else os.path.join(vdir, "bin", "python")
    if not os.path.exists(vpy):
        say("   建虚拟环境（约 20 秒）")
        run([sys.executable, "-m", "venv", vdir], timeout=300, check=True)
    say("   装附加依赖 verify/test（首次约 1–2 分钟，之后跳过）")
    run([vpy, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         "-e", "%s[verify,test]" % REPO], timeout=1800, check=True)
    say("   venv python %s" % run([vpy, "-c", "import sys;print(sys.version.split()[0])"]).stdout.strip())
    return vpy


def step4_bench(py, full):
    groups = "s01,s02,s02b,s03,s04,s05,s06,s07" if full else "s01,s02b,s03,s07"
    tag = "first_run_full" if full else "first_run_fast"
    say("4/5 跑场景组 %s（%s）" % (groups, "全量，约 10–20 分钟" if full else "快跑，约 3–6 分钟"))
    t0 = time.time()
    p = run([py, os.path.join(KIT, "bench.py"), "run", "--only", groups, "--tag", tag], timeout=3600)
    say("   exit=%s 用时 %.0fs" % (p.returncode, time.time() - t0))
    print((p.stdout or "")[-2500:])
    if p.returncode != 0:
        print((p.stderr or "")[-800:])
    return p.returncode


def step5_verdict():
    say("5/5 结论")
    runs = os.path.join(KIT, "runs")
    if not os.path.isdir(runs):
        say("没有 runs 目录：说明第 4 步没跑成"); return
    latest = sorted([d for d in os.listdir(runs) if os.path.isdir(os.path.join(runs, d))])[-1]
    sp = os.path.join(runs, latest, "summary.json")
    if not os.path.exists(sp):
        say("未找到 %s（可能被中断）" % sp); return
    import json
    s = json.load(open(sp, encoding="utf-8"))
    c = s.get("counts", {})
    say("   本次：%s" % " / ".join("%s=%s" % (k, c[k]) for k in sorted(c)))
    bad = c.get("FAIL", 0)
    say("   %s" % ("存在 FAIL —— 这些是被测方待确认项，不是本台故障" if bad else "无 FAIL"))
    say("   看板：%s" % os.path.join(runs, latest, "summary.html"))
    say("   明细：%s" % os.path.join(runs, latest))


if __name__ == "__main__":
    full = "--full" in sys.argv
    no_venv = "--no-venv" in sys.argv
    t0 = time.time()
    print("=" * 62)
    print("uibc 实测台 · 一键首跑（首次约 5–20 分钟，之后更快）")
    print("=" * 62)
    step1_env()
    step2_clone()
    py = step3_venv(no_venv)
    rc = step4_bench(py, full)
    step5_verdict()
    print("=" * 62)
    print("总用时 %.1f 分钟%s" % ((time.time() - t0) / 60, "" if rc == 0 else "（第 4 步有非零退出，见上）"))
