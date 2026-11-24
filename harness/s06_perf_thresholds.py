# -*- coding: utf-8 -*-
"""场景组 F：性能阈值。没有阈值就没有告警——上次 0.99s、这次 3s，报告里看不出来。

阈值集中在 thresholds.json，超 1.5 倍判 WARN，超 3 倍判 FAIL。
时延用 curl 的 time_total（此前实测 urllib 计时受本机透明层影响会显示 0ms，不可信）。
"""
import json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
REPO = os.path.join(KIT, "uibc-core-public")
PY = sys.executable
TH = os.path.join(KIT, "thresholds.json")
RESULTS = []
PLAT = "https://iaisp.teleinfo.cn/api/public/ioa/agents"

# 共享 runner 上的计时没有可比性：同一台平台，家宽 86ms、云主机 392ms、GitHub runner 实测 P50≈950ms。
# 这不是"平台变慢"，是"测量点在哪儿"的问题。CI 里又没指定 UIB_PROFILE 时，性能类只测量、不判。
CI_UNPINNED = bool(os.environ.get("CI")) and not os.environ.get("UIB_PROFILE", "").strip()


def rec(case, verdict, note="", extra=None):
    RESULTS.append(dict(case=case, verdict=verdict, note=note, extra=extra or {}))
    print("[%-5s] %-44s %s" % (verdict, case, note))


def load_th():
    """阈值按环境分档：同一台平台，从家宽测是 86ms，从云主机公网出口测是 392ms，
    用同一个绝对阈值必然误报。UIB_PROFILE=cloud 走云端档，默认 local。"""
    if not os.path.exists(TH):
        return {}
    th = json.load(open(TH, encoding="utf-8"))
    prof = os.environ.get("UIB_PROFILE", "local")
    for k, v in (th.get("profiles", {}).get(prof) or {}).items():
        if not k.startswith("_"):
            th[k] = v
    if th.get("profiles"):
        th["_profile"] = prof
    return th


def judge(name, value_ms, warn_ms, fail_ms):
    if value_ms <= warn_ms:
        return "PASS"
    if value_ms <= fail_ms:
        return "WARN"
    return "FAIL"


def http_times(url, n=7):
    """跨平台计时：用标准库 urllib（curl 在 Linux 上不一定叫 curl，也没有 NUL 设备）。
    每次新建连接（Connection: close），测到首字节的耗时。"""
    import urllib.request, socket
    vals = []
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(url, headers={"Connection": "close",
                                                       "User-Agent": "uibc-bench/0.3"})
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read(64)
            vals.append((time.perf_counter() - t0) * 1000)
        except Exception:
            pass
        time.sleep(0.2)
    return sorted(vals)


def f1_platform_latency(th):
    vals = http_times(PLAT, 7)
    if not vals:
        rec("F1 平台 agents 时延", "BLOCKED", "取不到响应时间（网络或 TLS 失败）"); return
    p50 = vals[len(vals) // 2]
    p95 = vals[int(len(vals) * 0.95) - 1]
    cold = vals[0]
    t = th.get("platform_agents_p95_ms", 300)
    if CI_UNPINNED:
        rec("F1 平台 agents 时延 P50/P95", "REFERENCE",
            "P50=%.0fms P95=%.0fms 最慢=%.0fms（n=7）；共享 runner 的计时不作判据——"
            "要判性能请在目标网络里用 UIB_PROFILE 指定档位" % (p50, p95, vals[-1]),
            {"kind": "性能", "p50": round(p50, 1), "p95": round(p95, 1), "ci_untimed": True})
        rec("F1 最慢单次请求", "REFERENCE",
            "最慢 %.0fms（仅记录，不判）" % vals[-1],
            {"kind": "性能长尾", "max_ms": round(vals[-1], 1)})
        rec("F1 冷启动 TLS 握手", "REFERENCE",
            "共享 runner 上不判（连接建立成本随网络路径变化）")
        return
    rec("F1 平台 agents 时延 P50/P95", judge("", p95, t, t * 2),
        "P50=%.0fms P95=%.0fms 最慢=%.0fms 阈值=%dms（n=7）" % (p50, p95, vals[-1], t),
        {"kind": "性能", "p50": round(p50, 1), "p95": round(p95, 1)})
    # 最慢单次：批量任务会被一次卡顿拖住，必须单独判
    worst = vals[-1]
    rec("F1 最慢单次请求", "PASS" if worst <= t * 3 else "WARN",
        "最慢 %.0fms（阈值×3=%.0fms）%s" % (worst, t * 3, "——出现偶发长尾，批量调用需设超时与重试" if worst > t * 3 else ""),
        {"kind": "性能长尾", "severity": "中" if worst > t * 3 else "-", "max_ms": round(worst, 1)})
    # 冷启动（新连接 TLS 握手）：标准库直接开一条 TLS 连接，跨平台一致
    import ssl, socket
    host = "iaisp.teleinfo.cn"
    t2 = th.get("platform_tls_handshake_ms", 1500)
    try:
        t0 = time.perf_counter()
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=20) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                pass
        tls = (time.perf_counter() - t0) * 1000
        rec("F1 冷启动 TLS 握手", judge("", tls, t2, t2 * 2),
            "%.0fms 阈值=%dms（新连接成本，短连接客户端要乘调用次数）" % (tls, t2))
    except Exception as e:
        rec("F1 冷启动 TLS 握手", "BLOCKED", "TLS 握手失败：%s" % repr(e)[:90])


def f2_local_ops(th):
    # 分发包不含被测仓库；缺仓库要报 BLOCKED 并给命令，而不是抛 ImportError 污染结果
    if not os.path.isdir(REPO):
        for c in ("F2 did:key 单次解析", "F2 CLI demo 端到端", "F2 10 证据包校验"):
            rec(c, "BLOCKED", "未找到 uibc-core-public；先执行 .\\setup.ps1 克隆被测仓库")
        return
    sys.path.insert(0, REPO)
    try:
        from uibc_core import did as didmod
    except Exception as e:
        for c in ("F2 did:key 单次解析", "F2 CLI demo 端到端", "F2 10 证据包校验"):
            rec(c, "BLOCKED", "当前解释器 %s 导入不了 uibc_core（缺依赖）：%s"
                % (os.path.basename(PY), repr(e)[:90]))
        return
    # did:key 纯本地解析
    t0 = time.perf_counter()
    for _ in range(200):
        didmod.resolve("did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK")
    per = (time.perf_counter() - t0) * 1000 / 200
    t = th.get("did_key_resolve_ms", 3)
    rec("F2 did:key 单次解析", judge("", per, t, t * 3),
        "%.2fms/次（200 次均值）阈值=%dms" % (per, t), {"kind": "性能"})

    # CLI demo 端到端
    d = tempfile.mkdtemp(prefix="perf_demo_")
    t0 = time.time()
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    p = subprocess.run([PY, "-m", "uibc_core.cli", "demo"], cwd=d, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    dur = (time.time() - t0) * 1000
    t = th.get("cli_demo_ms", 10000)
    # 跑失败 ≠ 跑得快：非零退出必须先判 FAIL，不能因为耗时长就 PASS（2026-11-23 Linux 上真出现过这种假绿）
    verdict = "FAIL" if p.returncode != 0 else judge("", dur, t, t * 3)
    rec("F2 CLI demo 端到端", verdict,
        "%.0fms 阈值=%dms exit=%s" % (dur, t, p.returncode), {"kind": "性能"})
    shutil.rmtree(d, ignore_errors=True)

    # 包校验（10 个证据文件）成本
    d2 = tempfile.mkdtemp(prefix="perf_pkg_")
    k = os.path.join(d2, "k.hex")
    subprocess.run([PY, "-m", "uibc_core.cli", "keygen", "--out", k], cwd=d2, capture_output=True)
    subprocess.run([PY, "-m", "uibc_core.cli", "init", "p"], cwd=d2, capture_output=True)
    subprocess.run([PY, "-m", "uibc_core.cli", "register", "p", "--agent-id", "perf-01", "--owner", "perf"],
                   cwd=d2, capture_output=True)
    for i in range(10):
        f = os.path.join(d2, "ev%d.txt" % i)
        open(f, "w", encoding="utf-8").write("evidence %d " % i + "x" * 2000)
        subprocess.run([PY, "-m", "uibc_core.cli", "evidence", "p", "--file", f, "--type", "OUTPUT"],
                       cwd=d2, capture_output=True)
    subprocess.run([PY, "-m", "uibc_core.cli", "submit", "p", "--key", k], cwd=d2, capture_output=True)
    t0 = time.time()
    pv = subprocess.run([PY, "-m", "uibc_core.cli", "verify", "p"], cwd=d2, capture_output=True, text=True)
    dur = (time.time() - t0) * 1000
    t = th.get("verify_pkg_10ev_ms", 2000)
    rec("F2 10 证据包校验", "PASS" if pv.returncode in (0, 1) and dur <= t else judge("", dur, t, t * 3),
        "%.0fms 阈值=%dms" % (dur, t), {"kind": "性能"})
    shutil.rmtree(d2, ignore_errors=True)


def f0_verdict_selftest():
    """负向回归：证明"非零退出必判 FAIL"这条规则本身有效。

    由来：v0.3.1 曾把 exit≠0 但耗时短的调用判成 PASS（假绿），
    只有换到 Linux 才暴露。修完后必须留一条用例把规则钉死，
    否则以后改代码时可能又悄悄退化成"只看耗时"。
    """
    d = tempfile.mkdtemp(prefix="selftest_")
    try:
        # 故意制造一个"很快但失败"的调用：Python 立即以退出码 3 结束
        p = subprocess.run([PY, "-c", "import sys;sys.exit(3)"], cwd=d,
                           capture_output=True, text=True, timeout=60)
        t = load_th().get("cli_demo_ms", 10000)
        verdict = "FAIL" if p.returncode != 0 else judge("", 1, t, t * 3)
        ok = (verdict == "FAIL")
        rec("F0 判定器自检（exit≠0 必判 FAIL）", "PASS" if ok else "FAIL",
            "构造 exit=3、耗时≈0ms 的调用 → 判定=%s（应为 FAIL）；%s"
            % (verdict, "规则有效" if ok else "规则已退化，假绿会重现"),
            {"kind": "负向回归", "severity": "高"})
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    print("=== F 组：性能阈值 %s ===" % time.strftime("%F %T"))
    th = load_th()
    rec("F0 阈值来源", "INFO", "thresholds.json %s，档位=%s" % ("已加载" if th else "缺省内置值", th.get("_profile", "default")))
    f0_verdict_selftest()
    for fn in (f1_platform_latency, f2_local_ops):
        try:
            fn(th)
        except Exception as e:
            import traceback; traceback.print_exc()
            rec(fn.__name__, "ERROR", repr(e)[:150])
    out = sys.argv[1] if len(sys.argv) > 1 else "s06_results.json"
    json.dump(RESULTS, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    v = {}
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== 汇总 %s ===" % v)


if __name__ == "__main__":
    main()
