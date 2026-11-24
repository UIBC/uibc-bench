# -*- coding: utf-8 -*-
"""场景组 D：外人全量实跑（单测 / 一致性工具 / 端到端 demo / Release 包）。

这些跑得慢，单独成组；判据是"外人 clone 下来照文档做，能不能一次过"。
"""
import json, os, re, subprocess, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
import _subject  # 统一解析：UIBC_SUBJECT 优先，其次 <bench根>/uibc-core-public
REPO = _subject.resolve(require=False) or os.path.join(KIT, "uibc-core-public")
PY = sys.executable
RESULTS = []


def rec(case, verdict, note="", extra=None):
    RESULTS.append(dict(case=case, verdict=verdict, note=note, extra=extra or {}))
    print("[%-5s] %-44s %s" % (verdict, case, note))


def _tmp_env():
    """把临时目录钉到被测仓所在盘。

    2026-11-25 实测（Windows，bench 在 F:、系统 TEMP 在 C:）：被测仓
    tests/test_crosswalk_probe.py 用 tempfile 造文件再与被测仓算相对路径，
    `ntpath.relpath` 跨盘直接抛 ValueError: path is on mount 'C:', start on
    mount 'F:'，7 条用例全红。那不是被测仓的缺陷，是台子让临时目录跟被测仓
    分了盘。CI 单盘永远看不到，外人（尤其 Windows 用户）一跑就中。
    """
    if os.name != "nt":
        return {}
    drive = os.path.splitdrive(os.path.abspath(REPO))[0]
    if not drive:
        return {}
    d = os.path.join(drive + os.sep, "_uibc_bench_tmp")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return {}
    return {"TEMP": d, "TMP": d, "TMPDIR": d}

def run(args, cwd=REPO, timeout=900, env=None):
    e = dict(os.environ); e.update(env or {}); e.setdefault("PYTHONIOENCODING", "utf-8")
    e.update(_tmp_env())
    e["PYTHONPATH"] = REPO + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    t0 = time.time()
    p = subprocess.run([PY] + args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env=e)
    return p.returncode, p.stdout or "", p.stderr or "", time.time() - t0


def fingerprint():
    """把"跑在什么机器上"写下来。

    由来：同一命令在 Windows 265s 跑完，在云主机 15 分钟仍未结束（CPU 只 12s），
    没有指纹就无法区分"这台机器慢"和"这条用例卡住"。有指纹后，
    任何"慢/超时"结论都必须带上它，否则不许下判断。
    """
    import platform, shutil, socket
    fp = dict(os=platform.platform(), machine=platform.machine(),
              python=platform.python_version(), impl=platform.python_implementation(),
              cpu_cores=os.cpu_count(), tz=time.strftime("%Z %z"),
              py_exe=PY, repo=REPO, cwd=os.getcwd(),
              disk_free_gb=None)
    try:
        fp["disk_free_gb"] = round(shutil.disk_usage(KIT).free / (1024 ** 3), 1)
    except Exception:
        pass
    # 被测副本的克隆设置：决定"47 例失败"是真缺陷还是行尾改写，必须在结论旁边写明
    try:
        g = subprocess.run(["git", "-C", REPO, "config", "--get", "core.autocrlf"],
                           capture_output=True, text=True, timeout=20)
        fp["repo_autocrlf"] = (g.stdout or "").strip() or "unset"
        g2 = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True, timeout=20)
        fp["repo_head"] = (g2.stdout or "").strip() or "?"
    except Exception:
        pass
    # 外网可达性：被测侧网络依赖项是否会卡，靠这一项解释
    for host, port, key in (("github.com", 443, "github"), ("iaisp.teleinfo.cn", 443, "iaisp")):
        t0 = time.time()
        try:
            socket.create_connection((host, port), timeout=8).close()
            fp[key + "_reachable_ms"] = int((time.time() - t0) * 1000)
        except Exception as e:
            fp[key + "_unreachable"] = repr(e)[:80]
    p = os.path.join(KIT, "runs", "_env_fingerprint.json")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(fp, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass
    return fp


def run_stream(args, outfile, cwd=REPO, timeout=900):
    """跑长命令并把逐行输出落盘。

    由来：`unittest discover` 在云主机上 15 分钟不结束、cpu 只 12s；用
    subprocess.run 抓 stdout 时一旦超时，输出全丢，只剩"超时"两个字，
    谁也无法判断卡在哪条用例。改成落盘流式输出：超时也留证据。
    """
    e = dict(os.environ); e.setdefault("PYTHONIOENCODING", "utf-8")
    e.update(_tmp_env())
    e["PYTHONPATH"] = REPO + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    os.makedirs(os.path.dirname(outfile), exist_ok=True)
    t0 = time.time()
    f = open(outfile, "w", encoding="utf-8", errors="replace")
    p = subprocess.Popen([PY] + args, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, env=e)
    timed_out = False
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        p.kill(); p.wait()
    f.close()
    try:
        txt = open(outfile, encoding="utf-8", errors="replace").read()
    except Exception:
        txt = ""
    return p.returncode, txt, time.time() - t0, timed_out


def d1_unittest():
    if not os.path.isdir(REPO):
        # 没有被测仓就干净地说清楚，而不是让子进程在不存在的工作目录里抛
        # NotADirectoryError（WinError 267）——那是给不出结论的错误。
        rec("D1 外人全量单测", "BLOCKED",
            "找不到被测仓 %s。传 --subject <uibc-core 目录>、设 UIBC_SUBJECT，"
            "或克隆到 ./uibc-core-public" % REPO)
        return
    fp = fingerprint()
    rec("D0 环境指纹", "INFO",
        "%s / %s / py%s / %s核 / 时区 %s / 磁盘余 %.1fGB / github:%s / iaisp:%s" % (
            fp["os"].split("-")[0], fp["machine"], fp["python"], fp["cpu_cores"], fp["tz"],
            fp.get("disk_free_gb") or -1,
            ("%dms" % fp["github_reachable_ms"]) if fp.get("github_reachable_ms") else "不可达",
            ("%dms" % fp["iaisp_reachable_ms"]) if fp.get("iaisp_reachable_ms") else "不可达"),
        {"fingerprint": fp, "file": "runs/_env_fingerprint.json"})
    t0_tests = time.time()
    outp = os.path.join(KIT, "runs", "d1_unittest_v.log")
    # 命令用被测仓 README 里写的那一条（`python -m pytest -q`），不是 unittest discovery：
    # 2026-11-24 实测，同一提交 unittest 只收 1157 例、pytest 收 1589 例；用前者会把
    # 一个 pytest 风格用例（module 级 importorskip）记成 FAIL，而外人照文档跑其实是绿的。
    code, txt, dt, timed_out = run_stream(["-m", "pytest", "-q"], outp, timeout=900)
    retried = False
    retry_note = ""
    if code != 0 and not timed_out:
        # 失败不等于被测方有缺陷，也不等于我们环境有问题：先复跑再定性。
        # v0.4.5 起改为**只复跑失败的那几条**（全量复跑 345s 太重，且会把一次偶发拖成十分钟）：
        # 单条复跑通过 = 偶发竞态（仍记 FAIL，但把证据写进结论）；单条也失败 = 真失败。
        fails0 = re.findall(r"^FAILED (\S+::\S+)", txt, re.M)
        run_ok, run_n = 0, 0
        details = []
        for nodeid in fails0[:5]:
            f_rel = nodeid.split("::")[0]
            meth = nodeid.split("::")[-1].split("[")[0]
            f = os.path.join(REPO, f_rel)
            if not os.path.exists(f):
                details.append("%s -> 找不到测试文件（复跑跳过）" % meth[:50]); run_n += 1; continue
            run_n += 1
            o2 = os.path.join(KIT, "runs", "d1_single_rerun_%d.log" % run_n)
            # 用 pytest -k 单跑：unittest 的 `-m unittest 模块.类.方法` 在本仓需要 tests 在 sys.path，
            # 写错路径会把"脚本没跑起来"误读成"用例失败"（v0.4.5 修的就是这个假阴性）。
            c2, t2, _, to2 = run_stream(["-m", "pytest", f_rel, "-k", meth, "-q"], o2, timeout=300)
            ok2 = (c2 == 0 and not to2 and "no tests ran" not in t2)
            run_ok += 1 if ok2 else 0
            details.append("%s -> %s" % (meth[:60], "PASS" if ok2 else "FAIL"))
        if run_n:
            retry_note = "｜单条复跑 %d/%d 通过（%s）" % (run_ok, run_n, "；".join(details))
    lines = [l for l in txt.splitlines() if l.strip()]
    m = re.search(r"(\d+) passed", txt)
    n = int(m.group(1)) if m else -1
    fails = re.findall(r"^FAILED (\S+)", txt, re.M)
    skipped = re.search(r"(\d+) skipped", txt)
    skips = re.findall(r"SKIPPED \[\d+\] (\S+?):", txt)
    ok = code == 0 and not timed_out
    if timed_out:
        # 卡点定位：最后一条已开始的用例就是嫌疑对象
        last = ""
        for l in reversed(lines):
            if " ..." in l:
                last = l.strip(); break
        rec("D1 外人全量单测", "FAIL",
            "超时 %.0fs（上限 900s）· 已跑 %d 行 · 最后一条：%s" % (dt, len(lines), last[:90]),
            {"timeout": True, "log": "runs/d1_unittest_v.log", "last": last,
             "fingerprint": fp})
        return
    note = "%s exit=%s 用例=%d 失败=%d 跳过=%s 用时=%.0fs%s" % (
        "[偶发·首轮失败复跑通过]" if retried else "", code, n, len(fails),
        skipped.group(1) if skipped else "?", dt, retry_note)
    # 47 例这个数量级几乎只可能是行尾改写：被测仓有一批硬编码 sha256 的测试夹具，
    # 默认克隆（autocrlf=true）会把它们改写。这里把解释直接贴在结论旁边，
    # 否则外人看到 47 个 F 会以为整个项目是坏的 —— 2026-11-23 包内实测正是如此。
    if len(fails) >= 30 and str(fp.get("repo_autocrlf", "")).lower() in ("true", "input"):
        note += "｜疑因默认克隆行尾改写（本副本 autocrlf=%s），根因与判据见 E1 组" % fp["repo_autocrlf"]
    rec("D1 外人全量单测", "PASS" if ok else "FAIL", note.strip(),
        # fails 现在是 pytest 的 nodeid 字符串（`FAILED path::nodeid`），不要再按元组解包：
        # 2026-11-24 v0.4.38 第一版在这里留着旧的两元解包，Windows 上只要有 1 条失败就
        # ValueError（too many values to unpack），整组被记成 ERROR——Linux 上恰好 0 失败，
        # 所以只在 Windows 暴露。这正是"只在一种平台上验过就等于没验"的实例。
        {"failures": [str(f) for f in fails][:40], "tail": lines[-6:],
         "log": "runs/d1_unittest_v.log", "retried": retried, "fingerprint": fp})
    if skips:
        kinds = sorted(set(skips))
        rec("D1 跳过原因归档", "INFO", "%d 条跳过，%d 种原因：%s" % (len(skips), len(kinds), " / ".join(kinds)[:320]))
    if fp.get("github_unreachable"):
        # 不单独产用例：这一项时有时无，会污染基线（同一条命令今天 122 条、明天 123 条）。
        # 折进 D0 的说明里，基线用例数保持恒定。
        print("[INFO ] github.com 不可达（%s），D1 用时 %.0fs 属正常范围" % (fp["github_unreachable"], dt))
    if fails:
        mods = {}
        for name in fails:
            mods[name] = mods.get(name, 0) + 1
        rec("D1 失败集中在哪些测试", "INFO", json.dumps(mods, ensure_ascii=False)[:400])


def d2_conformance():
    p = os.path.join(REPO, "tools", "gateway_conformance.py")
    if not os.path.exists(p):
        rec("D2 网关一致性工具", "BLOCKED", "tools/gateway_conformance.py 不存在于本提交"); return
    code, out, err, dt = run([p], timeout=600)
    tail = (out or err).strip().splitlines()[-8:]
    rec("D2 网关一致性 43 条", "PASS" if code == 0 else "FAIL",
        "exit=%s %.0fs %s" % (code, dt, " | ".join(tail[-3:])[:220]), {"tail": tail})


def d3_crosscheck():
    p = os.path.join(REPO, "independent_verifier", "cross_check.py")
    if not os.path.exists(p):
        rec("D3 独立交叉核验", "BLOCKED", "independent_verifier/cross_check.py 不存在"); return
    code, out, err, dt = run([p], timeout=600)
    tail = (out or err).strip().splitlines()[-6:]
    rec("D3 独立交叉核验", "PASS" if code == 0 else "FAIL",
        "exit=%s %.0fs %s" % (code, dt, " | ".join(tail[-3:])[:200]), {"tail": tail})


def d4_demo():
    code, out, err, dt = run(["-m", "uibc_core.cli", "demo"], timeout=600)
    tail = (out or err).strip().splitlines()[-4:]
    rec("D4 一条命令端到端 demo", "PASS" if code == 0 else "FAIL",
        "exit=%s %.1fs %s" % (code, dt, " | ".join(tail)[:200]), {"tail": tail})


def d5_release():
    # 仓库里提交的发行包（如果有）；必须按"包内确实有 run.py"来挑，否则是挑错了对象
    import zipfile, tempfile, shutil
    cands = []
    for root, _, files in os.walk(REPO):
        for f in files:
            if f.endswith(".zip"):
                cands.append(os.path.join(root, f))
    if not cands:
        rec("D5 Release 包实跑", "BLOCKED", "本提交内未发现 release zip，需从 Releases 页下载后单独测"); return
    good = []
    for z in cands:
        try:
            with zipfile.ZipFile(z) as zf:
                if any(n.endswith("run.py") for n in zf.namelist()):
                    good.append(z)
        except Exception:
            continue
    if not good:
        rec("D5 Release 包实跑", "BLOCKED",
            "仓库内 %d 个 zip 均无 run.py（不是发行包）：%s" % (len(cands), [os.path.basename(c) for c in cands][:3]))
        return
    z = sorted(good, key=os.path.getmtime)[-1]
    d = tempfile.mkdtemp(prefix="rel_")
    with zipfile.ZipFile(z) as zf:
        zf.extractall(d)
    runner = None
    for root, _, files in os.walk(d):
        if "run.py" in files:
            runner = root; break
    if not runner:
        rec("D5 Release 包实跑", "FAIL", "包内 run.py 解压后找不到"); return
    t0 = time.time()
    p = subprocess.run([PY, "run.py"], cwd=runner, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600)
    tail = (p.stdout or p.stderr).strip().splitlines()[-3:]
    rec("D5 Release 包 run.py", "PASS" if p.returncode == 0 else "FAIL",
        "%s · %.1fs · %s" % (os.path.basename(z), time.time() - t0, " | ".join(tail)[:200]))
    shutil.rmtree(d, ignore_errors=True)


def main():
    print("=== D 组：外人全量实跑 %s ===" % time.strftime("%F %T"))
    only = (sys.argv[2] if len(sys.argv) > 2 else "").lower()
    plan = [("d1", d1_unittest), ("d2", d2_conformance), ("d3", d3_crosscheck), ("d4", d4_demo), ("d5", d5_release)]
    for k, fn in plan:
        if only and k not in only:
            continue
        try:
            fn()
        except subprocess.TimeoutExpired:
            rec(fn.__name__, "FAIL", "超时")
        except Exception:
            rec(fn.__name__, "ERROR", traceback.format_exc().splitlines()[-1][:160])
    out = sys.argv[1] if len(sys.argv) > 1 else "s04_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    v = {}
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== 汇总 %s ===" % v)


if __name__ == "__main__":
    main()
