# -*- coding: utf-8 -*-
r"""版本声明一致性红线（补 S8 的自动化缺口）。

为什么要这个：S8 靠人工读 README 才发现"README 写 main 0.4.0 / PyPI 0.3.3，实际 pyproject 0.5.0"。
人工读会漏、会过时，所以把这条变成可跑的判定：被测仓声明的版本与实际包版本不一致 → FAIL。

判定：
  PASS     声明与实际一致（或声明里没有具体版本号，不构成矛盾）
  FAIL     发现矛盾，逐条列出（属被测方问题，我们只报不改）
  BLOCKED  缺被测仓或缺 pyproject.toml
用法：
  python tools/check_version_drift.py            # 默认读 ./uibc-core-public
  python tools/check_version_drift.py <repo路径>
"""
import json, os, re, sys

SEMVER = re.compile(r"\b(\d+\.\d+\.\d+)\b")
KV = ("version", "版本", "release", "pypi", "main", "latest", "tag")


def pyproject_version(repo):
    p = os.path.join(repo, "pyproject.toml")
    if not os.path.exists(p):
        return None
    txt = open(p, encoding="utf-8", errors="replace").read()
    m = re.search(r'(?m)^\s*version\s*=\s*["\']([^"\']+)["\']', txt)
    if m:
        return m.group(1)
    m = re.search(r'(?m)^\s*version\s*=\s*\{[^}]*file\s*=\s*["\']([^"\']+)["\']', txt)
    if m:
        f = os.path.join(repo, m.group(1))
        if os.path.exists(f):
            return open(f, encoding="utf-8", errors="replace").read().strip()
    return None


def readme_claims(repo):
    out = []
    for name in ("README.md", "README.en.md", "README.rst", "README.txt"):
        p = os.path.join(repo, name)
        if not os.path.exists(p):
            continue
        for i, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
            low = line.lower()
            if not any(k in low for k in KV):
                continue
            for v in SEMVER.findall(line):
                out.append((name, i, v, line.strip()[:110]))
    return out


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uibc-core-public")
    if not os.path.isdir(repo):
        print("[BLOCKED] 缺被测仓：%s" % repo)
        return 2
    ver = pyproject_version(repo)
    if not ver:
        print("[BLOCKED] 缺 pyproject.toml 或其中没有 version")
        return 2
    claims = readme_claims(repo)
    bad = [c for c in claims if c[2] != ver]
    print("[INFO ] pyproject version = %s" % ver)
    print("[INFO ] README 里的版本声明 %d 条" % len(claims))
    for c in claims:
        print("         %s:%d  %s  <- %s" % c)
    if bad:
        print("[FAIL ] %d 条声明与实际不一致（被测方问题，只能报不能改）" % len(bad))
        res = dict(case="N1 版本声明一致性", verdict="FAIL",
                   note="pyproject=%s；%d 条 README 声明不一致" % (ver, len(bad)),
                   extra=dict(actual=ver, mismatches=[dict(file=b[0], line=b[1],
                                                           claimed=b[2]) for b in bad]))
        rc = 1
    else:
        print("[PASS ] 声明与实际一致")
        res = dict(case="N1 版本声明一致性", verdict="PASS",
                   note="pyproject=%s；%d 条声明全部一致" % (ver, len(claims)),
                   extra=dict(actual=ver, claims=len(claims)))
        rc = 0
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version_drift.json")
    json.dump([res], open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("落盘：%s" % out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
