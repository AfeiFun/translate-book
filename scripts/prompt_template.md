请把下面这份 Markdown 书稿片段翻译为 **{TARGET_LANGUAGE}**，写入指定的输出文件。

IMPORTANT REQUIREMENTS:

1. 严格保持 Markdown 格式：标题、段落、引用块、列表、表格、图片引用、脚注。
2. 只翻译文字内容，Markdown 语法、图片路径、文件名原样保留。
   - 数学公式（`$...$`、`$$...$$`）内字符一律不动。
   - 表格保持行列结构，只译单元格文字。
   - 脚注标记 `[^12]` 与定义 `[^12]:` 原位保留，不改编号、不移动，只译注释文字。
3. 删除空链接与行末多余的 `\`；不要删除独立成行的数字（可能是年份、章号或注释编号）。
4. 保证语义准确，译文自然；只输出译文正文，不要任何说明、提示或对话。
5. 严格按顺序翻译，不跳过、不合并、不增补原文没有的内容。
6. 保留全部图片引用 `![alt](path)`；原始 HTML 标签的 `alt`/`title` 属性内若出现 `"` `'` `<` `>` `&`，改写为弯引号或 `&quot;` `&#39;` `&lt;` `&gt;` `&amp;`，`src`/`href` 不动。
7. 标题层级：原文已有的 `#`/`##`/`###` 保持层级不变；仅当独立成行的短标题尚无 Markdown 标记时，按其在本片段中的层级补 `##` 或 `###`；不要给正文段落加标题。
8. 原文的斜体 `*...*`、粗体 `**...**` 强调原样保留（中文内部也保留标记）。
9. 译文使用目标语言的标准标点；数字、年份、页码、英文缩写保持半角。
10. 引文与文献信息：若源书为学术著作，注释中的作者、书名、期刊、出版社、页码默认保留原文，只译叙述性文字——除非下面的自定义要求另有规定。
11. 不要翻译本提示本身，也不要输出"以下是译文"之类的话。

{STYLE_BLOCK}

{CUSTOM_INSTRUCTIONS}

{TERM_TABLE}

{NEIGHBOR_CONTEXT}

## 输出元数据

同时写出观察文件 `{META_FILE}`，严格遵循 schema：

```json
{
  "schema_version": 1,
  "new_entities": [
    {"source": "Taig", "target_proposal": "泰格", "category": "person",
     "evidence": "<不超过200字符的原文引文>"}
  ],
  "alias_hypotheses": [
    {"variant": "Taig", "may_be_alias_of_source": "Tai", "evidence": "<引文>"}
  ],
  "attribute_hypotheses": [
    {"entity_source": "Tai", "attribute": "gender", "value": "male",
     "confidence": "high", "evidence": "<引文>"}
  ],
  "used_term_sources": ["Tai", "Manhattan"],
  "conflicts": [
    {"entity_source": "Tai", "field": "target", "injected": "泰",
     "observed_better": "太一", "evidence": "<引文>"}
  ]
}
```

- 不要包含 `chunk_id` 字段（chunk 身份来自文件名，写进去会被判为无效）。
- 只报告本片段真实出现、且术语表里没有的专名；证据必须摘自本片段原文。
- 空数组完全合法，不要为了"显得有产出"而编造实体。

## 完成要求

1. 读取 `{CHUNK_FILE}` 全文。
2. 翻译并写入 `{OUTPUT_FILE}`。
3. 写入 `{META_FILE}`。
4. 只回复一行：`{CHUNK_ID} done <输出字符数>`，不要粘贴译文。
