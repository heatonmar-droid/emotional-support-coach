# Emotional Support Coach

[简体中文](README.md) · [Contribute](CONTRIBUTING.md) · [Prompts](prompts/README.md) · [Knowledge](knowledge/README.md) · [Architecture](docs/ARCHITECTURE.md)

A backend you can read, change, and self-host when building a psychological-support chat service.

Some people want to talk through a difficult day. Others feel stuck in a relationship and want to understand what matters to them. After a longer conversation, someone may want help finding one small next step. Those conversations need different pacing. This project provides two text conversation modes, with context, memory, safety assessment, and method-card retrieval in the same request flow.

## What you can build with it

Use it as the backend for a mini-program or web chat, connected to your own interface and identity system. You can also study the prompts, compare the two response styles, or explore how memory affects later turns by modifying the code and testing fictional cases.

| What you need | What is included |
|---|---|
| Space to talk before receiving advice | **Everyday support** `claude`: listening and natural conversation |
| Help organizing a concern, comparing options, or finding a small action | **Psychological coach** `claude_coach`: discussion grounded in what the user has shared |
| Continuity without repeating the previous turn | Recent context, profile memory, and episodic memory |
| A concrete exercise when it fits the conversation | Method-card retrieval; the response model decides whether to use a card |
| A clear indication that a turn finished | SSE progress, a final reply, and explicit error events |

Both modes share safety assessment and memory but use different main prompts. Developers choose models by role; multiple roles may use the same model.

This repository contains backend code. You supply the frontend, full identity platform, billing, and operations integrations. It has not been validated for clinical effectiveness and cannot promise diagnosis, treatment, or emergency assistance. Start by building and evaluating the conversation flow before deciding how to offer it to users.

## Where to start

| Content | Entry point |
|---|---|
| Both main prompts and shared rules, in Chinese and English | [Prompts](prompts/README.md) |
| Knowledge contents, import instructions, and scope | [Knowledge](knowledge/README.md) |
| How replies, memory, and safety work together | [Architecture](docs/ARCHITECTURE.md) |
| Where data goes and what reset deletes | [Privacy](docs/PRIVACY.md) |
| Completed checks and remaining limitations | [Validation](docs/VALIDATION.md) |
| Preparing your own public repository | [Release](docs/RELEASE.md) |

## Quick start

Requires Python 3.12 or newer, an empty PostgreSQL database, and your own model-service credentials. Run these commands in this directory.

```bash
git clone https://github.com/heatonmar-droid/emotional-support-coach.git
cd emotional-support-coach
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows PowerShell, use `.\.venv\Scripts\python.exe` and `Copy-Item .env.example .env`.

Edit `.env`:

- `PGDATABASE_URL`: your own empty database. The code does not discover or fall back to a production database.
- `REPLY_API_KEY` / `REPLY_BASE_URL`: reply credentials and compatible endpoint.
- `SAFETY_API_KEY` / `SAFETY_BASE_URL`: safety-assessment credentials and compatible endpoint.
- `MEMORY_API_KEY` / `MEMORY_BASE_URL`: memory-extraction credentials and compatible endpoint.
- `EMBEDDING_API_KEY`: credentials; also set `EMBEDDING_BASE_URL` and `EMBEDDING_MODEL`. The current store requires 1024-dimensional output via an OpenAI-compatible embeddings endpoint. Rebuild method-card and episodic vectors when changing models; do not mix embedding spaces.
- `MEM0_OSS_DATA_DIR`: a writable absolute local path for Qdrant and Mem0 history, outside the Git repository.

Model IDs are in `config/chat_clean_v1.json`; endpoints are in `.env`. Model IDs for all three roles are blank; supply your own IDs. The chat adapter uses OpenAI-compatible Chat Completions, and models must satisfy the JSON output contract. Other protocols need an adapter; arbitrary models are not guaranteed to work unchanged. The retained mode IDs `claude` and `claude_coach` do not restrict model choice.

Optional: start an independent local PostgreSQL instance with Docker. First set a newly generated `POSTGRES_PASSWORD` in `.env`, then:

```bash
docker compose up -d postgres
```

The database binds only to local port `55432`. Set `PGDATABASE_URL` to `postgresql://support:<your-password>@127.0.0.1:55432/support_text`; URL-encode special characters in the password. Data persists in a dedicated Docker volume; removing the container does not erase it.

Initialize and start:

```bash
.venv/bin/python manage.py init-db
.venv/bin/python manage.py create-user --mode claude
.venv/bin/python -m uvicorn clean_workflow_api:app --host 127.0.0.1 --port 5101 --workers 1 --no-access-log
```

`create-user` prints a new account ID and a random token; only its hash is stored in the database. Treat the token as a login credential. Keep it out of screenshots, logs, example files, and Git. Revoke it using `python manage.py revoke-user --user-id <account-id>`.

This adaptation requires **one process and one worker**. Local Qdrant locking, queued memory writes, and reset ordering depend on this boundary. Do not use `--reload` for a deployed service. Memory extraction runs in background threads, not a durable queue: process exit may lose unfinished memory work. Committed chat messages remain in PostgreSQL.

## API

Read your locally generated test token into a temporary environment variable and send fictional content:

```bash
read -rs -p 'Local test account token: ' SUPPORT_TOKEN
export SUPPORT_TOKEN
curl -N http://127.0.0.1:5101/stream_run \
  -H "Authorization: Bearer $SUPPORT_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-raw '{"user_input":"我想理一下今天的工作安排。"}'
```

Except for `/health` and generated API documentation, application-data endpoints require `Authorization: Bearer <token>`. Requests cannot supply `user_id` or `client_id`; identity comes from verified authentication.

| Endpoint | Usage |
|---|---|
| `GET /auth/chat_mode` | Read the account's current mode |
| `POST /auth/chat_mode` | `{"mode":"daily"}` or `{"mode":"coach"}`; effective next turn |
| `POST /session_start` | Generic greeting, no LLM call |
| `POST /stream_run` | `user_input`, optional `conversation_id` and `request_id` |
| `GET /conversations` | The account's 100 most recent conversations |
| `GET /history/{conversation_id}` | Owned conversation context window, bounded by message and character budgets |
| `POST /reset_all` | Delete owned chat, profile, and episodic memory; retain account and mode |

SSE order is `workflow_start` → `step` → `workflow_end`. Failures end with `error`, never a success event. **This retains the production completion-event protocol, not token-by-token generation.** The mini-program's original Next.js event-conversion layer is excluded. Final text is `workflow_end.output.response`. HTTP 200 alone does not mean a completed response.

Without a conversation ID, the service reuses the account's latest conversation; a new account receives its first conversation automatically. This package supplies core conversation capabilities, not a full conversation-management UI. Reusing a committed `request_id` fails rather than saving the same turn twice.

## Method cards and memory

The package includes **68 Chinese method cards**; see [knowledge contents and scope](knowledge/README.md). The database starts empty, so import the cards to enable retrieval. Counseling transcripts, user memories, and existing vectors are excluded.

Import the bundled cards:

```bash
.venv/bin/python manage.py import-cards --file knowledge/method-cards.zh-CN.json
```

Importing calls your embedding provider and incurs its charges. Restart the API afterwards. Retrieval retains production ranking based on the current message and recent context; the response model decides whether to use a card.

Profile memory is stored in PostgreSQL. Episodic memory uses Mem0 OSS / Qdrant, with embeddings sent to your configured provider. Models receive the current message and relevant context. **Self-hosting does not make the system fully offline.** Read the [privacy and deletion boundaries](docs/PRIVACY.md).

## Verification

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_release.py
```

For database integration checks, also set `TEST_DATABASE_URL` to a dedicated local test database. Tests create and remove an isolated schema. Never use a real-user database. Without that variable, database checks are explicitly skipped. All bundled tests use synthetic content and model doubles, with no paid model calls. Mem0/Qdrant checks use actual local storage with synthetic embeddings.

See [validation results and limitations](docs/VALIDATION.md). English prompt files are complete reference translations, not a validated English support product; see [prompt notes](prompts/README.md).

## Contribute

[Report a problem](https://github.com/heatonmar-droid/emotional-support-coach/issues/new/choose) or fork the repository and open a PR. Setup notes, English proofreading, fictional regression cases, and method cards are welcome. See the [contribution guide](CONTRIBUTING.md); maintainers review merges.

On your first run, check `http://127.0.0.1:5101/health` from another terminal, then call the chat endpoint with your newly created account token. Health only confirms startup, not a successful model call; chat must reach `workflow_end`. For a 401, check the account token. For model-access or model-name errors, check your provider account and model configuration. Never include secrets, full configuration, or real user content in reports.

## License

Code is licensed under [MIT](LICENSE). Model weights, provider-service access, and third-party publication rights are outside that license. See [knowledge sources and scope](knowledge/README.md). This project provides psychological support and must not be presented as a validated diagnostic or treatment service.
