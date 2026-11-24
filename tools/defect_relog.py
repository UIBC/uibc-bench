# -*- coding: utf-8 -*-
"""逐条复跑日志：把「缺陷已修」从台账叙述变成可复跑、带哈希的日志文件。

背景：全文级复核连着七轮把 38 号 S4 判「夸大」，理由始终是「未提供逐条缺陷复跑日志文件」。
台账（defects_ledger.md）只写了「验证：…」，那不是日志。本工具把**现在真能跑**的检查当场重跑，
每条落一个 .log（含命令、退出码、耗时、stdout/stderr、sha256），并出 index.json。

纪律：
- 只跑现在真的能跑的检查；跑不了的标 NOT_RERUN 并写明理由，不假装跑过。
- 日志逐字记录 stdout/stderr，不裁剪成「漂亮结论」。
- index.json 带每份日志 sha256，外人可核。

用法：python tools/defect_relog.py <out_dir> --src <38_九门自查.md> [--bench <bench_root>]
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--src", default="")
ap.add_argument("--bench", default="")
a = ap.parse_args()

OUT = os.path.abspath(a.out)
BENCH = os.path.abspath(a.bench) if a.bench else os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PY = sys.executable
os.makedirs(OUT, exist_ok=True)


def sha(p):
    h = hashlib.sha256()
    with io.open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest().upper()


def run_log(rid, defect, cmd, timeout=240):
    t0 = time.time()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    note = ""
    try:
        pr = subprocess.run(cmd, cwd=BENCH, capture_output=True, text=True, timeout=timeout,
                            env=env, encoding="utf-8", errors="replace")
        out, err, code = pr.stdout or "", pr.stderr or "", pr.returncode
    except subprocess.TimeoutExpired as e:
        out, err, code = (e.stdout or ""), (e.stderr or ""), "TIMEOUT"
        note = "超时 %ss" % timeout
    dur = round(time.time() - t0, 1)
    log = os.path.join(OUT, rid + ".log")
    io.open(log, "w", encoding="utf-8").write(
        "# %s  %s\n# cmd: %s\n# cwd: %s\n# exit: %s  elapsed: %ss  %s\n\n[stdout]\n%s\n[stderr]\n%s\n"
        % (rid, defect, " ".join(cmd), BENCH, code, dur, note, out, err))
    return {"id": rid, "defect": defect, "cmd": " ".join(cmd), "exit": code, "elapsed_s": dur,
            "log": os.path.basename(log), "sha256": sha(log),
            "stdout_tail": out.strip().splitlines()[-3:]}


rows = []

# R1 缺陷 A：端口写死。真占 8080，再看 serve_any 是否自动换端口并仍能服务。
probe_port = os.path.join(OUT, "_probe_port.py")
io.open(probe_port, "w", encoding="utf-8").write(r'''
import sys, socket, urllib.request
sys.path.insert(0, r"%s")
from harness._portutil import serve_any
from http.server import BaseHTTPRequestHandler

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *args): pass

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(("127.0.0.1", 8080)); s.listen(1)
srv, port = serve_any(H, 8080, tries=6)
code = urllib.request.urlopen("http://127.0.0.1:%%d/" %% port, timeout=3).status
print("OCCUPIED=8080 ACTUAL_PORT=%%d AUTO_SWITCH=%%s HTTP=%%d" %% (port, port != 8080, code))
s.close(); srv.shutdown()
''' % BENCH)
rows.append(run_log("R1_defect_A_port", "缺陷 A：端口写死 8080/8443", [PY, probe_port], timeout=60))

# R2 缺陷 B：符号链接/越界证物。用被测仓自身判据（islink 或 realpath 出 evidence 根即失败）。
ev_root = os.path.join(BENCH, "uibc-core-public", "evidence")
if os.path.isdir(ev_root):
    probe_sym = os.path.join(OUT, "_probe_symlink.py")
    io.open(probe_sym, "w", encoding="utf-8").write(r'''
import os, sys
root = r"%s"; root_real = os.path.realpath(root)
n = sym = outside = 0
for dp, _d, fs in os.walk(root):
    for f in fs:
        p = os.path.join(dp, f); n += 1
        if os.path.islink(p): sym += 1; continue
        if not os.path.realpath(p).startswith(root_real + os.sep): outside += 1
print("EVIDENCE_FILES=%%d SYMLINKS=%%d OUTSIDE_ROOT=%%d" %% (n, sym, outside))
sys.exit(0 if sym == 0 and outside == 0 else 1)
''' % ev_root)
    rows.append(run_log("R2_defect_B_symlink", "缺陷 B：符号链接破坏对方自审", [PY, probe_sym], timeout=120))
else:
    rows.append({"id": "R2_defect_B_symlink", "defect": "缺陷 B：符号链接破坏对方自审",
                 "exit": "NOT_RERUN", "note": "本地公开快照无 evidence/ 目录，判据无法就地复跑"})

# R3 版本口径漂移（真实工具，非模拟）
drift = os.path.join(BENCH, "tools", "check_version_drift.py")
if os.path.exists(drift):
    rows.append(run_log("R3_version_drift", "缺陷：版本口径漂移",
                        [PY, drift, os.path.join(BENCH, "uibc-core-public")], timeout=120))

# R4 断言清单强制覆盖（缺陷 #22：清单静默截断 / 标题被跳过）
inv = os.path.join(BENCH, "tools", "claim_inventory.py")
if a.src and os.path.exists(inv):
    rows.append(run_log("R4_claim_must", "缺陷 #22：清单静默截断 / 标题跳过",
                        [PY, inv, "--src", os.path.abspath(a.src),
                         "--out", os.path.join(OUT, "_claims_relog.json"), "--must", "M1–M4"],
                        timeout=120))

rows.append({"id": "R5_defect_C_D_E_F_G", "defect": "缺陷 C/D/E/F/G（环境慢、跨 OS 语义、用例消失、偶发、行尾改写）",
             "exit": "NOT_RERUN",
             "note": "五条都要整套基线（141 例约 8.5 分钟）或云主机环境；本轮预算内未复跑，不冒充跑过"})
rows.append({"id": "R6_late_numbered", "defect": "看板编号缺陷 #8–#18（shim Content-Type、endpoint 000、import 静默回退、证书自举等）",
             "exit": "NOT_RERUN",
             "note": "需重建验收环境（自签证书 / 故意坏 endpoint / 错误 UIBC_REPO），属专项复现，本轮未做"})

idx = os.path.join(OUT, "index.json")
doc = {
    "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "bench": BENCH, "python": PY, "input_md": os.path.abspath(a.src) if a.src else "",
    "discipline": "只记录本轮真跑过的检查；跑不了的标 NOT_RERUN 并写理由；日志逐字含 stdout/stderr。",
    "checks": rows,
}
io.open(idx, "w", encoding="utf-8").write(json.dumps(doc, ensure_ascii=False, indent=2))
print("checks=%d -> %s" % (len(rows), idx))
for r in rows:
    print("  %-22s exit=%s  %s" % (r["id"], r.get("exit"), " ".join(r.get("stdout_tail", []))[:90]))
