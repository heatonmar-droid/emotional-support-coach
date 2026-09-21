# GitHub 发布 / Publishing to GitHub

本目录是独立的开源包，代码许可为 MIT。发布更新时只提交本目录经审核的内容；不要把父项目、生产快照、验证环境、密钥或旧 Git 历史一起提交。

This directory is a standalone open-source package with MIT-licensed code. Publish updates from its reviewed contents only, excluding the parent project, production snapshots, test environment, secrets, and old Git history.

## 本地检查 / Local checks

```bash
python scripts/check_release.py
python -m unittest discover -s tests -v
gitleaks dir . --redact=100
```

`check_release.py` 检查文件白名单和常见隐私模式；Gitleaks 检查凭证。扫描结果不得携带密钥原文。修改后应重新审阅暂存差异和新文件；不要为通过检查而整体排除文档、测试或提示词目录。

`check_release.py` checks the file allowlist and common privacy patterns; Gitleaks checks credentials. Keep raw secret values out of reports. Review staged changes and new files after editing. Do not broadly exclude docs, tests, or prompts merely to obtain a passing scan.

## 新建独立历史 / Start a separate history

在包目录内新建仓库，不复制父项目的 `.git`。提交前设置你希望公开的作者名及 GitHub noreply 邮箱，检查是否有签名、Git hooks 或全局设置会引入意外信息。

Initialize inside this package without copying the parent `.git`. Before committing, configure the public author name and GitHub noreply email you want to disclose, and check whether signing, hooks, or global settings introduce unintended information.

```bash
git init -b main
git add .
git diff --cached --stat
git diff --cached
```

确认文件清单后再创建首个提交和远端仓库。先检查本地内容，不能把「先传私有仓库再扫描」当作保护敏感信息的替代。添加远端时核对准确的 GitHub 所有者、仓库名及可见性。

Create the first commit and remote repository only after reviewing the file list. Inspect locally first; uploading to a private repository is not a substitute for preventing disclosure. Verify the exact GitHub owner, repository name, and visibility when adding a remote.

启用 GitHub secret scanning 和 push protection。它们可以拦截支持的凭证模式，但不能替代个人数据审查；见 [GitHub push protection](https://docs.github.com/en/code-security/concepts/secret-security/push-protection)。

Enable GitHub secret scanning and push protection. They detect supported credential patterns, not every privacy issue; see [GitHub push protection](https://docs.github.com/en/code-security/concepts/secret-security/push-protection).

若凭证已被推送，先撤销或轮换，再处理历史和缓存。删除当前文件或增加 `.gitignore` 不会清除已提交的历史；参见 [GitHub 敏感数据移除说明 / Removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)。

If a credential has been pushed, revoke or rotate it before addressing history and caches. Deleting the current file or adding `.gitignore` does not erase committed history; see the [GitHub removal guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
