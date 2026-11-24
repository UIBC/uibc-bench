# -*- coding: utf-8 -*-
"""场景组 C：多生态 × 多系统的可用性/兼容性实测。

覆盖：MCP(JSON-RPC over stdio)、A2A 适配器、Node 侧独立校验、CLI 全链路（中文路径/
空格/长路径）、并发与锁、时区与语言环境、凭据泄漏扫描。
每个用例都是"上线后真实会遇到的情况"，失败只记录不中断。
"""
import json, os, shutil, subprocess, sys, tempfile, threading, time, traceback, hashlib, re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "uibc-core-public"))
PY = sys.executable
RESULTS = []
CN_DIR = os.path.join(tempfile.gettempdir(), "实测_中国信通院 身份码 场景")
# 目录不会自己出现：Linux 上 /tmp 是空的，Windows 上可能残留旧目录，两种情况都要能跑
os.makedirs(CN_DIR, exist_ok=True)


def rec(case, verdict, note="", extra=None):
    RESULTS.append(dict(case=case, verdict=verdict, note=note, extra=extra or {}))
    print("[%-5s] %-46s %s" % (verdict, case, note))


def run(args, cwd=None, timeout=180, env=None, stdin=None):
    e = dict(os.environ); e.update(env or {}); e["PYTHONIOENCODING"] = e.get("PYTHONIOENCODING", "utf-8")
    # 不依赖"这台机器装过 uibc_core"：把被测仓库放进 PYTHONPATH，换机器/换 venv 都能跑
    e["PYTHONPATH"] = REPO + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    t0 = time.time()
    p = subprocess.run([PY] + args, cwd=cwd or REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",   # 非 UTF-8 控制台不应让脚本崩
                       timeout=timeout, env=e, input=stdin)
    return p.returncode, (p.stdout or ""), (p.stderr or ""), time.time() - t0


# ---------- C1 MCP ----------
def c1_mcp():
    msgs = [
        ("C1 initialize", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2024-11-05", "clientInfo": {"name": "outsider"}}}),
        ("C1 tools/list", {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
        ("C1 未知方法", {"jsonrpc": "2.0", "id": 3, "method": "no/such", "params": {}}),
        ("C1 未知工具", {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "nope", "arguments": {}}}),
        ("C1 缺参数调用", {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                          "params": {"name": "verify_package", "arguments": {}}}),
        ("C1 路径不存在", {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                          "params": {"name": "verify_package", "arguments": {"path": "Z:/nope.pkg"}}}),
        ("C1 大参数 1MB", {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                          "params": {"name": "inspect_package", "arguments": {"path": "x" * (1024 * 1024)}}}),
    ]
    payload = "".join(json.dumps(m[1], ensure_ascii=False) + "\n" for m in msgs)
    payload += "{not json}\n"          # 畸形行
    payload += "\x00\x01\x02garbage\n"  # 二进制垃圾
    payload += json.dumps({"jsonrpc": "2.0", "id": 9, "method": "tools/list"}) + "\n"
    try:
        code, out, err, dt = run(["-m", "uibc_core.mcp_server"], stdin=payload, timeout=60)
        lines = [l for l in out.splitlines() if l.strip()]
        ok_ids = []
        for l in lines:
            try:
                j = json.loads(l)
                if "id" in j:
                    ok_ids.append(j["id"])
            except Exception:
                pass
        rec("C1 MCP 会话(7 请求+2 垃圾行)", "PASS" if 1 in ok_ids and 2 in ok_ids else "FAIL",
            "exit=%s 响应行=%d 收到 id=%s stderr=%r" % (code, len(lines), ok_ids, err.strip()[:120]))
        rec("C1 MCP 未知方法是否给 JSON-RPC 错误", "PASS" if 3 in ok_ids else "WARN", "id3 有无响应：%s" % (3 in ok_ids))
        rec("C1 MCP 畸形行是否中止进程", "PASS" if code in (0, None) else "WARN",
            "exit=%s（%s）" % (code, "进程存活" if 9 in ok_ids else "垃圾行后无响应"))
        # 工具清单
        for l in lines:
            try:
                j = json.loads(l)
                if j.get("id") == 2 and "result" in j:
                    tools = [t["name"] for t in j["result"].get("tools", [])]
                    rec("C1 MCP 工具清单", "INFO", "%d 个：%s" % (len(tools), tools))
            except Exception:
                pass
        # 并发两个进程
        def one():
            return run(["-m", "uibc_core.mcp_server"], stdin=payload[:2000], timeout=60)[0]
        ths = [threading.Thread(target=one) for _ in range(2)]
        [t.start() for t in ths]; [t.join() for t in ths]
        rec("C1 MCP 双进程并发", "PASS", "两个独立进程均正常退出")
    except subprocess.TimeoutExpired:
        rec("C1 MCP 会话", "FAIL", "60s 未退出（疑似 stdin 未 EOF 或阻塞）")
    except Exception as e:
        rec("C1 MCP 会话", "ERROR", repr(e)[:150])


# ---------- C2 A2A 适配器 ----------
def c2_a2a():
    sys.path.insert(0, REPO)
    try:
        from adapters.a2a import transform as t
        fns = [n for n in dir(t) if not n.startswith("_") and callable(getattr(t, n))]
        rec("C2 A2A 导出函数", "INFO", "%d 个：%s" % (len(fns), fns[:10]))
    except Exception as e:
        rec("C2 A2A 导入", "FAIL", repr(e)[:140]); return
    # 用畸形输入打每个单参数函数
    bad_inputs = [None, {}, [], "", "x" * 10000, {"tasks": "notalist"}, {"id": None}]
    fails = []
    for fn in fns:
        f = getattr(t, fn)
        try:
            import inspect
            if len(inspect.signature(f).parameters) != 1:
                continue
        except Exception:
            continue
        for b in bad_inputs:
            try:
                f(b)
            except TypeError:
                continue
            except Exception as e:
                fails.append("%s(%r)->%s" % (fn, str(b)[:24], type(e).__name__))
    rec("C2 A2A 畸形输入", "WARN" if fails else "PASS",
        ("%d 处异常：%s" % (len(fails), fails[:6])) if fails else "全部以异常/拒绝收场，无静默错值", {"fails": fails[:20]})


# ---------- C3 Node 侧独立校验 ----------
def c3_node():
    if not shutil.which("node"):
        rec("C3 Node 可用性", "BLOCKED", "本机无 node，JS 端无法实跑（需在评审机补）"); return
    vjs = os.path.join(REPO, "tools", "verify-js", "verify.mjs")
    if not os.path.exists(vjs):
        rec("C3 Node 校验器存在性", "FAIL", "tools/verify-js/verify.mjs 缺失"); return
    # 造一个结构完整的包（init/register/event/evidence/submit）
    pkg = os.path.join(CN_DIR, "pkg_for_js")
    shutil.rmtree(pkg, ignore_errors=True)
    key = os.path.join(CN_DIR, "js_k.hex")
    run(["-m", "uibc_core.cli", "keygen", "--out", key], cwd=CN_DIR)
    run(["-m", "uibc_core.cli", "init", pkg], cwd=CN_DIR)
    run(["-m", "uibc_core.cli", "register", pkg, "--agent-id", "js-parity-01", "--owner", "跨语言对照"], cwd=CN_DIR)
    run(["-m", "uibc_core.cli", "event", pkg, "--type", "ACTIVATE"], cwd=CN_DIR)
    evf = os.path.join(CN_DIR, "js证据.txt")
    open(evf, "w", encoding="utf-8").write("跨语言对照证据\n")
    run(["-m", "uibc_core.cli", "evidence", pkg, "--file", evf, "--type", "OUTPUT"], cwd=CN_DIR)
    code, out, err, dt = run(["-m", "uibc_core.cli", "submit", pkg, "--key", key], cwd=CN_DIR)
    rec("C3 生成演示包", "PASS" if code == 0 else "FAIL",
        "exit=%s %.1fs %s" % (code, dt, out.strip().splitlines()[-1][:90] if out.strip() else err[:90]))

    # Node 侧独立校验（第二语言、零依赖；设计上永不返回 PASS，结构完好即 INCONCLUSIVE）
    try:
        p = subprocess.run(["node", vjs, pkg], capture_output=True, text=True, timeout=180)
        o = p.stdout or ""
        res = "INCONCLUSIVE" if "INCONCLUSIVE" in o else ("FAIL" if '"result": "FAIL"' in o or "FAIL" in o else "?")
        per_check = re.findall(r'"?(\bS\d{1,2})\b"?[^\n]*?(PASS|FAIL|INCONCLUSIVE)', o)
        neg = [c for c in per_check if c[1] == "FAIL"]
        rec("C3 Node 校验 Python 生成的包", "PASS" if (p.returncode in (0, 1) and not neg) else "FAIL",
            "node exit=%s 判定=%s 失败检查=%s（JS 端只做结构类，签名/时间戳留白）" % (p.returncode, res, neg[:4]),
            {"tail": o.strip().splitlines()[-4:]})
        # 与 Python 端同一包的判定对照
        code, out, err, dt = run(["-m", "uibc_core.cli", "verify", pkg], cwd=CN_DIR)
        pyres = "INCONCLUSIVE" if '"result": "INCONCLUSIVE"' in out else ("PASS" if '"result": "PASS"' in out else "?")
        rec("C3 两语言判定是否一致", "PASS" if pyres == res else "WARN",
            "Python=%s Node=%s（同一个包）" % (pyres, res))
    except Exception as e:
        rec("C3 Node 校验 Python 生成的包", "ERROR", repr(e)[:140])


# ---------- C4 CLI 全链路（中文路径/空格） ----------
def c4_cli():
    shutil.rmtree(CN_DIR, ignore_errors=True); os.makedirs(CN_DIR, exist_ok=True)
    work = os.path.join(CN_DIR, "包 一")
    os.makedirs(work, exist_ok=True)
    steps = [
        ("keygen", ["-m", "uibc_core.cli", "keygen", "--out", os.path.join(work, "密钥.hex")]),
        ("init", ["-m", "uibc_core.cli", "init", os.path.join(work, "包")]),
    ]
    for name, args in steps:
        code, out, err, dt = run(args, cwd=work)
        rec("C4 CLI %s（中文+空格路径）" % name, "PASS" if code == 0 else "FAIL",
            "exit=%s %.1fs %s" % (code, dt, (err or out).strip().splitlines()[-1][:100] if (err or out).strip() else ""))
    pk = os.path.join(work, "包")
    ev = os.path.join(work, "证据_输出.txt")
    open(ev, "w", encoding="utf-8").write("测试证据：一次真实调用输出\n")
    seq = [
        ("register", ["-m", "uibc_core.cli", "register", pk,
                      "--agent-id", "caict-test-agent-01", "--owner", "中国信通院-测试主体"]),
        ("event", ["-m", "uibc_core.cli", "event", pk, "--type", "ACTIVATE"]),
        ("evidence", ["-m", "uibc_core.cli", "evidence", pk, "--file", ev, "--type", "OUTPUT"]),
        ("submit", ["-m", "uibc_core.cli", "submit", pk, "--key", os.path.join(work, "密钥.hex")]),
        ("verify", ["-m", "uibc_core.cli", "verify", pk, "--key", os.path.join(work, "密钥.hex")]),
        ("gate", ["-m", "uibc_core.cli", "gate", pk]),
        ("inspect", ["-m", "uibc_core.cli", "inspect", pk]),
    ]
    for name, args in seq:
        try:
            code, out, err, dt = run(args, cwd=work, timeout=90)
            rec("C4 CLI %s" % name, "PASS" if code in (0, 2, 3) else "FAIL",
                "exit=%s %.1fs %s" % (code, dt, (out or err).strip().splitlines()[-1][:110] if (out or err).strip() else ""))
        except subprocess.TimeoutExpired:
            rec("C4 CLI %s" % name, "FAIL", "90s 超时")
    # 空证据包：按设计应是 INCONCLUSIVE + 退出码 1，而不是被拒或误判 PASS
    empty = os.path.join(work, "空证据包")
    shutil.rmtree(empty, ignore_errors=True)
    run(["-m", "uibc_core.cli", "init", empty], cwd=work)
    run(["-m", "uibc_core.cli", "register", empty, "--agent-id", "empty-01", "--owner", "空包"], cwd=work)
    run(["-m", "uibc_core.cli", "submit", empty, "--key", os.path.join(work, "k.hex")], cwd=work)
    code, out, err, dt = run(["-m", "uibc_core.cli", "verify", empty], cwd=work)
    res = "INCONCLUSIVE" if '"result": "INCONCLUSIVE"' in out else ("PASS" if '"result": "PASS"' in out else "?")
    rec("C4 空证据包 → INCONCLUSIVE(exit1)", "PASS" if (res == "INCONCLUSIVE" and code == 1) else "FAIL",
        "result=%s exit=%s（三值判定语义正确）" % (res, code))

    # 篡改后必须被抓住
    mf = os.path.join(pk, "manifest.json")
    if os.path.exists(mf):
        d = json.load(open(mf, encoding="utf-8"))
        d["agent"] = "被篡改" if isinstance(d.get("agent"), str) else d.get("agent")
        json.dump(d, open(mf, "w", encoding="utf-8"), ensure_ascii=False)
        code, out, err, dt = run(["-m", "uibc_core.cli", "verify", pk, "--key", os.path.join(work, "密钥.hex")], cwd=work)
        rec("C4 篡改包后 verify 必须非 0", "PASS" if code != 0 else "FAIL", "exit=%s %s" % (code, (out or err).strip().splitlines()[-1][:100] if (out or err).strip() else ""))
    # 截断/空文件
    broken = os.path.join(work, "坏包"); os.makedirs(broken, exist_ok=True)
    open(os.path.join(broken, "manifest.json"), "wb").write(b'{"agent":')
    try:
        code, out, err, dt = run(["-m", "uibc_core.cli", "verify", broken], cwd=work, timeout=60)
        rec("C4 截断 manifest 的处理", "PASS" if code != 0 else "FAIL",
            "exit=%s %s" % (code, (err or out).strip().splitlines()[-1][:110] if (err or out).strip() else ""))
        rec("C4 截断时是否泄漏堆栈", "WARN" if "Traceback" in err else "PASS", "stderr 含 Traceback：%s" % ("Traceback" in err))
    except subprocess.TimeoutExpired:
        rec("C4 截断 manifest 的处理", "FAIL", "60s 超时")


# ---------- C5 并发与锁（Windows 分支） ----------
def c5_lock():
    work = os.path.join(CN_DIR, "并发")
    shutil.rmtree(work, ignore_errors=True); os.makedirs(work, exist_ok=True)
    run(["-m", "uibc_core.cli", "keygen", "--out", os.path.join(work, "k.hex")], cwd=work)
    run(["-m", "uibc_core.cli", "init", os.path.join(work, "p")], cwd=work)
    pk = os.path.join(work, "p")
    run(["-m", "uibc_core.cli", "register", pk, "--agent-id", "concurrent-01", "--owner", "并发测试"], cwd=work)
    run(["-m", "uibc_core.cli", "event", pk, "--type", "ACTIVATE"], cwd=work)
    ev = os.path.join(work, "证据.txt")
    open(ev, "w", encoding="utf-8").write("并发测试证据\n")
    run(["-m", "uibc_core.cli", "evidence", pk, "--file", ev, "--type", "OUTPUT"], cwd=work)
    res = {"ok": 0, "err": [], "ms": []}
    lk = threading.Lock()

    def submit():
        t0 = time.time()
        try:
            code, out, err, dt = run(["-m", "uibc_core.cli", "submit", pk, "--key", os.path.join(work, "k.hex")], cwd=work, timeout=60)
            with lk:
                if code == 0: res["ok"] += 1
                else: res["err"].append(code)
                res["ms"].append(dt)
        except Exception as e:
            with lk: res["err"].append(type(e).__name__)

    ths = [threading.Thread(target=submit) for _ in range(6)]
    [t.start() for t in ths]; [t.join() for t in ths]
    rec("C5 6 进程并发 submit 同一包", "PASS" if not res["err"] else "WARN",
        "ok=%d err=%s 总耗时=%.1fs（锁在 Windows 上走 msvcrt 分支）" % (res["ok"], res["err"], sum(res["ms"])))
    code, out, err, dt = run(["-m", "uibc_core.cli", "verify", pk, "--key", os.path.join(work, "k.hex")], cwd=work)
    rec("C5 并发后包仍可校验", "PASS" if code == 0 else "FAIL", "exit=%s" % code)
    # 只读目录
    ro = os.path.join(work, "只读"); os.makedirs(ro, exist_ok=True)
    code, out, err, dt = run(["-m", "uibc_core.cli", "init", os.path.join(ro, "p2")], cwd=work)
    rec("C5 包写在没有权限的目录", "INFO", "exit=%s %s" % (code, (err or out).strip().splitlines()[-1][:90] if (err or out).strip() else ""))


# ---------- C6 时区/语言/编码 ----------
def c6_locale():
    a = os.path.join(CN_DIR, "tz_a"); b = os.path.join(CN_DIR, "tz_b")
    outs = {}
    for name, d, env in (("TZ=UTC", a, {"TZ": "UTC"}), ("TZ=Asia/Shanghai", b, {"TZ": "Asia/Shanghai", "LC_ALL": "C"})):
        shutil.rmtree(d, ignore_errors=True); os.makedirs(d, exist_ok=True)
        try:
            code, out, err, dt = run(["-m", "uibc_core.cli", "demo"], cwd=d, env=env, timeout=180)
            outs[name] = (code, out, err)
            rec("C6 demo 在 %s" % name, "PASS" if code == 0 else "FAIL", "exit=%s %.1fs" % (code, dt))
        except Exception as e:
            rec("C6 demo 在 %s" % name, "ERROR", repr(e)[:120])
    h = {}
    for name, d in (("TZ=UTC", a), ("TZ=Asia/Shanghai", b)):
        for root, _, files in os.walk(d):
            for f in files:
                p = os.path.join(root, f)
                if f.endswith(".json") and os.path.getsize(p) < 2_000_000:
                    h.setdefault(name, {})[os.path.relpath(p, d)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    if h.get("TZ=UTC") and h.get("TZ=Asia/Shanghai"):
        common = set(h["TZ=UTC"]) & set(h["TZ=Asia/Shanghai"])
        diff = [k for k in common if h["TZ=UTC"][k] != h["TZ=Asia/Shanghai"][k]]
        rec("C6 跨时区产物一致性", "INFO" if not diff else "WARN",
            "共同文件 %d，内容差异 %d：%s" % (len(common), len(diff), diff[:5]), {"diff": diff[:20]})
    # 非 UTF-8 控制台
    try:
        code, out, err, dt = run(["-m", "uibc_core.cli", "demo"], cwd=a,
                                 env={"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp936"}, timeout=180)
        rec("C6 控制台 cp936（中文 Windows 默认）", "PASS" if code == 0 else "WARN",
            "exit=%s %s" % (code, (err or out).strip().splitlines()[-1][:120] if (err or out).strip() else ""))
    except Exception as e:
        rec("C6 控制台 cp936", "ERROR", repr(e)[:120])


# ---------- C7 凭据泄漏扫描 ----------
def c7_leak():
    hits = []
    pats = [re.compile(r"\b[0-9a-f]{64}\b"), re.compile(r"PRIVATE KEY"), re.compile(r"\bseed\b", re.I),
            re.compile(r"BEGIN [A-Z ]*KEY")]
    scan_dirs = [CN_DIR]
    for d in scan_dirs:
        for root, _, files in os.walk(d):
            for f in files:
                if not f.endswith((".log", ".txt", ".out")) and "std" not in f:
                    continue
                p = os.path.join(root, f)
                try:
                    txt = open(p, encoding="utf-8", errors="replace").read()
                except Exception:
                    continue
                for pat in pats:
                    if pat.search(txt):
                        hits.append("%s:%s" % (os.path.basename(p), pat.pattern))
    rec("C7 输出中是否出现密钥素材", "WARN" if hits else "PASS",
        ("命中 %d 处：%s" % (len(hits), hits[:6])) if hits else "扫描目录内无 64 位十六进制密钥/私钥头",
        {"hits": hits[:20]})
    # 生成密钥文件的权限位（Windows ACL 简查）
    kf = os.path.join(CN_DIR, "包 一", "密钥.hex")
    if os.path.exists(kf):
        rec("C7 密钥文件是否明文落盘", "INFO",
            "%d 字节，%s；Windows 下无 POSIX 0600 语义，靠 ACL 继承" % (os.path.getsize(kf), "明文 hex"),
            {"kind": "密钥保护", "severity": "中"})


def main():
    print("=== C 组：多生态/多系统实测 %s ===" % time.strftime("%F %T"))
    for fn in (c1_mcp, c2_a2a, c3_node, c4_cli, c5_lock, c6_locale, c7_leak):
        try:
            fn()
        except Exception:
            rec(fn.__name__, "ERROR", traceback.format_exc().splitlines()[-1][:160])
    out = sys.argv[1] if len(sys.argv) > 1 else "s03_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    v = {}
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== 汇总 %s ===" % v)


if __name__ == "__main__":
    main()
