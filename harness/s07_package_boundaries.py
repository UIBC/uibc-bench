# -*- coding: utf-8 -*-
"""场景组 G：包/证据层的对抗性边界。

上线后最容易被忽略的不是"能不能验过"，而是"验的时候会不会读包外的文件、
会不会被畸形输入打崩、会不会在只读环境写坏东西"。本组只测这些。
"""
import json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
REPO = os.path.join(KIT, "uibc-core-public")
PY = sys.executable
RESULTS = []


def rec(case, verdict, note="", extra=None):
    RESULTS.append(dict(case=case, verdict=verdict, note=note, extra=extra or {}))
    print("[%-5s] %-44s %s" % (verdict, case, note))


def _env():
    """把被测仓库放进 PYTHONPATH：不依赖"这台机器刚好装过 uibc_core"，
    换解释器/换机器（含 venv）也能跑同一套用例。"""
    e = dict(os.environ)
    e["PYTHONPATH"] = REPO + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    return e


def cli(*args, cwd=None, timeout=120):
    return subprocess.run([PY, "-m", "uibc_core.cli"] + list(args), cwd=cwd, env=_env(),
                          capture_output=True, text=True, timeout=timeout)


def build_pkg(root, n_evidence=1):
    os.makedirs(root, exist_ok=True)
    k = os.path.join(root, "k.hex")
    cli("keygen", "--out", k, cwd=root)
    cli("init", "p", cwd=root)
    cli("register", "p", "--agent-id", "sec-01", "--owner", "安全边界", cwd=root)
    for i in range(n_evidence):
        f = os.path.join(root, "ev%d.txt" % i)
        open(f, "w", encoding="utf-8").write("evidence %d" % i)
        cli("evidence", "p", "--file", os.path.basename(f), "--type", "OUTPUT", cwd=root)
    cli("submit", "p", "--key", k, cwd=root)
    return os.path.join(root, "p"), k


def g1_traversal():
    """证据索引里塞一个 ../ 路径，并带上包外文件的真实哈希。
    如果校验器读了包外文件且哈希匹配，就说明围栏失守——这比"报不报错"更有说服力。"""
    import hashlib
    root = tempfile.mkdtemp(prefix="sec_trav_")
    pkg, key = build_pkg(root, n_evidence=1)
    outside = os.path.join(root, "outside_secret.txt")
    body = b"this file lives OUTSIDE the package and must never be read"
    with open(outside, "wb") as f:
        f.write(body)
    digest = hashlib.sha256(body).hexdigest()

    idx = os.path.join(pkg, "evidence", "index.json")
    if not os.path.exists(idx):
        rec("G1 manifest 路径穿越(../)", "BLOCKED", "包内没有 evidence/index.json")
        shutil.rmtree(root, ignore_errors=True)
        return
    data = json.load(open(idx, encoding="utf-8"))
    items = data.get("items") or data.get("entries") or []
    if not items:
        rec("G1 manifest 路径穿越(../)", "BLOCKED", "index.json 里没有条目结构"); shutil.rmtree(root, ignore_errors=True); return
    injected = dict(items[0])
    injected["path"] = "../outside_secret.txt"
    for k in ("sha256", "hash", "digest", "content_hash"):
        if k in injected:
            injected[k] = digest
            if k == "digest":
                injected[k] = "sha256:" + digest
    items.append(injected)
    data["items"] = items if "items" in data else None
    if "entries" in data:
        data["entries"] = items
        data.pop("items", None)
    json.dump(data, open(idx, "w", encoding="utf-8"), ensure_ascii=False)

    p = cli("verify", pkg, "--key", key, cwd=root)
    out = p.stdout + p.stderr
    accepted = p.returncode == 0 and '"result": "PASS"' in out
    rec("G1 证据索引路径穿越(../)", "FAIL" if accepted else "PASS",
        "exit=%s 结果=%s；包外条目哈希已按真实内容填写，被接受即证明读了包外文件" % (
            p.returncode, "PASS(围栏失守)" if accepted else "未通过/被拒"),
        {"kind": "路径围栏", "severity": "高" if accepted else "-"})
    shutil.rmtree(root, ignore_errors=True)


def g2_strict_json():
    root = tempfile.mkdtemp(prefix="sec_dup_")
    pkg, key = build_pkg(root)
    mf = os.path.join(pkg, "manifest.json")
    raw = open(mf, encoding="utf-8").read().strip()
    # 重复成员名：把最后一个 } 前插入一个重复键
    if raw.endswith("}"):
        dup = raw[:-1].rstrip()
        sep = "" if dup.endswith("{") else ","
        raw2 = dup + sep + '"agent":"duplicated-name"\n}'
        open(mf, "w", encoding="utf-8").write(raw2)
        p = cli("verify", pkg, "--key", key, cwd=root)
        rec("G2 重复 JSON 成员名", "PASS" if p.returncode != 0 else "FAIL",
            "exit=%s（严格序列化应拒收）" % p.returncode,
            {"kind": "严格序列化", "severity": "中"})
    shutil.rmtree(root, ignore_errors=True)


def g3_weird_identifiers():
    root = tempfile.mkdtemp(prefix="sec_id_")
    k = os.path.join(root, "k.hex")
    cli("keygen", "--out", k, cwd=root)
    cases = [
        ("超长 10000 字符", "a" * 10000),
        ("控制字符", "a\x01b"),
        ("emoji", "智能体🤖-01"),
        ("双向文本", "abc\u202e\"evil"),
        ("路径样串", "../../etc/passwd"),
        ("空串", ""),
        ("保留设备名", "CON"),
    ]
    expect = {"超长 10000 字符": "INFO", "控制字符": "WARN", "emoji": "INFO",
              "双向文本": "WARN", "路径样串": "INFO", "空串": "WARN", "保留设备名": "INFO"}
    for name, aid in cases:
        p = os.path.join(root, "p_" + str(abs(hash(name))))
        cli("init", p, cwd=root)
        r = cli("register", p, "--agent-id", aid, "--owner", "x", cwd=root, timeout=60)
        accepted = r.returncode == 0
        want = expect.get(name, "INFO")
        # 控制字符/双向文本/空串被接受 = 标识符校验缺失，判 WARN；其余只记录
        verdict = ("PASS" if not accepted else want) if want == "WARN" else ("INFO" if accepted else "PASS")
        rec("G3 agent_id %s" % name, verdict,
            "exit=%s %s%s" % (r.returncode,
                              (r.stderr or r.stdout).strip().splitlines()[-1][:60] if (r.stderr or r.stdout).strip() else "",
                              "（被接受，标识符校验偏松）" if accepted and want == "WARN" else ""),
            {"kind": "标识符校验", "severity": "中" if verdict == "WARN" else "-"})
    shutil.rmtree(root, ignore_errors=True)


def g4_ro_and_concurrent():
    root = tempfile.mkdtemp(prefix="sec_ro_")
    pkg, key = build_pkg(root)
    before = {}
    for dp, _, fs in os.walk(pkg):
        for f in fs:
            p = os.path.join(dp, f)
            before[os.path.relpath(p, pkg)] = (os.path.getsize(p), os.path.getmtime(p))
    # 并发 10 个 verify 同一包（只读路径）
    import threading
    res = {"ok": 0, "err": [], "ms": []}
    lk = threading.Lock()

    def one():
        t0 = time.time()
        r = cli("verify", pkg, "--key", key, cwd=root, timeout=120)
        with lk:
            if r.returncode in (0, 1):
                res["ok"] += 1
            else:
                res["err"].append(r.returncode)
            res["ms"].append((time.time() - t0) * 1000)

    ths = [threading.Thread(target=one) for _ in range(10)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    rec("G4 10 并发只读校验", "PASS" if not res["err"] else "FAIL",
        "ok=%d err=%s 中位=%.0fms" % (res["ok"], res["err"], sorted(res["ms"])[len(res["ms"]) // 2]),
        {"kind": "并发", "severity": "中" if res["err"] else "-"})
    after = {}
    for dp, _, fs in os.walk(pkg):
        for f in fs:
            p = os.path.join(dp, f)
            after[os.path.relpath(p, pkg)] = (os.path.getsize(p), os.path.getmtime(p))
    changed = [k for k in before if before[k] != after.get(k)]
    added = [k for k in after if k not in before]
    rec("G4 校验是否写了包目录", "PASS" if not changed and not added else "WARN",
        "改动 %s 新增 %s（校验应只读；有写入说明副作用）" % (changed[:3], added[:3]),
        {"kind": "只读性", "severity": "中" if changed or added else "-"})
    shutil.rmtree(root, ignore_errors=True)


def g5_tz_and_clock():
    outs = {}
    for tz in ("UTC", "Asia/Shanghai", "Pacific/Kiritimati"):
        root = tempfile.mkdtemp(prefix="sec_tz_")
        env = dict(os.environ, TZ=tz)
        k = os.path.join(root, "k.hex")
        subprocess.run([PY, "-m", "uibc_core.cli", "keygen", "--out", k], cwd=root, capture_output=True, env=env)
        subprocess.run([PY, "-m", "uibc_core.cli", "init", "p"], cwd=root, capture_output=True, env=env)
        subprocess.run([PY, "-m", "uibc_core.cli", "register", "p", "--agent-id", "tz-01", "--owner", "tz"],
                       cwd=root, capture_output=True, env=env)
        f = os.path.join(root, "e.txt"); open(f, "w", encoding="utf-8").write("x")
        subprocess.run([PY, "-m", "uibc_core.cli", "evidence", "p", "--file", "e.txt", "--type", "OUTPUT"],
                       cwd=root, capture_output=True, env=env)
        subprocess.run([PY, "-m", "uibc_core.cli", "submit", "p", "--key", k], cwd=root, capture_output=True, env=env)
        r = subprocess.run([PY, "-m", "uibc_core.cli", "verify", "p"], cwd=root, capture_output=True, text=True, env=env)
        outs[tz] = (r.returncode, "PASS" if '"result": "PASS"' in r.stdout else ("INCONCLUSIVE" if "INCONCLUSIVE" in r.stdout else "?"))
        shutil.rmtree(root, ignore_errors=True)
    vals = {v[1] for v in outs.values()}
    rec("G5 三时区判定一致", "PASS" if len(vals) == 1 else "FAIL",
        str(outs), {"kind": "时区", "severity": "中" if len(vals) > 1 else "-"})

    # 时钟回拨：把系统时间概念换成"未来"的事件再验
    root = tempfile.mkdtemp(prefix="sec_future_")
    pkg, key = build_pkg(root)
    mf = os.path.join(pkg, "manifest.json")
    m = json.load(open(mf, encoding="utf-8"))
    if isinstance(m.get("events"), list) and m["events"]:
        m["events"][-1]["timestamp"] = "2099-01-01T00:00:00Z"
        json.dump(m, open(mf, "w", encoding="utf-8"), ensure_ascii=False)
        p = cli("verify", pkg, "--key", key, cwd=root)
        rec("G5 未来时间戳事件", "PASS" if p.returncode != 0 else "WARN",
            "exit=%s（篡改时间戳后应不再 PASS）" % p.returncode,
            {"kind": "时间语义", "severity": "中" if p.returncode == 0 else "-"})
    shutil.rmtree(root, ignore_errors=True)


def g6_big_evidence():
    root = tempfile.mkdtemp(prefix="sec_big_")
    k = os.path.join(root, "k.hex")
    cli("keygen", "--out", k, cwd=root)
    cli("init", "p", cwd=root)
    cli("register", "p", "--agent-id", "big-01", "--owner", "big", cwd=root)
    big = os.path.join(root, "big.bin")
    with open(big, "wb") as f:
        f.write(b"\0" * (50 * 1024 * 1024))
    t0 = time.time()
    r = cli("evidence", "p", "--file", "big.bin", "--type", "OUTPUT", cwd=root, timeout=300)
    dt = time.time() - t0
    rec("G6 50MB 证据文件入包", "PASS" if r.returncode == 0 else "FAIL",
        "exit=%s 耗时 %.1fs（只算哈希，不应整包复制）" % (r.returncode, dt),
        {"kind": "大文件", "severity": "低"})
    cli("submit", "p", "--key", k, cwd=root, timeout=300)
    t0 = time.time()
    v = cli("verify", "p", cwd=root, timeout=300)
    rec("G6 50MB 证据包校验", "PASS" if v.returncode in (0, 1) else "FAIL",
        "exit=%s 耗时 %.1fs" % (v.returncode, time.time() - t0))
    shutil.rmtree(root, ignore_errors=True)


def preflight():
    """先确认被测 CLI 在当前解释器里真的能跑起来。
    否则会出现最危险的情况：解释器缺依赖 → CLI 非零退出 → 被我们当成"拒绝 → PASS"的假绿灯。
    （2026-11-23 用 Python 3.12 实跑时真的发生过一次，故在此设门。）"""
    if not os.path.isdir(REPO):
        rec("G0 环境自检", "BLOCKED", "未找到 uibc-core-public，先执行 .\\setup.ps1")
        return False
    # 注意：不能用 --help 做预检——它不加载加密库，会给出"能跑"的假象；
    # 必须跑一条真的会产生密钥的命令（keygen），才能确认依赖齐全。
    d = tempfile.mkdtemp(prefix="g0_probe_")
    k = os.path.join(d, "k.hex")
    r = subprocess.run([PY, "-m", "uibc_core.cli", "keygen", "--out", k], cwd=d, env=_env(),
                       capture_output=True, text=True, timeout=120)
    err = (r.stderr or "")
    ok = r.returncode == 0 and os.path.exists(k) and not ("No module named" in err or "ModuleNotFoundError" in err)
    shutil.rmtree(d, ignore_errors=True)
    if not ok:
        first = ([l for l in err.strip().splitlines() if l.strip()] or ["(无输出)"])[-1][:120]
        rec("G0 环境自检", "BLOCKED",
            "当前解释器 %s 跑不起被测 CLI（缺依赖或仓库不全）：%s" % (PY, first))
        return False
    rec("G0 环境自检", "PASS", "%s 可用" % os.path.basename(PY))
    return True


def main():
    print("=== G 组：包与证据层对抗边界 %s ===" % time.strftime("%F %T"))
    if preflight():
        for fn in (g1_traversal, g2_strict_json, g3_weird_identifiers, g4_ro_and_concurrent, g5_tz_and_clock, g6_big_evidence):
            try:
                fn()
            except Exception as e:
                import traceback; traceback.print_exc()
                rec(fn.__name__, "ERROR", repr(e)[:150])
    out = sys.argv[1] if len(sys.argv) > 1 else "s07_results.json"
    json.dump(RESULTS, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    v = {}
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== 汇总 %s ===" % v)


if __name__ == "__main__":
    main()
