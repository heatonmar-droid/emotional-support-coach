# 一起改进 / Contributing

欢迎试用、提问题，也欢迎直接修一处让你卡住的地方。中文和英文都可以。

Try the project, report what got in your way, or fix something small. Chinese and English contributions are welcome.

## 可以从哪里开始 / Where to start

| 方向 / Area | 一个具体起点 / A concrete starting point |
|---|---|
| 安装体验 / Setup | 在自己的空数据库上跑快速开始，指出漏掉的步骤。Try the quick start with an empty database and report missing steps. |
| 提示词 / Prompts | 校对中英文含义，附虚构输入和预期行为。Check translation fidelity with fictional inputs and expected behavior. |
| 回归测试 / Regression tests | 补一个能复现问题的虚构案例，如跨账号访问或记忆纠正。Add a fictional reproduction, such as account isolation or memory correction. |
| 方法卡 / Method cards | 改进适用条件、步骤或停止条件，并说明来源和许可。Improve applicability, instructions, or stop conditions; explain sources and licensing. |

较大的行为调整先开 Issue 说清场景和预期。修错字、补说明可以直接提 PR。上述方向是邀请，不代表已经确认存在某个缺陷。

For larger behavior changes, open an issue describing the scenario and expected outcome first. Typo and documentation fixes can go straight to a PR. These suggestions are invitations, not claims of known defects.

## 提交方式 / Submitting a change

Fork 仓库，在自己的分支修改，再向本仓库 `main` 提交 PR。说明改了什么、为什么改、怎样验证。贡献者不需要仓库写入权限；由维护者审核决定是否合并。

Fork the repository, make changes on your own branch, and open a PR against this repository's `main`. Explain what changed, why, and how you checked it. Contributors do not need write access; maintainers review and decide whether to merge.

按 [README](README.md) 配置开发环境。行为修改运行相关测试；仅文档修改检查链接与命令即可。添加公开文件时，同时更新 `release-files.txt`，不要把运行数据加入清单。

Follow the [English README](README.en.md) for setup. Run relevant tests for behavior changes; check links and commands for documentation-only edits. Add new public files to `release-files.txt`, never runtime data.

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python scripts/check_release.py
```

数据库集成测试需要专门的 `TEST_DATABASE_URL`；未配置时会跳过，提交时请如实说明。测试使用虚构数据和模型替身。真实模型测试会收费，只使用你自己的凭证，不要提交响应日志或真实对话。

Database integration tests require a dedicated `TEST_DATABASE_URL`; they are skipped when it is absent, so report that accurately. Tests use fictional data and model doubles. Real-provider tests incur charges: use your own credentials and do not commit response logs or real conversations.

## 内容边界 / Content boundaries

不要提交真实咨询记录、用户画像、用户记忆、个人身份信息、密钥、数据库导出或未经授权的书籍原文。改掉名字的真实案例仍可能暴露身份，请从头编写虚构案例。截图和错误信息也需要检查；安全漏洞按 [SECURITY.md](SECURITY.md) 处理，不公开敏感细节。

Do not submit real counseling records, user profiles or memories, personal identifiers, secrets, database exports, or unauthorized book text. Changing names in real cases may still expose someone; write fictional cases from scratch. Check screenshots and error messages too. Follow [SECURITY.md](SECURITY.md) for vulnerabilities without posting sensitive details publicly.

修改一份提示词或说明时同步对应语言；如果无法确认翻译，请在 PR 中标注。知识正文保留中文的约定见 [知识库说明](knowledge/README.md)。不要把离线测试通过描述为临床效果证明。

Update the corresponding language when editing prompts or documentation; flag translations you cannot verify in the PR. See [knowledge notes](knowledge/README.md) for Chinese source-text conventions. Passing offline tests is not evidence of clinical effectiveness.

提交你有权贡献的内容，代码贡献沿用仓库 MIT 许可。引用第三方材料时说明出处与适用许可；不要把第三方内容标成自己的原创。

Submit material you have the right to contribute. Code contributions follow the repository's MIT license. Identify sources and applicable licenses for third-party material; do not present it as your own work.
