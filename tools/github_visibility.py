# -*- coding: utf-8 -*-
"""S9 可见性判据：只用 git 协议判 PUBLIC / PRIVATE。

为什么不用 REST：匿名 `api.github.com` 对私有仓回 404、对限流回 403，两者混用会把公开记成私有、
把私有记成"暂时拿不到"（403 式绿）。git 协议只给两种结果：能列 refs = PUBLIC；要凭据 =
PRIVATE/不存在。

用法：
    python tools/github_visibility.py owner/repo [owner/repo ...]
    python tools/github_visibility.py --local <git-dir>     # 只判本地仓有没有远端
"""
import argparse
import json
import os
import re
import subprocess
import sys


def anonymous_ls_remote(slug, retries=3):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="")
    url = "https://github.com/%s" % slug
    attempts = []
    for i in range(retries):
        p = subprocess.run(["git", "-c", "credential.helper=", "ls-remote", url, "HEAD"],
                           capture_output=True, text=True, env=env, timeout=60)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        attempts.append({"try": i + 1, "code": p.returncode, "stdout": out, "stderr": err})
        if p.returncode == 0 and re.search(r"\b[0-9a-f]{40}\b", out):
            return "PUBLIC", out.split()[0], attempts
        if re.search(r"Authentication failed|could not read Username|Repository not found|not found", err, re.I):
            return "PRIVATE/不存在", None, attempts
    return "BLOCKED（网络）", None, attempts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="+")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    res = []
    for slug in a.repos:
        verdict, head, attempts = anonymous_ls_remote(slug)
        res.append({"repo": slug, "verdict": verdict, "head": head, "attempts": attempts})
        print("%-45s %-14s %s" % (slug, verdict, head or "-"))
        if verdict == "BLOCKED（网络）":
            print("   （三次都没连上，不能据此判私有；换时间复跑）")
    if a.json:
        json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("json=%s" % a.json)
    return 0 if all(r["verdict"] != "BLOCKED（网络）" for r in res) else 2


if __name__ == "__main__":
    sys.exit(main())
