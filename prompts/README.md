# 提示词 / Prompts

| 文件组 / Group | 运行时版本 / Runtime | 对照译文 / Translation |
|---|---|---|
| daily | 中文原文 / Original Chinese | English |
| coach | 中文原文 / Original Chinese | English |
| safety | 英文原文 / Original English | 简体中文 |
| memory | 英文原文 / Original English | 简体中文 |
| memory-use | 英文原文 / Original English | 简体中文 |
| context-boundary | 英文原文 / Original English | 简体中文 |

两套中文主提示词使用通用的助手身份；四组共享提示词默认使用英文。译文单独保存，便于阅读、审查和二次开发。运行时只使用上表指定的语言版本，不拼接双语，也不因请求是英文就切换。

The Chinese main prompts use a generic assistant identity; the four shared prompts default to English. Translations are separate files for reading, review, and adaptation. Runtime uses only the language specified in the table; it neither concatenates both languages nor automatically switches for English input.

**英文译文不是经过验证的英语心理支持版本。** 当前安全回复、兜底话术和资源配置仍针对中文及中国大陆语境。要发布英语服务，应另外验证语言表现和所在地资源，不能只换一个提示词文件。译文中保留原有号码是对生产文本的忠实翻译，不是适用于全球的建议。

**The translations are not a validated English-language support product.** Safety replies, fallback wording, and resources retain the original Chinese/mainland-China context. An English deployment needs separate language and regional-resource validation. Numbers retained in translations describe the original text, not worldwide recommendations.

JSON 字段名和枚举不翻译。/ JSON field names and enum values remain unchanged.
