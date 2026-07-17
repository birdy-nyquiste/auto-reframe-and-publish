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

Marker sending also uses a file-backed clipboard fixture:

```json
{
  "schema_version": 1,
  "owner_id": null,
  "text": ""
}
```

The adapter acquires exclusive ownership, discards any previous `text`, pastes the
marker through this clipboard, and clears the value on both normal and exceptional
exit. It never restores or records the previous clipboard contents. When
`--scripted-clipboard` is omitted, the CLI uses `<scripted-chat-stem>.clipboard.json`
beside the chat fixture.

`initialize` appends a baseline marker to `messages` and ignores all earlier messages. `run` appends one new marker, processes only messages between the previous and current markers, then moves `arrive_after_next_marker` after the new marker to emulate submissions arriving during processing.

Initialize from the Skill directory:

```text
python scripts/process_weixin_submissions.py initialize \
  --repository <absolute-task-repository-path> \
  --scripted-chat <absolute-scripted-chat-path> \
  --scripted-clipboard <absolute-scripted-clipboard-path>
```

Run one input window:

```text
python scripts/process_weixin_submissions.py run \
  --repository <absolute-task-repository-path> \
  --scripted-chat <absolute-scripted-chat-path> \
  --scripted-clipboard <absolute-scripted-clipboard-path>
```

The omitted publication selection is `none`. For an explicitly authorized validation-only automatic publication, add `--publication auto --fake-blog-directory <absolute-fake-blog-path>`. For LSForum, add `--publication auto --blog-config <absolute-non-secret-config-path>` instead. Never supply `auto` unless the operator requested public publication for this run.

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
    "scripted_capture": {
      "clipboard_text": "通过复制粘贴取得的文章正文",
      "source_url": "https://example.com/article",
      "article_end_observed": true,
      "all_static_images_captured": true,
      "media": []
    }
  }
]
```

The task header recognizes `目标`, optional `文章数: 1`, and optional `要求`. Requirements consume the remainder of the message. Omitted or empty requirements select the default placeholder behavior. Unknown or duplicate control fields, missing targets, non-adjacent articles, unsupported message kinds, and article counts other than one create independent `needs_input` tasks.

`scripted_capture` is a deterministic development adapter, not extra syntax that a WeChat sender must type. See [scripted-capture.md](scripted-capture.md) for media fixtures, evidence guarantees, and limitations. A legacy fixture with only `body`, optional `source_url`, and an empty `images` array remains accepted for existing core tests; new fixtures should use `scripted_capture`.
