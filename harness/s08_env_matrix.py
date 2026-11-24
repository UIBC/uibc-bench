# -*- coding: utf-8 -*-
"""场景组 M：环境矩阵（把"未测 10 项"从一句免责声明，变成逐条产出的用例）。

为什么要单独做一组：
对外材料里写"未测 macOS/ARM64/容器/离线/代理 MITM/弱网/磁盘满/24h/多租户"，
但那是**散文**，读者无法核对"你到底探过没有"。本组把每一项变成一条用例：
能做的就真做（PASS/FAIL 都有实测），做不了的必须给出**探测证据**再记 SKIP，
而不是一句"没条件"糊过去。

判定约定：
- INFO：本机属性（记录下来，供比对，不代表通过）
- PASS/FAIL：真的执行了某项环境条件
- SKIP：本机无法构造该条件，且 note 里必须写清"探测到了什么、为什么做不到"
"""
import json, os, platform, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
import _subject  # noqa: E402  被测仓只从一个入口定位，见 _subject.py 的历史说明
REPO = _subject.resolve()
PY = sys.executable
RESULTS = []


def rec(case, verdict, note="", extra=None):
    RESULTS.append(dict(case=case, verdict=verdict, note=note, extra=extra or {}))
    print("[%-5s] %-40s %s" % (verdict, case, note))


def run(args, cwd=REPO, timeout=120, env=None):
    e = dict(os.environ); e.update(env or {}); e.setdefault("PYTHONIOENCODING", "utf-8")
    e["PYTHONPATH"] = REPO + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    t0 = time.time()
    p = subprocess.run([PY] + args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env=e)
    return p.returncode, (p.stdout or ""), (p.stderr or ""), time.time() - t0


def repo_ready():
    """依赖被测仓库的三项（M3/M4/M6 要真跑 CLI）先体检：缺仓库就 BLOCKED，别抛 ERROR。"""
    return os.path.isdir(REPO) and not os.path.islink(REPO)


# ---------- M0 / M1 平台属性 ----------
def m0_platform():
    rec("M0 平台与架构", "INFO",
        "%s / %s / %d 核 / 解释器 %s" % (platform.system(), platform.machine(), os.cpu_count(),
                                        platform.python_version()),
        {"kind": "环境属性"})


def m1_python():
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 10) and sys.implementation.name == "cpython"
    rec("M1 Python 版本门槛", "PASS" if ok else "FAIL",
        "%s %s（要求 CPython ≥ 3.10）" % (sys.implementation.name, platform.python_version()),
        {"kind": "兼容性"})


# ---------- M2 大小写敏感 ----------
def m2_case_sensitivity():
    d = tempfile.mkdtemp(prefix="case_")
    try:
        a = os.path.join(d, "Probe.txt"); b = os.path.join(d, "probe.txt")
        open(a, "w").write("A")
        sensitive = not os.path.exists(b)
        open(b, "w").write("b")
        same = None
        try:
            same = (open(a).read() == open(b).read())
        except Exception:
            same = None
        rec("M2 文件系统大小写敏感", "INFO",
            "%s（两个名字是否同一文件：%s）" % ("敏感（区分大小写）" if sensitive else "不敏感（Windows 默认）",
                                            "是" if same else "否"),
            {"kind": "环境属性", "case_sensitive": sensitive})
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------- M3 非 ASCII + 空格路径 ----------
def m3_unicode_path():
    if not repo_ready():
        rec("M3 中文+空格路径端到端","BLOCKED","缺被测仓库（先 first_run.py 或 setup.ps1 克隆），本项无法执行"); return
    d = tempfile.mkdtemp(prefix="uni_")
    p = os.path.join(d, "实测 中国信通院 场景", "并发", "只读")
    os.makedirs(p, exist_ok=True)
    code, out, err, dt = run(["-m", "uibc_core.cli", "demo"], cwd=p)
    tail = ((out or err).strip().splitlines() or [""])[-1][:90]
    rec("M3 中文+空格路径端到端", "PASS" if code == 0 else "FAIL",
        "exit=%s %.1fs %s" % (code, dt, tail), {"kind": "部署现实", "path": p})


# ---------- M4 控制台编码 ----------
def m4_console_encoding():
    if not repo_ready():
        rec("M4 控制台编码下 CLI","BLOCKED","缺被测仓库，本项无法执行"); return
    enc = "cp936" if sys.platform == "win32" else "utf-8"
    code, out, err, dt = run(["-m", "uibc_core.cli", "demo"],
                             env={"PYTHONIOENCODING": enc})
    tail = ((out or err).strip().splitlines() or [""])[-1][:90]
    rec("M4 控制台编码 %s 下 CLI" % enc, "PASS" if code == 0 else "FAIL",
        "exit=%s %.1fs %s" % (code, dt, tail), {"kind": "本地化", "encoding": enc})


# ---------- M5 容器化 ----------
def m5_container():
    marks = []
    for f in ("/.dockerenv", "/run/.containerenv"):
        if os.path.exists(f):
            marks.append(f)
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        marks.append("KUBERNETES_SERVICE_HOST")
    tag = "容器内" if marks else "不在容器内"
    rec("M5 容器化环境", "INFO", "%s（探测标记：%s）" % (tag, ", ".join(marks) or "无"),
        {"kind": "环境属性", "in_container": bool(marks)})


# ---------- M6 只读 TMPDIR 下的行为 ----------
def m6_readonly_tmp():
    if not repo_ready():
        rec("M6 只读临时目录下运行","BLOCKED","缺被测仓库，本项无法执行"); return
    d = tempfile.mkdtemp(prefix="ro_")
    try:
        os.chmod(d, 0o555) if os.name == "posix" else None
        if os.name == "nt":
            subprocess.run(["icacls", d, "/deny", "%USERNAME%:(W,AD,WD)"], capture_output=True)
        code, out, err, dt = run(["-m", "uibc_core.cli", "demo"], env={"TMPDIR": d, "TEMP": d, "TMP": d})
        blob = (out + err)
        crash = "Traceback (most recent call last)" in blob
        if code == 0:
            rec("M6 只读临时目录下运行", "PASS", "exit=0 %.1fs（未受影响，不写临时目录）" % dt)
        elif crash:
            rec("M6 只读临时目录下运行", "WARN",
                "写不进临时目录时抛 Python 栈（未转成友好错误）；exit=%s" % code,
                {"kind": "健壮性", "tail": blob.strip().splitlines()[-3:]})
        else:
            rec("M6 只读临时目录下运行", "PASS", "exit=%s 且为干净报错，非栈" % code)
    finally:
        try:
            os.chmod(d, 0o755) if os.name == "posix" else None
            subprocess.run(["icacls", d, "/reset"], capture_output=True)
        except Exception:
            pass
        shutil.rmtree(d, ignore_errors=True)


# ---------- M7–M10 构造能力探测（做不到就 SKIP，但必须给证据） ----------
def m7_offline():
    ev = []
    try:
        import socket
        socket.create_connection(("github.com", 443), timeout=6).close()
        ev.append("外网可达（说明没有处于离线）")
    except Exception as e:
        ev.append("外网不可达：%r" % (repr(e)[:60],))
    if os.name == "posix":
        p = subprocess.run(["iptables", "-L"], capture_output=True, text=True)
        ev.append("iptables 可用" if p.returncode == 0 else "iptables 不可用（无 root/netns 权限）")
    else:
        p = subprocess.run(["netsh", "advfirewall", "show", "allprofiles"], capture_output=True, text=True)
        ev.append("netsh 防火墙查询可用" if p.returncode == 0 else "netsh 不可用")
    rec("M7 离线/断网环境", "SKIP",
        "无法安全构造「断网」（会切断本机与平台/仓库的链路）：" + "；".join(ev)[:180],
        {"kind": "未测项", "reason": "no-safe-network-isolation"})


def m8_proxy_mitm():
    envs = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE")}
    present = [k for k, v in envs.items() if v]
    rec("M8 企业代理 MITM", "SKIP",
        "当前环境代理变量：%s；注入 MITM 需要自签根证书与中间人代理（本机无该条件）"
        % ("、".join(present) if present else "均未设置"),
        {"kind": "未测项", "reason": "no-mitm-proxy", "env": envs})


def m9_weak_network():
    ev = []
    if os.name == "posix":
        p = subprocess.run(["tc", "qdisc", "show"], capture_output=True, text=True)
        ev.append("tc 可用" if p.returncode == 0 else "tc 不可用/无权限：%s" % (p.stderr.strip()[:60] or "command missing"))
        ev.append("root=%s" % (os.geteuid() == 0 if hasattr(os, "geteuid") else "n/a"))
    else:
        ev.append("Windows 无 tc；需要第三方弱网工具（Clumsy/NetLimiter），本机未装")
    rec("M9 弱网/高延迟", "SKIP", "无法构造可控弱网：" + "；".join(ev)[:180],
        {"kind": "未测项", "reason": "no-traffic-shaping"})


def m10_disk_full():
    ev = []
    try:
        free = shutil.disk_usage(KIT).free
        ev.append("当前空闲 %.1fGB（远未满）" % (free / (1024 ** 3)))
    except Exception as e:
        ev.append("无法读磁盘：%r" % (repr(e)[:40],))
    if os.name == "posix":
        p = subprocess.run(["losetup", "-f"], capture_output=True, text=True)
        ev.append("loop 设备可用（可造小文件系统）" if p.returncode == 0 and p.stdout.strip()
                  else "loop 设备不可用（需 root）")
    else:
        ev.append("Windows 需管理员+虚拟磁盘，本机未做")
    rec("M10 磁盘写满", "SKIP", "无法安全构造「磁盘写满」：" + "；".join(ev)[:180],
        {"kind": "未测项", "reason": "no-disk-fill"})


def m11_long_run():
    rec("M11 24 小时长跑", "SKIP",
        "本轮未做长跑（单次运行最长 8.5 分钟）；如需，用 `bench.py run` 定时重复 + compare_baseline 做漂移检测",
        {"kind": "未测项", "reason": "no-24h-run"})


def main():
    print("=== M 组：环境矩阵 %s ===" % time.strftime("%F %T"))
    only = (sys.argv[2] if len(sys.argv) > 2 else "").lower()
    plan = [("m0", m0_platform), ("m1", m1_python), ("m2", m2_case_sensitivity),
            ("m3", m3_unicode_path), ("m4", m4_console_encoding), ("m5", m5_container),
            ("m6", m6_readonly_tmp), ("m7", m7_offline), ("m8", m8_proxy_mitm),
            ("m9", m9_weak_network), ("m10", m10_disk_full), ("m11", m11_long_run)]
    for k, fn in plan:
        if only and k not in only:
            continue
        try:
            fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            rec("M-%s" % k, "ERROR", repr(e)[:150])
    out = sys.argv[1] if len(sys.argv) > 1 else "s08_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    v = {}
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== 汇总 %s ===" % v)


if __name__ == "__main__":
    main()
