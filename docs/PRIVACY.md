# 隐私与数据边界 / Privacy and data boundaries

## 发布包 / Release contents

只允许发布清单中的代码、空配置模板、空表结构、提示词、合成测试、经过审查的静态知识文件及文档。原始生产快照、服务器地址、部署证据、密钥、数据库、聊天日志、录音、向量快照、截图、备份和本地 Git 历史均不随包交付。

Only allowlisted code, empty configuration templates, schema, prompts, synthetic tests, reviewed static knowledge files, and documentation are included. Raw production snapshots, server addresses, deployment evidence, secrets, databases, chat logs, recordings, vector snapshots, screenshots, backups, and prior local Git history are excluded.

扫描能发现一部分凭证和个人信息模式，不能证明不存在任何语义层面的隐私信息。不要把脱敏工具当成发布真实咨询内容的许可；新增样例应完全虚构，并人工复核。

Scanning detects some credential and personal-data patterns, but cannot prove the absence of all semantic privacy information. Do not treat redaction tools as permission to publish real counseling content. New examples should be wholly fictional and manually reviewed.

## 运行时的数据流 / Runtime data flow

| 数据 / Data | 去向 / Destination |
|---|---|
| 本轮消息、上下文与选中的记忆 / Message, context, selected memory | 配置的 Claude 服务；安全与记忆辅助模型按各自调用上下文接收信息。Configured Claude provider and auxiliary providers receive their respective contexts. |
| 待检索/写入事件与方法卡文本 / Episode and method-card text | SiliconFlow embedding 服务。SiliconFlow embedding service. |
| 账号令牌哈希、模式、聊天、画像、安全状态 / Token hash, mode, chat, profile, safety state | 使用者配置的 PostgreSQL。Recipient-owned PostgreSQL. |
| 事件原文、向量、Mem0 操作历史 / Episode text, vectors, Mem0 operation history | 使用者配置的 Qdrant 与 Mem0 本地数据目录。Recipient-configured Qdrant and Mem0 data directory. |

Mem0 以 `infer=False` 写入，不额外让 Mem0 的模型再次抽取。其 LLM 配置保留一个关闭的本机端点，以阻止误用；不代表可以省略上层记忆提取模型的凭证。Mem0 遥测默认关闭，但云模型和 embedding 服务的数据保留规则由对应供应商控制。

Mem0 writes use `infer=False`, avoiding another extraction call inside Mem0. Its configured LLM points to a closed loopback endpoint to prevent accidental use; the separate memory-extraction model still needs credentials. Mem0 telemetry is disabled, but provider retention policies still govern cloud model and embedding requests.

本包不做全量用户输入匿名化，模型收到的仍可能是敏感原文。部署者应设置适当的用户告知、访问控制和保留期限，并避免启用 SDK 的请求正文调试日志。`--no-access-log` 只关闭 Uvicorn 的访问日志，不会替你配置外部反向代理或供应商日志。

This package does not fully anonymize user input; providers may receive sensitive source text. Deployers should configure appropriate notices, access control, and retention, and avoid SDK request-body debugging. `--no-access-log` disables Uvicorn access logs only, not external proxy or provider logs.

## 身份隔离 / Identity isolation

服务只接受账号令牌；数据库只存令牌的 SHA256。读取、写入、模式切换和清空均由认证得到的账号 ID 限定。请求里自行填写用户 ID 被拒绝；他人的会话 ID 不能用于读取或写入。

The service accepts account tokens and stores only their SHA256 hashes. Reads, writes, mode changes, and reset are scoped to the authenticated account. Caller-supplied user IDs are rejected, and another account's conversation ID cannot authorize access.

令牌不自动过期，属于本适配版明确的功能边界；使用 `manage.py revoke-user` 撤销。公网部署前应接入你自己的身份系统、TLS、访问频率限制和运维监控，不能直接把开发端口暴露为正式服务。

Tokens do not expire automatically; this is an explicit adapter limitation. Revoke them with `manage.py revoke-user`. A public deployment needs your own identity integration, TLS, rate limits, and operations monitoring rather than simply exposing the development port.

## 遗忘与删除 / Forgetting and deletion

自然语言纠正/遗忘操作按生产语义使旧画像失效，失效项可能仍保留在历史命名空间；原聊天记录也仍存在。**「不再作为记忆使用」不等于物理擦除。** 模型只可删除本账号本次已检索出的事件 ID，不允许随意指定其他账号记录。

Natural-language corrections or forgetting invalidate profile entries according to production semantics. Invalidated entries may remain in a history namespace, and original chat messages remain. **Not using an item as memory is not physical erasure.** The model can target only episode IDs retrieved for that account, not arbitrary other-account records.

`POST /reset_all` 先删除该账号的活动事件记录，再删除本地聊天和画像；外部事件删除失败时返回错误，保留本地历史以便重试。清空会阻止已排队的旧记忆任务重新写入。操作保留账号和模式，且不撤销令牌。

`POST /reset_all` deletes the account's active episodic records first, then local chats and profiles. An episode-store deletion failure returns an error and preserves local history for retry. Reset invalidates queued old memory jobs. It retains the account, mode, and token.

**清空 API 不承诺删除供应商保留数据、备份、Mem0 操作历史库、数据库事务日志、反向代理日志或已经导出的文件。** Qdrant 删除也不等于立即覆盖磁盘字节。需要彻底删除时，部署者还要针对这些独立存储执行其保留/清理流程。本接口返回 `external_backups_removed=false` 提醒这个边界。

**Reset does not promise to erase provider-retained data, backups, Mem0 operation-history databases, database transaction logs, proxy logs, or exported files.** Qdrant deletion does not imply immediate overwriting of disk bytes. Deployers must handle those separate retention and cleanup systems. The endpoint returns `external_backups_removed=false` to keep this boundary visible.
