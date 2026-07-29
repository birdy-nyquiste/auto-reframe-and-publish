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

The omitted publication selection is `none`. For an explicitly authorized validation-only automatic publication, add `--publication auto --fake-blog-directory <absolute-fake-blog-path>`. To exercise referenced-image upload as part of that run, also add `--image-policy upload --fake-blob-directory <absolute-fake-blob-path>`. For LSForum image publication, use `--publication auto --image-policy upload --env-file <project>/.env --blog-config <absolute-non-secret-config-path>`. Never supply `auto` unless the operator requested public publication for this run.

## Submission messages

Use a text message followed immediately by one Official Account article:

```json
[
  {
    "message_id": "message-1",
    "kind": "text",
    "text": "#投稿\n作者: Public author name\nauthor.slug：public-author\npostType: opinion\ncategory：AI\ntags: Kimi, AI\nfeatured：false\n洗稿指令:\n可选的多行洗稿指令"
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

The task header requires the localized field `作者`, which maps exactly to Blog `author.name`. `洗稿指令` is the only other localized field. Optional Blog fields use their exact API names: `author.slug`, `postType`, `category`, `tags`, and `featured`. Every field line accepts either the half-width separator `:` or the full-width separator `：`; this applies equally to localized and API-named fields. Nested Blog fields retain dotted paths; `tags` is comma-separated, `featured` is `true` or `false`, and `postType` is `article` or `opinion`. `洗稿指令` consumes the remainder of the message and should therefore be last. Omitted or empty instructions select default mode.

The parser rejects literal `author.name`, `文章数`, old `目标`/`要求` fields, unknown or duplicate fields, invalid Blog values, and workflow-owned Blog fields such as `title`, `content`, `image`, `slug`, `sourceUrl`, and `status`. Missing `作者`, non-adjacent articles, and unsupported message kinds create independent `needs_input` tasks. One task header still binds to exactly one immediately following article card. Scripted generation emits a validation placeholder; the real Codex generator applies the active versioned default prompt.

`scripted_capture` is a deterministic development adapter, not extra syntax that a WeChat sender must type. See [scripted-capture.md](scripted-capture.md) for media fixtures, evidence guarantees, and limitations. A legacy fixture with only `body`, optional `source_url`, and an empty `images` array remains accepted for existing core tests; new fixtures should use `scripted_capture`.
