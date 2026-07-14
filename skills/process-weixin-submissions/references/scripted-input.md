# Scripted input contract

The Ticket 01 tracer accepts one JSON input window containing exactly one task header followed by one Official Account article.

```json
{
  "schema_version": 1,
  "window_id": "fixture-window-001",
  "messages": [
    {
      "kind": "task_header",
      "text": "#投稿\n目标: author-id\n要求:\n可选的多行改写要求"
    },
    {
      "kind": "official_account_article",
      "title": "文章标题",
      "body": "通过脚本 fixture 提供的正文",
      "source_url": "https://example.com/article",
      "images": []
    }
  ]
}
```

Invoke the tracer from the Skill directory:

```text
python scripts/process_weixin_submissions.py run \
  --repository <absolute-task-repository-path> \
  --input <absolute-scripted-input-path> \
  --blog-adapter fake \
  --fake-blog-directory <absolute-fake-blog-path>
```

The target is required. Requirements may be omitted; the tracer records that the default rules were selected but deliberately uses a placeholder rewrite until the approved policy is integrated.

