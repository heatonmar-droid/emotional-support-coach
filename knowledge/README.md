# 知识库 / Knowledge

随包：68 张方法卡和 [13 组参考资料清单](SOURCES.md)。3,816 条书籍原文因再分发授权尚未核实而未附入；咨询原文明确排除。

Included: 68 method cards and an [inventory of 13 reference groups](SOURCES.md). The 3,816 book fragments are not bundled while redistribution permission remains unverified. Counseling transcripts are explicitly excluded.

## 方法卡 / Method cards

[method-cards.zh-CN.json](method-cards.zh-CN.json) 包含 68 张中文方法卡，来自实际运行版本的静态卡片文件。保留适用情境、目的、引导步骤、结束方式和边界；替换产品身份，重新编号，移除内部来源片段标识。没有加入咨询原文或用户记忆。

[method-cards.zh-CN.json](method-cards.zh-CN.json) contains 68 Chinese method cards from the running version's static card file. It retains situations, purpose, instructions, closing, and boundaries. Product identity is replaced, IDs are reassigned, and internal source-fragment identifiers are removed. No counseling transcripts or user memories are included.

卡片涵盖 ACT、CBT、DBT 相关练习，包括当下稳定、与念头拉开距离、澄清价值、小步行动和人际表达。它们是对话时的参考，不是诊疗方案，也不是这些方法有效性的验证结果。

The cards cover ACT-, CBT-, and DBT-related exercises, including grounding, distancing from thoughts, clarifying values, small actions, and interpersonal expression. They are conversation references, not treatment plans or evidence that this implementation is effective.

先配置数据库和 embedding 凭证，再在仓库根目录执行：

Configure the database and embedding credentials, then run from the repository root:

```bash
python manage.py init-db
python manage.py import-cards --file knowledge/method-cards.zh-CN.json
```

导入按 16 张一批调用配置的 embedding 服务，会产生供应商费用。重新导入相同 ID 会更新已有卡片；重启 API 后加载。库为空时不会检索方法卡。导入这 68 张卡不会自动启用书籍或其他实验语料。

Import calls the configured embedding provider in batches of 16 and incurs provider charges. Reimporting the same IDs updates existing cards; restart the API to load them. An empty table disables card retrieval. Importing these 68 cards does not enable books or other experimental corpora.

知识正文保留原中文，以免翻译改变检索和练习含义；本页、字段说明和接入文档提供中英对照。英文主提示词另见 [prompts](../prompts/README.md)。

Knowledge text remains in its original Chinese to avoid changing retrieval or exercise meaning through translation. This page, field explanations, and integration documents are bilingual. English main prompts are in [prompts](../prompts/README.md).

| 字段 / Field | 含义 / Meaning |
|---|---|
| `id` | 公开版稳定编号 / Stable public ID |
| `title` | 方法名称 / Method title |
| `category` | 分类 / Category |
| `text` | 提供给回复模型的完整方法卡 / Full card for the response model |
| `search_text` | 生成检索向量的文本 / Text used to build the retrieval embedding |

## 来源与许可 / Sources and licensing

方法卡是整理后的练习说明，来源体系包括 ACT、CBT 和 DBT。内部书籍片段编号不是完整的书目引用，公开版不把这些编号冒充可核验的出处。代码的 MIT 许可不授予任何第三方书籍、译文或出版物的版权。

The cards are compiled exercise instructions drawing on ACT, CBT, and DBT. Internal book-fragment IDs are not complete bibliographic references and are not presented as verifiable citations. The code's MIT license does not grant rights to third-party books, translations, or publications.
