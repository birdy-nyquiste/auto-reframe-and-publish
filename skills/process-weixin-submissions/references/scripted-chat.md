# Scripted chat contract

Use a mutable JSON fixture to emulate the File Transfer Assistant conversation during core validation:

```json
{
  "schema_version": 1,
  "conversation": "file-transfer-assistant",
  "messages": [],
  "arrive_after_next_marker": []
}
```

`initialize` appends a baseline marker to `messages` and ignores all earlier messages. `run` appends one new marker, processes only messages between the previous and current markers, then moves `arrive_after_next_marker` after the new marker to emulate submissions arriving during processing.

Initialize from the Skill directory:

```text
python scripts/process_weixin_submissions.py initialize \
  --repository <absolute-task-repository-path> \
  --scripted-chat <absolute-scripted-chat-path>
```

Run one input window:

```text
python scripts/process_weixin_submissions.py run \
  --repository <absolute-task-repository-path> \
  --scripted-chat <absolute-scripted-chat-path> \
  --fake-blog-directory <absolute-fake-blog-path>
```

## Submission messages

Use a text message followed immediately by one Official Account article:

```json
[
  {
    "message_id": "message-1",
    "kind": "text",
    "text": "#投稿\n目标: author-id\n要求:\n可选的多行改写要求"
  },
  {
    "message_id": "message-2",
    "kind": "official_account_article",
    "title": "文章标题",
    "body": "脚本化采集正文",
    "source_url": "https://example.com/article",
    "images": []
  }
]
```

The task header recognizes `目标`, optional `文章数: 1`, and optional `要求`. Requirements consume the remainder of the message. Omitted or empty requirements select the default placeholder behavior. Unknown or duplicate control fields, missing targets, non-adjacent articles, unsupported message kinds, and article counts other than one create independent `needs_input` tasks.
