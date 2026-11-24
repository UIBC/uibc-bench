#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uibc-bench 单一入口：跨平台（Windows / Linux / macOS），带超时，跑完给一张表。

为什么要有这个文件：原先只有 `run_all.ps1`，非 Windows 的人根本进不来；而且它声明了
`-TimeoutSec` 却从未使用，任何一组卡住就整轮不结束——外部使用者第一次跑就会撞上这个。

用法：
    python run.py                      # 全部组
    python run.py --list               # 只列出组，不跑
    python run.py --only s10,s02b      # 指定组（前缀匹配）
    python run.py --quick              # 跳过 s04/s05/s08（最慢、需要网络或特定平台的三组）
    python run.py --subject <dir>      # 指定被测仓（缺省读 $UIBC_SUBJECT，再缺省找 ./uibc-core-public）
    python run.py --timeout 600        # 每组超时秒数（默认 900）

输出：`runs/<时间戳>/` 下每组一份 `<组名>_results.json`、`run.log`、`summary.json`，终端打一张表。
退出码：0 全部有产物且无 FAIL；1 有 FAIL/超时/缺产物；2 前置检查没过（这时一秒内就退出，不让你干等）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _harden_stdio():
    """终端不因为一个字符把整轮跑挂掉。

    2026-11-24 GitHub 的 windows-latest 上真挂过：runner 的控制台是 cp1252，
    一行带 `◀`/中文的输出直接抛 UnicodeEncodeError，整个 job exit 1——
    而同样的代码在本机 cp936 上跑得好好的。这不是"环境怪"，是"没适配"：
    任何人换台机器、换个 locale 就该能跑，所以统一把 stdout/stderr 定成 UTF-8，
    编不出来的字符替换掉，而不是崩。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_harden_stdio()
HARNESS = os.path.join(HERE, "harness")
QUICK_SKIP = ("s04", "s05", "s08")   # 全量套件 / Windows 克隆 / 环境矩阵：慢或挑平台
VERDICTS = ("PASS", "FAIL", "BLOCKED", "REFERENCE", "SKIP", "TIMEOUT")


def platform_slug():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def resolve_baseline(cli_value):
    """基线选择：显式 --baseline > baseline.json（判据只有一份，避免"改判据改出真绿"）。

    平台差异不走"另存一份基线"，而是 `baseline/<平台>.json` 里的 **excludes 补充登记**：
    有些用例本来就只在一个平台产出（Windows 克隆、cp936 编码），在本平台"没产出"是正常现象。
    把它们登记进 excludes，写清理由，就能既不放松判据、又不再刷屏一样的"消失"提示。
    （WPT 的 expectations、Chromium 的 baselines 也是这个思路：差异单独立档，判据不跟着漂。）
    """
    if cli_value:
        return os.path.abspath(cli_value), "--baseline 指定", []
    return os.path.join(HERE, "baseline.json"), "通用基线 baseline.json", platform_excludes()


def platform_excludes():
    """读 baseline/<平台>.json 里的 excludes（没有就返回空列表）。"""
    p = os.path.join(HERE, "baseline", platform_slug() + ".json")
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            return [str(x) for x in (json.load(f).get("excludes") or [])]
    except Exception:
        return []


def say(msg=""):
    print(msg, flush=True)


def discover():
    if not os.path.isdir(HARNESS):
        return []
    items = []
    for name in sorted(os.listdir(HARNESS)):
        if re.match(r"^s\d{2}[a-z]?_", name) and name.endswith(".py"):
            items.append((name[:-3], os.path.join(HARNESS, name)))
    return items


def resolve_subject(cli_value):
    """返回 (路径, 来源说明)。找不到就返回 (None, 原因)。"""
    for cand, src in ((cli_value, "--subject"), (os.environ.get("UIBC_SUBJECT"), "环境变量 UIBC_SUBJECT")):
        if cand:
            if not os.path.isdir(cand):
                return None, "%s 指向的目录不存在：%s" % (src, cand)
            return os.path.abspath(cand), src
    default = os.path.join(HERE, "uibc-core-public")
    if os.path.isdir(default):
        return default, "默认目录 uibc-core-public"
    return None, "没有找到被测仓"


def preflight(args):
    """前置检查：不过就立刻退出，并把下一步写清楚。"""
    problems, notes = [], []

    if sys.version_info < (3, 10):
        problems.append("Python 版本 %d.%d 低于 3.10" % sys.version_info[:2])
    notes.append("python %d.%d.%d" % sys.version_info[:3])

    if not os.path.isdir(HARNESS):
        problems.append("找不到 harness/ 目录，确认在仓根运行本脚本")

    if args.groups:
        subject, src = resolve_subject(args.subject)
        if subject is None:
            problems.append(
                "%s。三条路选一条：\n"
                "    python run.py --subject <uibc-core 目录>\n"
                "    set UIBC_SUBJECT=<uibc-core 目录>        (PowerShell: $env:UIBC_SUBJECT=...)\n"
                "    export UIBC_SUBJECT=<uibc-core 目录>     (bash)\n"
                "  也可以把被测仓克隆成 ./uibc-core-public（git clone --depth 1 <repo> uibc-core-public）" % src)
        else:
            notes.append("被测仓 %s（来源：%s）" % (subject, src))
            if not os.path.isdir(os.path.join(subject, "uibc_core")):
                problems.append("被测仓里没有 uibc_core/ 包：%s" % subject)

    if shutil.which("node") is None:
        notes.append("没装 node：JS 侧校验场景会记 BLOCKED（不影响其余组）")

    if problems:
        say("[preflight] 没过，先解决这几条（不会跑任何一组）：")
        for p in problems:
            say("  ✗ " + p)
        for n in notes:
            say("  · " + n)
        return False, None, None
    for n in notes:
        say("  · " + n)
    return True, resolve_subject(args.subject)[0], None


def counts_from_json(path):
    """优先读结果 json 数判定；读不出来就返回 None，交给输出正则兜底。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    rows = data if isinstance(data, list) else (data.get("results") or data.get("cases") or [])
    if not isinstance(rows, list):
        return None
    c = {}
    for r in rows:
        if isinstance(r, dict):
            v = str(r.get("verdict") or r.get("state") or "").upper()
            if v in VERDICTS:
                c[v] = c.get(v, 0) + 1
    return c or None


def counts_from_text(text):
    c = {}
    for m in re.finditer(r"\[(PASS|FAIL|BLOCKED|REFERENCE|SKIP|TIMEOUT)\]", text):
        c[m.group(1)] = c.get(m.group(1), 0) + 1
    for m in re.finditer(r"'(PASS|FAIL|BLOCKED|REFERENCE|SKIP|TIMEOUT)':\s*(\d+)", text):
        c[m.group(1)] = max(c.get(m.group(1), 0), int(m.group(2)))
    return c or None


def _kill_tree(proc):
    """连孙进程一起杀。Windows 只 kill 子进程会留下 s04 里那层 pytest 继续占 CPU/端口。"""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_group(name, path, out_dir, timeout, subject):
    out_json = os.path.join(out_dir, name + "_results.json")
    env = dict(os.environ)
    # 子进程也一样钉 UTF-8：各组脚本会打印中文和 `◀`，在 cp1252 的控制台上会直接抛
    # UnicodeEncodeError（GitHub windows-latest 上真发生过）。父进程 print 修了不算完，
    # 跑在子进程里的这些组也得修。
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if subject:
        env["UIBC_SUBJECT"] = subject
    cmd = [sys.executable, path, out_json]
    t0 = time.time()
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, cwd=HERE, errors="replace")
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)
        try:
            out, _ = proc.communicate(timeout=timeout)
            elapsed = time.time() - t0
            text = out or ""
            status = "ok" if proc.returncode == 0 else "exit%s" % proc.returncode
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            try:
                out, _ = proc.communicate(timeout=10)
            except Exception:
                out = ""
            elapsed = time.time() - t0
            text = (out or "") + "\n[TIMEOUT] 超过 %ds 被终止（子进程树已一并结束）\n" % timeout
            status = "timeout"
    except Exception as e:
        elapsed = time.time() - t0
        text = "[ERROR] 起子进程失败：%r" % (e,)
        status = "error"

    counts = counts_from_json(out_json) or counts_from_text(text)
    if status == "timeout":
        counts = dict(counts or {})
        if not counts.get("TIMEOUT"):
            counts["TIMEOUT"] = 1
    return dict(group=name, status=status, seconds=round(elapsed, 1),
                counts=counts or {}, json=out_json if os.path.exists(out_json) else None,
                log=text.strip().splitlines()[-12:])


def guided_choice(args):
    """引导模式：不懂参数的人用这个。三条路对应三种真实目的，选完就等于把参数替人填好。"""
    say("uibc-bench 引导模式（直接回车＝默认值）")
    say("  1) 只想确认台子在我这台机上活着       → --quick，约 1 分钟，跳过三组最慢的")
    say("  2) 给被测仓做一次完整体检             → 全量 11 组，约 6–9 分钟")
    say("  3) 只查某一组（比如刚改完 DID 解析）   → 输入组名，如 s02、s10")
    try:
        ans = input("选 1 / 2 / 3 [1]: ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        ans = "1"
    if ans.startswith("2"):
        args.quick = False
        say("[guide] 全量体检")
    elif ans.startswith("3"):
        try:
            name = input("组名（可逗号分隔，--list 可看全量）: ").strip()
        except (EOFError, KeyboardInterrupt):
            name = ""
        args.only = name
        args.quick = False
        say("[guide] 只跑 %s" % (name or "（空，等同全量）"))
    else:
        args.quick = True
        say("[guide] 快速体检（--quick）")
    return args


def main():
    ap = argparse.ArgumentParser(add_help=True, description="uibc-bench 单一入口")
    ap.add_argument("--list", action="store_true", help="只列出场景组")
    ap.add_argument("--only", default="", help="逗号分隔的组名前缀，如 s10,s02b")
    ap.add_argument("--quick", action="store_true", help="跳过 s04/s05/s08")
    ap.add_argument("--subject", default="", help="被测仓目录（uibc-core 工作树）")
    ap.add_argument("--timeout", type=int, default=900, help="每组超时秒数，默认 900")
    ap.add_argument("--out", default="", help="输出目录（默认 runs/<时间戳>）")
    ap.add_argument("--no-baseline", action="store_true", help="跑完不做基线比对")
    ap.add_argument("--strict", action="store_true",
                    help="发布前自查用：基线里的用例本次没产出也算失败（换平台会误报，平时别开）")
    ap.add_argument("--update-baseline", action="store_true",
                    help="用本次结果刷新基线；刷新的是本平台文件 baseline/<平台>.json，不动通用基线")
    ap.add_argument("--baseline", default="", help="基线文件（默认优先 baseline/<平台>.json，再退回 baseline.json）")
    ap.add_argument("--no-junit", action="store_true", help="不写 results.junit.xml（CI 用文件）")
    ap.add_argument("--no-html", action="store_true", help="不写 report.html（人看文件）")
    ap.add_argument("--attest", action="store_true",
                    help="额外写 ATTEST.json / ATTEST.md：本次全部产物的 sha256 清单 + 环境指纹，供第三方复算")
    ap.add_argument("--guide", action="store_true", help="引导模式：三个问题替你选好要跑的组")
    args = ap.parse_args()

    if args.guide:
        args = guided_choice(args)

    groups = discover()
    if not groups:
        say("harness/ 里没有 s*.py，确认在仓根运行")
        return 2

    if args.list:
        say("共 %d 组：" % len(groups))
        for name, path in groups:
            note = "（--quick 会跳过）" if name.split("_")[0] in QUICK_SKIP else ""
            say("  %-40s %s%s" % (name, os.path.relpath(path, HERE), note))
        return 0

    if args.only:
        want = [w.strip().lower() for w in args.only.split(",") if w.strip()]
        picked = [(n, p) for n, p in groups if any(n.lower().startswith(w) for w in want)]
        if not picked:
            say("[run] --only=%s 没匹配到任何组；用 --list 看组名" % args.only)
            return 2
    else:
        picked = [(n, p) for n, p in groups if not (args.quick and n.split("_")[0] in QUICK_SKIP)]

    say("[run] 本次 %d 组，每组超时 %ds%s" % (len(picked), args.timeout, "，quick 模式" if args.quick else ""))
    ok, subject, _ = preflight(argparse.Namespace(groups=picked, subject=args.subject))
    if not ok:
        return 2

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = args.out or os.path.join(HERE, "runs", ts)
    os.makedirs(out_dir, exist_ok=True)
    say("[run] 输出目录 %s\n" % out_dir)

    results = []
    for name, path in picked:
        say("[run] ▶ %s" % name)
        r = run_group(name, path, out_dir, args.timeout, subject)
        results.append(r)
        c = r["counts"]
        headline = " ".join("%s=%d" % (k, c[k]) for k in VERDICTS if c.get(k)) or "无判定输出"
        say("[run] ◀ %-38s %6.1fs  %-10s %s" % (name, r["seconds"], r["status"], headline))
        if r["status"] != "ok" or c.get("FAIL") or c.get("BLOCKED") or c.get("TIMEOUT"):
            for line in r["log"][-6:]:
                say("      | " + line)
        say()

    # 基线比对（有就打，没有就明说）
    diff = None
    baseline_path, baseline_why, baseline_excludes = resolve_baseline(args.baseline)
    if not args.no_baseline and os.path.exists(os.path.join(HERE, "compare_baseline.py")):
        say("[run] 基线比对 · %s" % baseline_why)
        cmd = [sys.executable, os.path.join(HERE, "compare_baseline.py"), out_dir,
               "--baseline", baseline_path]
        if args.update_baseline:
            cmd.append("--update")
        if args.strict:
            cmd.append("--strict-missing")
        cp = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE, errors="replace")
        say((cp.stdout or cp.stderr or "").strip())
        diff_path = os.path.join(out_dir, "baseline_diff.json")
        if os.path.exists(diff_path):
            try:
                with open(diff_path, encoding="utf-8") as f:
                    diff = json.load(f)
            except Exception:
                diff = None
        say()

    # 汇总表 + 机读 summary
    say("=" * 78)
    say("%-40s %8s %-10s %s" % ("组", "用时", "状态", "判定"))
    say("-" * 78)
    totals = {}
    for r in results:
        c = r["counts"]
        for k, v in c.items():
            totals[k] = totals.get(k, 0) + v
        say("%-40s %7.1fs %-10s %s" % (r["group"], r["seconds"], r["status"],
                                        " ".join("%s=%d" % (k, c[k]) for k in VERDICTS if c.get(k)) or "-"))
    say("-" * 78)
    say("合计：" + (" ".join("%s=%d" % (k, totals[k]) for k in VERDICTS if totals.get(k)) or "-"))
    say("产物：%s" % out_dir)

    summary = dict(when=ts, subject=subject, timeout=args.timeout, groups=results, totals=totals,
                   baseline=os.path.relpath(baseline_path, HERE).replace(os.sep, "/"),
                   baseline_note=baseline_why, platform=platform_slug())
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "run.log"), "w", encoding="utf-8") as f:
        for r in results:
            f.write("=== %s (%s, %.1fs) ===\n" % (r["group"], r["status"], r["seconds"]))
            f.write("\n".join(r["log"]) + "\n\n")

    # ── 交出去：JUnit（CI 读）+ HTML（人读）+ ATTEST（第三方复算） ──
    # 这三件是"外人能不能用"的关键：报告不是给自己看的截图，而是能被脚本接走的文件。
    try:
        import bench_report as R
        groups_cases = R.load_cases(out_dir)
        if not args.no_junit:
            say("[run] JUnit  %s" % R.write_junit(out_dir, summary, groups_cases))
        if not args.no_html:
            say("[run] 报告    %s" % R.write_html(out_dir, summary, diff, groups_cases,
                                                  subject_head=R.git_head(subject),
                                                  baseline_name=os.path.relpath(baseline_path, HERE)))
        if args.attest:
            with open(os.path.join(HERE, "VERSION"), encoding="utf-8") as f:
                ver = (f.read().strip() or None)
            j, m, digest = R.write_attest(out_dir, summary, subject_head=R.git_head(subject),
                                          bench_version=ver,
                                          extra={"baseline": os.path.relpath(baseline_path, HERE)})
            say("[run] 存证    %s / %s（manifest_sha256=%s…）" % (j, m, digest[:16]))
        say()
    except Exception as e:
        say("[run] 导出 JUnit/HTML/存证失败（不影响判定，但这次不能外发）：%r" % (e,))


    # 退出码只管"这台台子有没有坏"，不管"被测仓好不好"：
    # 一个用例 FAIL 是本次测量得出的结论（也可能是基线里早就记着的已知缺陷），
    # 把它当失败会让外人以为 bench 自己跑挂了。真正要退 1 的是：
    #   组没跑完（非 0 退出 / 超时 / 没产物）  或  相对基线出现回归/用例消失。
    broken = [r["group"] for r in results if r["status"] != "ok" or r["counts"].get("TIMEOUT")]
    regressed = (diff or {}).get("regress") or []
    vanished = (diff or {}).get("missing") or []

    # 没跑的组（--quick / --only）本来就不会产出用例，不该算"消失"。
    ran_prefixes = {r["group"].split("_")[0].split("-")[0] for r in results}
    try:
        with open(baseline_path, encoding="utf-8") as f:
            base_by_case = {c["case"]: c.get("group", "") for c in json.load(f).get("cases", [])}
        skipped = [c for c in vanished
                   if base_by_case.get(c) and base_by_case[c].split("_")[0] not in ran_prefixes]
        vanished = [c for c in vanished if c not in skipped]
        if skipped and not args.strict:
            say("[run] 本次没跑的组，其基线用例 %d 条不计入'消失'（--quick/--only 的正常现象）" % len(skipped))
    except Exception:
        pass

    # 已登记的平台差异（baseline/<平台>.json 的 excludes）：本平台本来就不产出，不算"消失"。
    if baseline_excludes and vanished and not args.strict:
        known = [c for c in vanished if c in baseline_excludes]
        vanished = [c for c in vanished if c not in baseline_excludes]
        if known:
            say("[run] 本平台已登记不产出的用例 %d 条（baseline/%s.json），不计入'消失'" % (len(known), platform_slug()))

    if diff is not None:
        say("\n[run] 相对基线：回归 %d、消失 %d、新增 %d、变化 %d"
            % (len(regressed), len(vanished), len((diff or {}).get("added") or []),
               len((diff or {}).get("changed") or [])))
    fail_cases = totals.get("FAIL", 0)
    if fail_cases:
        if diff is None:
            say("[run] FAIL=%d 条：这是被测仓的结论（本次没做基线比对，无法判断是否新增）。"
                "要判回归，去掉 --no-baseline 再跑一次。" % fail_cases)
        else:
            say("[run] FAIL=%d 条，其中相对基线新增 %d 条（其余为基线已记录的已知项）。"
                % (fail_cases, len(regressed)))

    if broken or regressed or (vanished and args.strict):
        if broken:
            say("[run] 台子没跑完：%s（看 runs/.../run.log 与 summary.json）" % ", ".join(broken))
        if regressed:
            say("[run] 相对基线回归：%s" % ", ".join(x["case"] for x in regressed[:10]))
        if vanished and args.strict:
            say("[run] 基线里的用例本次没有产出（--strict 下判失败）：%s" % ", ".join(vanished[:10]))
        return 1

    if vanished:
        say("[run] 提示：%d 条基线用例本次没产出（换平台/改名常见，未判失败；要判失败加 --strict）：%s"
            % (len(vanished), ", ".join(vanished[:10])))
    say("\n[run] 台子正常：全部组都有产物、无超时、相对基线无回归。"
        "（BLOCKED=缺前置，REFERENCE=引用第三方，均不算失败）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
