"""Check the public file allowlist and privacy patterns; never print matched values.
检查发布白名单及隐私模式，只输出位置和类别，不输出匹配原文。
"""

import ast
import ipaddress
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {".git", "__pycache__", ".venv", "venv", ".pytest_cache", ".ruff_cache"}
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider-key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "github-token": re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"
    ),
    "signed-token": re.compile(
        r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}"
    ),
    "phone": re.compile(r"(?<![A-Za-z0-9])1[3-9]\d{9}(?![A-Za-z0-9])"),
    "personal-path": re.compile(r"[A-Za-z]:[/\\]Users[/\\][^\s/\\]+", re.I),
}


def files():
    return sorted(
        p
        for p in ROOT.rglob("*")
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & IGNORED)
    )


def main():
    expected = set(
        (ROOT / "release-files.txt").read_text(encoding="utf-8").splitlines()
    )
    actual = {p.relative_to(ROOT).as_posix() for p in files()}
    issues = [(name, "unexpected file") for name in sorted(actual - expected)]
    issues += [(name, "missing file") for name in sorted(expected - actual)]
    for path in files():
        name = path.relative_to(ROOT).as_posix()
        if path.is_symlink():
            issues.append((name, "symlink forbidden"))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            issues.append((name, "non-text file forbidden"))
            continue
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                issues.append((f"{name}:{line}", label))
        for match in re.finditer(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", text):
            try:
                address = ipaddress.ip_address(match.group())
            except ValueError:
                continue
            if not address.is_loopback:
                issues.append((name, "non-loopback IP address"))
        if path.suffix == ".py":
            ast.parse(text, filename=name)
        if name == ".env.example":
            for line in text.splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                key, value = line.split("=", 1)
                if (
                    any(word in key for word in ("PASSWORD", "API_KEY", "DATABASE_URL"))
                    and value.strip()
                ):
                    issues.append((name, "credential template must be empty"))
    if issues:
        for name, category in issues:
            print(f"FAIL {name}: {category}")
        return 1
    print(
        f"PASS: {len(actual)} allowlisted text files; no matched privacy patterns. / 白名单与模式检查通过。"
    )
    print(
        "This is not proof of zero private data. Also run Gitleaks and review manually. / 仍需凭证扫描及人工审查。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
