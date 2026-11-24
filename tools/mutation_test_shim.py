# -*- coding: utf-8 -*-
"""载体变异测试：故意把 shim 改坏，验证"我们的绿"不是空的。

为什么必须做：一套测试如果对"错误实现"也不报红，那它的绿就没有意义。
官方套件是别人的，我们改不了；但**载体（shim）是我们写的**，可以按标准变异手法逐条改坏，
然后看套件是否在**预期的那条断言**上判红。全红在预期位置 = 绿是真的。

用法：
  python tools/mutation_test_shim.py --kit <实测台目录> --repo <被测仓> [--port 9480]

做法：为每个变异体生成一份 shim 副本（只改必要字符），用 UIBC_SHIM 让一键脚本使用它，
      跑官方用例，读 summary.txt 判定；结果写 JSON。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

MUTANTS = [
    dict(
        name="M1 Content-Type 回退到旧写法",
        why="v0.4.6 修掉的老缺陷。规范要求 HTTP Content-Type == didResolutionMetadata.contentType",
        old='self._send(200, body, DOC_MEDIA)',
        new='self._send(200, body, RES_MEDIA)',
        expect="10-bindings",
        expect_fail_min=1,
    ),
    dict(
        name="M2 didResolutionMetadata 丢 contentType",
        why="contentType 是 resolution metadata 的必需项",
        old='{"didResolutionMetadata": {"contentType": DOC_MEDIA},',
        new='{"didResolutionMetadata": {},',
        expect="any",
        expect_fail_min=1,
    ),
    dict(
        name="M3 返回文档的 id 与所解析 DID 不一致",
        why="规范：didDocument.id MUST 等于被解析的 DID",
        old='        body = json.dumps({"didResolutionMetadata": {"contentType": DOC_MEDIA},',
        new='        doc = dict(doc); doc["id"] = "did:example:wrong"\n'
            '        body = json.dumps({"didResolutionMetadata": {"contentType": DOC_MEDIA},',
        expect="4-did-resolution",
        expect_fail_min=1,
    ),
    dict(
        name="M4 坏 DID 仍回 200（错误映射失效）",
        why="INVALID_DID 必须映射为 400；错误对象必须出现在 resolution metadata",
        old='            kind = "INVALID_DID" if ("invalid" in msg or "not a DID" in msg) else "NOT_FOUND"',
        new='            return self._send(200, json.dumps({"didResolutionMetadata": {"contentType": DOC_MEDIA},'
            '"didDocument": {}}, ensure_ascii=False), DOC_MEDIA)\n'
            '            kind = "INVALID_DID"',
        expect="any",
        expect_fail_min=1,
    ),
]


def mutate(src, old, new):
    if old not in src:
        return None
    return src.replace(old, new, 1)


def run_one(kit, repo, port, shim_path, out_dir, tag):
    env = dict(os.environ)
    env["UIBC_REPO"] = os.path.abspath(repo)
    env["UIBC_SHIM"] = os.path.abspath(shim_path)
    env["PYTHONIOENCODING"] = "utf-8"
    ps = os.path.join(kit, "tools", "run_official_suite.ps1")
    sh = os.path.join(kit, "tools", "run_official_suite.sh")
    cmd = (["pwsh", "-NoProfile", "-File", ps, "-Port", str(port)]
           if os.name == "nt" else ["bash", sh, "--port", str(port)])
    t0 = time.time()
    runs = os.path.join(kit, "runs")
    before = set(os.listdir(runs)) if os.path.isdir(runs) else set()
    proc = subprocess.run(cmd, cwd=kit, env=env, capture_output=True, text=True)
    dt = round(time.time() - t0, 1)
    # 只认"这次新生成"的 run 目录：启动前先记下已有名字，跑完取差集。
    # 教训：以前用"排序最后一个 *_official"，会读到上一次的 summary，把旧绿当成新绿。
    after = set(os.listdir(runs)) if os.path.isdir(runs) else set()
    new_dirs = sorted(after - before)
    latest = os.path.join(runs, new_dirs[-1]) if new_dirs else ""
    summary = ""
    if latest and os.path.isfile(os.path.join(latest, "summary.txt")):
        summary = open(os.path.join(latest, "summary.txt"), encoding="utf-8").read()
    counts = {}
    for grp in ("4-did-resolution", "10-bindings"):
        m = re.search(grp + r":\s+pass=(\d+) fail=(\d+)", summary)
        if m:
            counts[grp] = dict(pass_=int(m.group(1)), fail=int(m.group(2)))
    return dict(tag=tag, seconds=dt, exit=proc.returncode, run_dir=latest,
                counts=counts, has_summary=bool(summary), summary=summary,
                tail=(proc.stderr or "")[-500:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--port", type=int, default=9480)
    ap.add_argument("--json", default="mutants.json")
    a = ap.parse_args()

    src_path = os.path.join(a.kit, "tools", "resolver_https_shim.py")
    src = open(src_path, encoding="utf-8").read()
    mdir = os.path.join(a.kit, "mutants")
    os.makedirs(mdir, exist_ok=True)

    results = []
    # 对照：未变异的载体必须全绿。注意空 counts 不能算绿（跑挂了也会得到 0 fail）
    out = run_one(a.kit, a.repo, a.port, src_path, mdir, "M0 对照（正式 shim）")
    ok = (out["has_summary"] and len(out["counts"]) == 2
          and sum(v["fail"] for v in out["counts"].values()) == 0
          and sum(v["pass_"] for v in out["counts"].values()) >= 20)
    out["killed"] = False
    out["verdict"] = "CONTROL-OK" if ok else "CONTROL-BAD"
    results.append(out)
    print("[%s] %s  %s" % (out["verdict"], out["tag"], out["counts"]))

    for i, mut in enumerate(MUTANTS, 1):
        mutated = mutate(src, mut["old"], mut["new"])
        if mutated is None:
            print("[SKIP] %s 找不到锚点，需更新变异脚本" % mut["name"])
            results.append(dict(tag=mut["name"], verdict="SKIP-ANCHOR"))
            continue
        path = os.path.join(mdir, "mutant_%d.py" % i)
        open(path, "w", encoding="utf-8").write(mutated)
        out = run_one(a.kit, a.repo, a.port + i, path, mdir, mut["name"])
        out.update(why=mut["why"], expect=mut["expect"])
        if not out["has_summary"]:
            # 变异体把 shim 改到起不来（或冒烟被拦）→ 没有新 run 目录/总结。这不算"击杀"，
            # 因为套件根本没跑起来；如实标 NO-RUN，人工看 tail 再决定。
            out["killed"] = False
            out["verdict"] = "NO-RUN"
            results.append(out)
            print("[NO-RUN] %s  exit=%s tail=%s" % (mut["name"], out["exit"], (out["tail"] or "").strip()[-200:]))
            continue
        fails = {k: v["fail"] for k, v in out["counts"].items()}
        hit = (out["counts"].get(mut["expect"], {}).get("fail", 0) >= mut["expect_fail_min"]
               if mut["expect"] != "any" else sum(fails.values()) >= mut["expect_fail_min"])
        out["killed"] = bool(hit)
        out["verdict"] = "KILLED" if hit else "SURVIVED"
        results.append(out)
        print("[%s] %s  fails=%s" % (out["verdict"], mut["name"], fails))

    json.dump(results, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_sur = sum(1 for r in results if r.get("verdict") == "SURVIVED")
    n_norun = sum(1 for r in results if r.get("verdict") == "NO-RUN")
    ctl_ok = results[0].get("verdict") == "CONTROL-OK"
    print("\n=== 对照 %s；变异得分：击杀 %d / 存活 %d / 未跑起来 %d ==="
          % ("OK" if ctl_ok else "BAD", len(MUTANTS) - n_sur - n_norun, n_sur, n_norun))
    return 0 if (ctl_ok and n_sur == 0 and n_norun == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
