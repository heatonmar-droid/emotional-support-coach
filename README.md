# 情绪支持与心理教练

[English](README.en.md) · [提示词](prompts/README.md) · [知识库](knowledge/README.md) · [架构](docs/ARCHITECTURE.md)

给想做心理支持对话的人，一套可以读懂、修改和自行部署的后端。

有人下班后只想把烦心事说出来，有人被一段关系困住，想理清自己在意什么；也有人已经聊了很久，希望这次能往前走一小步。这些对话需要不同的节奏。这个项目保留了两种 Claude 文字模式，也把上下文、记忆、安全判断和方法卡检索放在同一条链路里。

## 可以用它做什么

如果你在做小程序或网页里的心理支持聊天，可以从这里接上自己的界面和账号系统。想研究对话提示词、比较两种回复风格，或观察记忆怎样参与后续对话，也可以直接读代码、改提示词，用虚构案例测试。

| 想解决的问题 | 仓库提供的部分 |
|---|---|
| 用户想先说说，不想马上收到一串建议 | **日常支持** `claude`：以倾听和自然交流为主 |
| 用户想整理困扰、比较选择或找到一个小行动 | **心理教练** `claude_coach`：围绕已有信息推进讨论 |
| 下一轮不想重新解释刚才说过的事 | 近期上下文、长期画像和事件记忆 |
| 合适的时候提供一个具体练习 | 方法卡检索，由主回复模型决定是否采用 |
| 前端需要知道这轮是否真正完成 | SSE 进度、最终回复及明确的错误事件 |

两种模式共享安全判断和记忆，但采用不同的主提示词。主回复使用 Claude；安全判断、记忆提取和 embedding 另有各自的模型配置。

这是一套后端源码，前端、完整账号平台、计费和运营系统需要自行接入。它没有经过临床效果验证，不能用来承诺诊断、治疗或紧急救助。适合先搭建和评估对话服务，再决定怎样面向用户开放。

## 从哪里看起

| 内容 | 入口 |
|---|---|
| 两套主提示词及共享规则，中英文对照 | [prompts](prompts/README.md) |
| 知识库内容、导入方式与使用范围 | [knowledge](knowledge/README.md) |
| 回复、记忆和安全判断怎样协作 | [架构说明](docs/ARCHITECTURE.md) |
| 数据发送给谁，清空会删除什么 | [隐私说明](docs/PRIVACY.md) |
| 已测内容与尚未验证的部分 | [验证记录](docs/VALIDATION.md) |
| 准备自己的公开仓库 | [发布说明](docs/RELEASE.md) |

## 快速开始

需要 Python 3.12 或更新版本、一个空的 PostgreSQL 数据库，以及使用者自己的模型服务凭证。以下命令在本目录运行。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux/macOS 使用 `.venv/bin/python`，复制配置用 `cp .env.example .env`。

编辑 `.env`：

- `PGDATABASE_URL`：你自己的空数据库连接串。代码不会尝试发现或回退到生产数据库。
- `OPENROUTER_API_KEY`：Claude 主回复服务凭证。
- `DEEPSEEK_API_KEY`：语义安全判断服务凭证。
- `ARK_API_KEY`：异步记忆提取服务凭证。
- `SILICONFLOW_API_KEY`：BGE-M3 embedding，用于事件记忆及可选方法卡。
- `MEM0_OSS_DATA_DIR`：本机可写的绝对路径，用于本地 Qdrant 和 Mem0 历史数据；应在 Git 仓库外。

模型名在 `config/chat_clean_v1.json`，端点在 `.env`。默认模型标识来自生产快照；它们是否对你的账号可用必须用自己的凭证验证。这里没有提供或测试私有中转服务。

可选：用 Docker 启动一套独立的本地 PostgreSQL。先在 `.env` 设置一个新生成的 `POSTGRES_PASSWORD`，然后：

```powershell
docker compose up -d postgres
```

此容器仅绑定本机 `55432` 端口。将 `PGDATABASE_URL` 设置为 `postgresql://support:<你的密码>@127.0.0.1:55432/support_text`；密码含特殊字符时需 URL 编码。数据库持久化在独立 Docker volume，删除容器并不删除数据。

初始化并启动：

```powershell
.\.venv\Scripts\python.exe manage.py init-db
.\.venv\Scripts\python.exe manage.py create-user --mode claude
.\.venv\Scripts\python.exe -m uvicorn clean_workflow_api:app --host 127.0.0.1 --port 5101 --workers 1 --no-access-log
```

`create-user` 会在终端输出新账号 ID 和随机令牌，数据库只保存令牌哈希。令牌视同登录凭证，不要放进截图、日志、示例文件或 Git。需要撤销时运行 `python manage.py revoke-user --user-id <账号ID>`。

当前适配版要求 **单进程、一个 worker**。本地 Qdrant 文件锁、排队记忆写入与清空保护依赖这一边界。不要加 `--reload` 用于正式服务。异步记忆线程不是持久任务队列，进程退出可能丢失尚未完成的记忆提取；已提交的聊天消息仍在 PostgreSQL 中。

## 调用

PowerShell 中临时设置自己生成的令牌，然后发送完全虚构的测试消息：

```powershell
$env:SUPPORT_TOKEN = Read-Host '输入本地测试账号令牌'
curl.exe -N http://127.0.0.1:5101/stream_run `
  -H "Authorization: Bearer $env:SUPPORT_TOKEN" `
  -H "Content-Type: application/json" `
  --data-raw '{"user_input":"我想理一下今天的工作安排。"}'
```

除 `/health` 和自动生成的 API 文档外，应用数据接口均需要 `Authorization: Bearer <token>`。请求不能自行指定 `user_id` 或 `client_id`；服务器由认证结果确定身份。

| 接口 | 用法 |
|---|---|
| `GET /auth/chat_mode` | 读取当前账号模式 |
| `POST /auth/chat_mode` | `{"mode":"daily"}` 或 `{"mode":"coach"}`，下一轮生效 |
| `POST /session_start` | 获取通用开场问候，不调用 LLM |
| `POST /stream_run` | `user_input`，可选 `conversation_id`、`request_id` |
| `GET /conversations` | 当前账号最近 100 个会话 |
| `GET /history/{conversation_id}` | 当前账号的会话上下文窗口，受条数和字符预算限制 |
| `POST /reset_all` | 删除当前账号的聊天、画像和事件记忆，保留账号与模式 |

SSE 顺序为 `workflow_start` → `step` → `workflow_end`，失败时以 `error` 结束，不发成功终态。**此接口采用生产的完成后输出协议，不是逐 token 流式生成**；小程序原有的 Next.js 转换层不在包中。`workflow_end.output.response` 是最终正文。不要只凭 HTTP 200 判断成功。

未提供会话 ID 时复用当前账号最近会话；新账号自动创建首个会话。这里保留核心对话能力，不提供完整的会话管理 UI。重复使用已提交的 `request_id` 会失败，不会重复保存该轮消息。

## 方法卡与记忆

随包提供 **68 张中文方法卡**，具体内容和范围见 [知识库说明](knowledge/README.md)。数据库初始为空，需要导入后才参与检索。咨询原文、用户记忆和已有向量不随包交付。

导入随包方法卡：

```powershell
.\.venv\Scripts\python.exe manage.py import-cards --file knowledge/method-cards.zh-CN.json
```

导入会调用你的 embedding 服务并产生费用。重启 API 后生效。检索仍按生产代码综合当前问题和近期上下文排序；最终是否采用由主回复模型判断。

长期画像保存在 PostgreSQL；事件记忆使用 Mem0 OSS / Qdrant，embedding 发送给 SiliconFlow。模型会接收本轮消息和相关上下文。**自行部署不等于数据完全离线。** 详情与删除边界见 [隐私说明](docs/PRIVACY.md)。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/check_release.py
```

数据库集成检查需要另外设置 `TEST_DATABASE_URL`，指向专门的本机测试数据库。测试会创建并清理独立 schema；不要使用真实用户数据库。未设置时会明确跳过数据库检查。所有随包测试只使用合成内容和模型替身，不调用付费模型；Mem0/Qdrant 存储检查使用真实本地实现和替身 embedding。

当前检查结果与未验证项见 [验证记录](docs/VALIDATION.md)。英文提示词是完整对照译文，不等于已验证的英语服务；见 [提示词说明](prompts/README.md)。

## 许可

代码采用 [MIT](LICENSE)。模型权重、供应商服务授权和第三方出版物版权不属于该许可。知识资料的来源范围见 [知识库说明](knowledge/README.md)。本项目提供心理支持，不应被描述为已验证的诊断或治疗服务。
