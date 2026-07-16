# Scripted capture contract

`scripted_capture` emulates evidence already collected from one Official Account article. It is an internal validation fixture, not a WeChat sender template and not a substitute for the future Windows Computer Use adapter.

## Text and completeness

Provide copied article text, whether the article end was observed, and an optional best-effort source URL:

```json
{
  "clipboard_text": "通过文章界面复制并粘贴取得的完整正文",
  "source_url": null,
  "article_end_observed": true,
  "media": []
}
```

The body must be non-empty and always has capture method `copy_paste`; OCR text is not accepted. The source URL may be `null`. A false `article_end_observed` value keeps the task at `task_created` with a retryable `article_end_not_observed` blocker.

## Static media fixtures

Items in `media` are in article order. Every image or GIF occurrence receives its own ordered manifest record even when exact bytes are deduplicated in content-addressed storage.

Use original static bytes when available:

```json
{
  "kind": "image",
  "mime_type": "image/png",
  "capture_method": "original_bytes",
  "bytes_base64": "<base64>"
}
```

When original bytes are unavailable, provide the cropped static image and the unmodified viewport screenshot from which it was taken:

```json
{
  "kind": "image",
  "mime_type": "image/png",
  "capture_method": "viewport_crop",
  "bytes_base64": "<cropped-image-base64>",
  "viewport_mime_type": "image/png",
  "viewport_bytes_base64": "<unmodified-viewport-base64>",
  "crop": {"x": 10, "y": 20, "width": 300, "height": 180}
}
```

This records degradation `screenshot_crop`. Supported static MIME types are PNG, JPEG and WebP.

Represent a GIF with one selected static frame:

```json
{
  "kind": "gif",
  "static_frame_mime_type": "image/png",
  "static_frame_bytes_base64": "<base64>"
}
```

This records capture method `static_frame`, degradation `animation_removed`, and a warning.

## Unsupported embedded media

Represent embedded video or audio only by kind:

```json
{"kind": "video"}
```

```json
{"kind": "audio"}
```

Neither is downloaded or transcribed. The task continues with explicit warnings when copied text is sufficient. In the core fixture adapter, fewer than 20 non-whitespace text characters alongside embedded audio or video is a conservative validation heuristic for `media_only_source`; it creates a permanent failure. This threshold is not a production policy and must be replaced with operational evidence before production readiness.

## Evidence guarantees

- `raw/capture/manifest.json`, copied text, static assets and viewport screenshots are immutable once written.
- Asset paths are SHA-256 content addresses; MIME is manifest metadata rather than a filename extension.
- Rebuilding `sources/article.json` verifies copied-text, static-asset and viewport hashes, occurrence order, and capture-method metadata.
- Do not hand-edit evidence or the rebuilt source. Correct the fixture or adapter and create a new task.
