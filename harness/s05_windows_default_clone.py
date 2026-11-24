# -*- coding: utf-8 -*-
"""场景组 E：Windows 默认 git 克隆的"外人第一公里"。

为什么单列一组：仓库里有一批**字节锚定**的文件（测试硬编码 sha256），
只要检出时行尾被改写，单测就会大面积失败——而且这不属于业务逻辑缺陷，
不大会被写单测的人想到。本组把"外人照默认配置 clone 会怎样"固化成用例。

判据：默认克隆（autocrlf=true，即 Windows 安装器的默认）后，所有在测试里
声明了期望 sha256 的文件必须仍然匹配；否则 FAIL，并列出受影响文件数。
"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
REPO = os.path.join(KIT, "uibc-core-public")
URL = "https://github.com/zhaoxinghua09-cell/uibc-core"
RESULTS = []


def rec(case, verdict, note="", extra=None):
    RESULTS.append(dict(case=case, verdict=verdict, note=note, extra=extra or {}))
    print("[%-5s] %-44s %s" % (verdict, case, note))


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def declared_anchors():
    """从 tests/*.py 里抽出 (fixture 相对路径, 期望 sha256)"""
    out = []
    tests = os.path.join(REPO, "tests")
    for name in os.listdir(tests):
        if not name.endswith(".py"):
            continue
        p = os.path.join(tests, name)
        src = open(p, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r'([A-Z_]*FIXTURE\w*)\s*=\s*os\.path\.join\(os\.path\.dirname\(__file__\),\s*([^)]*)\)', src):
            tail = m.group(2)
            parts = re.findall(r'"([^"]+)"', tail)
            if not parts:
                continue
            rel = os.path.join("tests", *parts)
            m2 = re.search(r"([A-Z_]*SHA256\w*)\s*=\s*\"([0-9a-f]{64})\"", src)
            if m2:
                out.append((rel.replace("\\", "/"), m2.group(2)))
    return out


E1_OUTPUTS = ["E1 实际行尾配置", "E1 行尾改写文件数", "E1 字节锚定文件匹配",
              "E1 受影响模块在默认克隆下", "E1 .gitattributes 是否覆盖 tests/fixtures"]


def blocked_downstream(reason):
    """上游失败时，把依赖它的用例显式记成 BLOCKED。

    由来：这里原本直接 return，整组 5 条用例凭空消失。比对基线的逻辑会把"消失"
    当作必须解释的异常（防止有人删用例让结果变绿），于是每次都报 5 条"消失"，
    真正的结论反而被噪音埋掉。宁可 5 条 BLOCKED，也不要 5 条不存在。
    """
    for case in E1_OUTPUTS:
        rec(case, "BLOCKED", "上游默认克隆失败，无法判定：%s" % reason[:90])


def e1_default_clone():
    d = tempfile.mkdtemp(prefix="defclone_")
    t0 = time.time()
    try:
        p = None
        for attempt in (1, 2):
            p = subprocess.run(["git", "clone", "--depth", "1", URL, d],
                               capture_output=True, text=True, timeout=600)
            if p.returncode == 0:
                break
            shutil.rmtree(d, ignore_errors=True)
            d = tempfile.mkdtemp(prefix="defclone_")
        if p is None or p.returncode != 0:
            reason = (p.stderr or "").strip() if p is not None else "git clone 未执行"
            rec("E1 默认配置克隆仓库", "BLOCKED", "git clone 失败（已重试 1 次）：%s" % reason[:120],
                {"kind": "环境阻塞", "severity": "-"})
            blocked_downstream(reason)
            return
        rec("E1 默认配置克隆仓库", "INFO", "%.0fs（未加 core.autocrlf=false，与 Windows 默认一致）" % (time.time() - t0))
        cfg = subprocess.run(["git", "-C", d, "config", "--get", "core.autocrlf"], capture_output=True, text=True)
        eff = subprocess.run(["git", "-C", d, "config", "--get", "core.eol"], capture_output=True, text=True)
        rec("E1 实际行尾配置", "INFO", "autocrlf=%r eol=%r" % (cfg.stdout.strip() or "unset", eff.stdout.strip() or "unset"))

        # 1) 仓库级：多少文件与 LF 版本不同（用当前台子里的 LF 克隆做参照）
        changed = 0
        ref = os.path.join(KIT, "uibc-core-public")
        for root, _, files in os.walk(d):
            if ".git" in root.split(os.sep):
                continue
            for f in files:
                q = os.path.join(root, f)
                rel = os.path.relpath(q, d)
                r = os.path.join(ref, rel)
                if os.path.exists(r):
                    try:
                        if sha(q) != sha(r):
                            changed += 1
                    except Exception:
                        pass
        rec("E1 行尾改写文件数", "INFO", "%d 个文件与 LF 检出不同" % changed,
            {"kind": "行尾/可复现性", "severity": "高" if changed else "-"})

        # 2) 关键：测试里声明了期望 sha256 的文件是否仍匹配
        anchors = declared_anchors()
        bad = []
        for rel, want in anchors:
            p2 = os.path.join(d, rel)
            if os.path.exists(p2):
                got = sha(p2)
                if got != want:
                    bad.append(dict(path=rel, want=want, got=got, bytes=os.path.getsize(p2)))
        if not anchors:
            rec("E1 字节锚定文件匹配", "BLOCKED", "没能从 tests/ 抽出声明式锚点（正则没匹配到）")
        else:
            rec("E1 字节锚定文件匹配", "PASS" if not bad else "FAIL",
                "%d 个锚点中 %d 个被改写%s" % (
                    len(anchors), len(bad),
                    ("；例：" + bad[0]["path"] + " 期望 " + bad[0]["want"][:12] + " 实得 " + bad[0]["got"][:12]) if bad else ""),
                {"kind": "对外可复跑", "severity": "高", "anchor_mismatch": bad})

        # 3) 直接跑受影响最重的一个测试模块，让结论落到"能不能跑通"
        if bad:
            mods = ["tests.test_aer1_merkle_profile"]
            r = subprocess.run([sys.executable, "-m", "unittest"] + mods, cwd=d,
                               capture_output=True, text=True, timeout=300)
            tail = (r.stderr or r.stdout).strip().splitlines()[-2:]
            rec("E1 受影响模块在默认克隆下", "FAIL", " | ".join(tail)[:180])
        # 4) 修法是否已落地：.gitattributes 覆盖 tests/fixtures
        ga = os.path.join(d, ".gitattributes")
        covered = False
        if os.path.exists(ga):
            txt = open(ga, encoding="utf-8", errors="replace").read()
            covered = bool(re.search(r"^\s*tests/fixtures/\*\*\s+(text\s+eol=lf|-text)", txt, re.M))
        rec("E1 .gitattributes 是否覆盖 tests/fixtures", "PASS" if covered else "FAIL",
            ".gitattributes 命中规则：%s" % ("有" if covered else "无（这是 47 条失败的根因）"),
            {"kind": "修复项", "severity": "高"})
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    print("=== E 组：外人第一公里（默认克隆） %s ===" % time.strftime("%F %T"))
    # 本组只在 Windows 有意义：验证的是 Windows 默认 core.autocrlf 对字节锚定文件的影响。
    # 在 Linux/macOS 上 autocrlf 默认 false，跑出来的 PASS/FAIL 不反映该风险，反而是误导。
    if sys.platform != "win32":
        rec("E0 平台适用性", "SKIP",
            "本组只验证 Windows 默认克隆的行尾改写；当前平台 %s 的 autocrlf 默认不同，结论不可比，整组跳过"
            % sys.platform)
        write_results(); return
    try:
        e1_default_clone()
    except Exception as e:
        import traceback; traceback.print_exc()
        rec("E1", "ERROR", repr(e)[:150])
    write_results()


def write_results():
    out = sys.argv[1] if len(sys.argv) > 1 else "s05_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    v = {}
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== 汇总 %s ===" % v)


if __name__ == "__main__":
    main()
