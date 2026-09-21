# 验证记录 / Validation record

日期 / Date: 2026-09-21

状态：**已完成下列本地检查；发布源码不代表已完成真实模型或线上集成验收。未替换生产服务。**

Status: **The local checks below are complete. Publishing source code does not establish real-provider or live-integration acceptance. Production services were not replaced.**

## 已完成 / Completed

- 两套主提示词采用通用身份，英文与中文版本同步；来源标识及原始文件指纹不包含在公开包中。
  Both main prompts use a generic identity consistently in Chinese and English; source identifiers and original-file fingerprints are excluded from the public package.
- 在全新 Python 3.13 虚拟环境安装固定版本的直接依赖；`pip check` 无冲突。
  Direct dependencies installed in a fresh Python 3.13 virtual environment; `pip check` found no conflicts.
- 独立 Uvicorn 进程启动、健康接口及未认证请求拒绝通过。
  Standalone Uvicorn startup, health, and rejection of unauthenticated access passed.
- 10 项 `unittest` 检查通过，含隔离数据库集成测试；不是仅运行后跳过数据库检查。
  Ten unittest checks passed, including database integration, not a run that skipped the database check.
- Python 未定义名称/未使用导入等 Ruff F 类检查通过；所有交付 Python 文件可解析。
  Ruff F checks passed, and all delivered Python files parse successfully.
- Gitleaks 8.30.1 凭证扫描零发现，未使用目录级忽略规则。
  Gitleaks 8.30.1 reported zero findings without directory-wide exclusions.

## 测试覆盖 / Test coverage

1. 两种模式读取各自原提示词，不附音频；双语提示词文件完整。
   Both modes load their respective originals; no audio attachment; bilingual prompt files exist.
2. `length` 截断重试 1600 → 3200，第二次截断失败；拒绝残缺 JSON 和协议字段泄露。
   Bounded length retry, repeated-truncation failure, incomplete JSON and protocol-leak rejection.
3. 模型失败不回退到旧生成链路。
   Provider failure does not fall back to retired generators.
4. 安全证据必须来自用户原文；判断失败走保守安全路径。
   Safety evidence must match user text; assessment failure takes the conservative safety path.
5. 记忆拒绝编造原句和外部账号记录 ID。
   Fabricated memory quotes and foreign record IDs are rejected.
6. 清空使排队等待的旧记忆任务失效。
   Reset invalidates queued old memory writes.
7. 真实 Mem0 OSS / Qdrant 本地存储的新增、检索、账号隔离和删除。
   Actual local Mem0/Qdrant add, search, identity isolation, and deletion.
8. API 认证、模式切换、两种完整 SSE、历史落库、会话越权拒绝、失败不保存助手回复、安全状态、画像纠正、清空失败保留历史和成功清空。
   API authentication, mode changes, completed SSE for both modes, persistence, ownership checks, no assistant commit on failure, safety state, profile correction, failed-reset history preservation, and successful reset.
9. JSON 解析失败日志不包含测试原文。
   Failed-JSON parsing logs do not contain source text.
10. 68 张随包方法卡的编号、字段、边界说明及分批导入检查通过；embedding 使用替身。
    Bundled-card IDs, fields, boundaries, and batched import passed; embeddings were mocked.

数据库测试使用临时 **PGlite 0.5.8 + pglite-socket 0.2.11** 的 PostgreSQL 引擎和隔离 schema，经真实 psycopg 协议连接；没有访问生产数据库。PGlite 的并发连接实现与原生 PostgreSQL 不完全相同，因此不能据此宣称原生 PostgreSQL 的多进程/高并发部署已验证。[PGlite 官方说明](https://pglite.dev/docs/pglite-socket)

Database tests used a temporary **PGlite 0.5.8 + pglite-socket 0.2.11** PostgreSQL engine with an isolated schema and actual psycopg connections. No production database was accessed. PGlite multiplexes connections differently from native PostgreSQL, so this does not validate native multi-process or high-concurrency deployment. [Official PGlite documentation](https://pglite.dev/docs/pglite-socket)

## 未验证与边界 / Not verified and limitations

- 未使用真实模型或 embedding 凭证。测试替换了模型及 embedding 响应；不能当作真实 Claude 质量、延迟、计费或供应商权限验证。
  No real model or embedding credentials were used. Provider responses were replaced in tests; this does not validate Claude quality, latency, billing, or access.
- 没有微信真机或原有 Next.js 集成验收，没有执行 Docker Compose 原生 PostgreSQL 启动验收。
  No WeChat-device or original Next.js integration acceptance, and no native PostgreSQL Docker Compose startup acceptance.
- 英文译文没有临床/安全效果验证；不自动切换为英文回复。
  English translations have no clinical/safety-effect validation and do not automatically enable English replies.
- 已加入 68 张方法卡，但尚未用真实 embedding 服务完成导入与检索效果验证。
  The 68 cards are included, but importing and retrieval quality with a real embedding service remain unverified.
- 第三方依赖会提示可选 spaCy / BM25 扩展未安装；当前验证使用向量路径。测试还出现第三方 SQLite 资源释放提示和测试客户端弃用提示，未阻止上述检查通过，不代表额外扩展已安装或验证。
  Dependencies warn about absent optional spaCy/BM25 extras; this release tests the vector path. A third-party SQLite resource warning and a test-client deprecation warning also occurred without failing the checks. Optional extras were not installed or validated.
- 静态扫描不是零泄露保证。后续更改、凭证配置或添加数据后，必须重新检查；本次没有扫描或公开父项目的 Git 历史。
  Static scanning is not a zero-leak guarantee. Recheck after edits, credential configuration, or data additions. The parent project's Git history was neither scanned for this release nor published.
