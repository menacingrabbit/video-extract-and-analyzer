# Stock Photo Metadata API — `POST /analyze-multiple`

Client-facing API description for integrating with the multi-image analysis endpoint.

This document is self-contained: it describes the request, response, limits, errors, and the recommended client behavior. It does not assume access to the server source.

---

## 1. What it does

Analyzes **1–5 images in a single request** and returns **one coherent set of stock metadata** for the whole set: one title, one description, one keyword list.

It is intended for frames sampled from a single video clip. The server sends all images to the vision model in one call and asks for one merged result. Images are treated as a chronological sequence.

The existing `POST /analyze` endpoint is a separate, single-image endpoint and is unchanged. Use `/analyze-multiple` for every multi-frame request — including requests with only one frame.

**Response schema is identical to `/analyze`**, so existing response parsing can be reused.

---

## 2. Connection

| Item | Value |
|---|---|
| Method | `POST` |
| Path | `/analyze-multiple` |
| Content type | `multipart/form-data` |
| Auth | `X-API-Key: <SERVICE_API_KEY>` header on every request |
| Accept | `application/json` (recommended) |
| Recommended timeout | connect 10 s, read 120 s |

The service runs on Google Cloud Run. Cloud Run rejects request bodies above **32 MiB**; this endpoint's own limit is lower (25 MB total, see §5).

---

## 3. Request

`multipart/form-data` with a **repeated** `images` file field and optional scalar fields.

| Field | Type | Required | Notes |
|---|---|---|---|
| `images` | file, repeated | **yes** | 1–5 files. JPEG, PNG, or WebP. Send them in chronological order. |
| `filename` | string | no | Original video filename, e.g. `clip.mp4`. Used for optional filename-aware prompting and for labels. Defaults to the first file's name. |
| `generateTwoPartKeywords` | string `"true"` / `"false"` | no | `"true"` allows two-word phrases (max 40% of keywords). Defaults to false / single-word mode. |
| `useFilename` | string `"true"` / `"false"` | no | `"true"` lets the model use `filename` as extra context. Defaults to false. |
| `provider` | `"gemini"` \| `"openrouter"` | no | LLM provider. Defaults to `"gemini"`. |

Important details:

- **The field is `images` (plural), repeated.** There is no `image` field on this endpoint. Sending `image` returns `400`.
- **Order matters.** The server passes the files to the model in the order they appear in the multipart body. Do not sort or reorder them client-side after extraction.
- **Send one frame the same way**: one `images` part, not `image`.
- Scalar fields are strings in multipart, even the booleans. Send the literal `"true"` / `"false"`.

### Recommended URL configuration

If the client already has a webhook URL pointing at `.../analyze`, derive the new URL:

```python
_base = WEBHOOK_URL.rstrip("/")
if _base.endswith("/analyze"):
    _base = _base[: -len("/analyze")]

ANALYZE_MULTIPLE_URL = os.getenv(
    "ANALYZE_MULTIPLE_URL",
    f"{_base}/analyze-multiple",
)
```

---

## 4. Success response

**Status:** `200 OK`
**Content-Type:** `application/json`

```json
{
  "title": "One coherent title for the whole clip",
  "description": "One coherent description of the whole clip",
  "keywords": "sunset, lake, mountain, reflection, calm, water"
}
```

| Field | Type | Description |
|---|---|---|
| `title` | string | One title for the whole set (75–120 characters, no leading articles). |
| `description` | string | One description for the whole set (125–180 characters). |
| `keywords` | string | **Comma-separated string**, not an array. Lowercase, relevance-ordered, already deduplicated server-side. Typically 40–48 terms. |

The same three keys are always present. No additional fields are returned.

---

## 5. Limits

| Limit | Value | Exceeded → |
|---|---|---|
| Images per request | 1–5 | `400` |
| Size per image | 10 MB | `413` |
| Total size of all files | 25 MB | `413` |
| Allowed types | `image/jpeg`, `image/png`, `image/webp` | `415` |

The per-file and total limits are enforced before any model call.

---

## 6. Errors

All errors are JSON with an `error` string. Multer/body-parser errors are also JSON — the service never returns an HTML error page.

| Status | Body | When |
|---|---|---|
| `400` | `{"error":"at least one image is required"}` | No `images` parts. |
| `400` | `{"error":"at most 5 images are allowed"}` | More than 5 image parts. |
| `400` | `{"error":"unexpected file field: image"}` | A file was sent under an unknown field (e.g. the legacy `image` field). |
| `401` | `{"error":"Unauthorized: Invalid API key"}` | Missing or wrong `X-API-Key`. |
| `413` | `{"error":"image too large"}` | One file is over 10 MB. |
| `413` | `{"error":"request too large"}` | All files together exceed 25 MB. |
| `415` | `{"error":"unsupported image type"}` | A file is not JPEG/PNG/WebP. |
| `500` | `{"error":"Internal server error","message":"..."}` | Model/provider failure or unexpected server error. |

Handle `500` as a transient/server failure; the `message` field may contain provider details. Do not retry `400`, `401`, `413`, or `415` unchanged — those will fail again.

---

## 7. Client integration guidance

### 7.1 Frame order

Extract frames in ascending timestamp order and upload them in that order. The server preserves multipart order when calling the model.

### 7.2 One request per video

Combine all kept frames into **one** request. Do not call the endpoint once per frame — that produces per-frame metadata, not a coherent result.

### 7.3 Deduplicate before upload

The server does not deduplicate images. If frames are near-identical (static scenes, fades), drop duplicates client-side before building the multipart body. Sending fewer, distinct frames improves both quality and cost.

### 7.4 Version detection / legacy fallback

`/analyze-multiple` was added after the original `/analyze`. If a deployment is older, the new path returns:

- `404` (path not found) or
- `405` (method not allowed, if the platform intercepts it)

On **`404` or `405` only**, retry once against the legacy `POST /analyze` with the **first frame** in a single `image` field:

```
POST /analyze        (multipart)
  image=<first frame>
  filename=<video filename>
```

Do **not** fall back on `400`, `401`, `403`, `413`, `415`, `429`, or `5xx` — those are real request, auth, size, rate-limit, or server errors, not version mismatches.

The legacy response has the same `{title, description, keywords}` shape, so no response parsing changes are needed.

### 7.5 Retries

- Retry `429` and `5xx` with exponential backoff (e.g. 3 attempts, 1 s / 2 s / 4 s).
- Do not retry other `4xx`.
- Use `timeout=(10, 120)` (connect, read) in `requests`.

### 7.6 Output

The response applies to the video as a whole. Write **one CSV row per video**, not one per frame. Keep any per-frame paths only for debugging (optional sidecar JSON).

---

## 8. Examples

### 8.1 curl

```bash
curl -X POST "$ANALYZE_MULTIPLE_URL" \
  -H "X-API-Key: $SERVICE_API_KEY" \
  -H "Accept: application/json" \
  -F "images=@clip_001.jpg;type=image/jpeg" \
  -F "images=@clip_002.jpg;type=image/jpeg" \
  -F "filename=clip.mp4" \
  -F "generateTwoPartKeywords=true" \
  -F "useFilename=true" \
  -F "provider=gemini"
```

### 8.2 Python (`requests`)

```python
import os
from contextlib import ExitStack

import requests

BASE_URL = os.environ["STOCK_METADATA_API_URL"].rstrip("/")
API_KEY = os.environ["STOCK_METADATA_API_KEY"]


def analyze_frames(frame_paths: list[str], filename: str, provider: str = "gemini") -> dict:
    """Send 1-5 frames to /analyze-multiple and return the merged metadata."""
    if not 1 <= len(frame_paths) <= 5:
        raise ValueError("analyze_frames expects 1-5 frames")

    with ExitStack() as stack:
        files = [
            (
                "images",
                (os.path.basename(path), stack.enter_context(open(path, "rb")), "image/jpeg"),
            )
            for path in frame_paths
        ]

        response = requests.post(
            f"{BASE_URL}/analyze-multiple",
            headers={
                "X-API-Key": API_KEY,
                "Accept": "application/json",
            },
            files=files,
            data={
                "filename": filename,
                "generateTwoPartKeywords": "true",
                "useFilename": "true",
                "provider": provider,
            },
            timeout=(10, 120),
        )

    response.raise_for_status()
    return response.json()
```

### 8.3 Legacy fallback sketch

```python
def post_frames(frame_paths, filename, headers):
    response = post_multi_image(frame_paths, filename, headers)

    if response.status_code in (404, 405):
        # Older deployment: retry the legacy single-image endpoint.
        with open(frame_paths[0], "rb") as handle:
            response = requests.post(
                LEGACY_ANALYZE_URL,
                headers=headers,
                files={"image": (os.path.basename(frame_paths[0]), handle, "image/jpeg")},
                data={"filename": filename},
                timeout=(10, 120),
            )

    response.raise_for_status()
    return response.json()
```

---

## 9. Handoff prompt for the consuming project

Copy this into the other project's Claude Code instance (adjust names to match the project):

> Integrate the new `POST /analyze-multiple` endpoint from the Stock Photo Metadata API.
>
> - Send 1–5 extracted video frames in **one** `multipart/form-data` request using a **repeated `images` file field** (JPEG/PNG/WebP, max 10 MB each, 25 MB total), in ascending timestamp order.
> - Include `filename` (the video file name) and the string fields `generateTwoPartKeywords` and `useFilename`. Optionally include `provider` (`gemini` or `openrouter`; default `gemini`).
> - Authenticate with the `X-API-Key` header from existing config. Use a connect/read timeout of 10 s / 120 s.
> - The response is `{"title": string, "description": string, "keywords": string}` — `keywords` is a **comma-separated string**, not an array.
> - Treat the response as one result for the whole video (one CSV row per video).
> - On **404/405 only**, retry once with the legacy `POST /analyze` endpoint using the first frame in the single `image` field. Do not fall back on any other status.
> - Retry `429` and `5xx` with exponential backoff; do not retry other `4xx`.
> - Validate locally that 1–5 frames are sent; more than 5 is rejected with `400`.
> - Add unit tests with mocked HTTP; no network calls in tests.

---

## 10. Reference

- Full backend contract and rollout notes: `docs/MULTI_IMAGE_SPEC.md`
- Single-image endpoint (legacy): `POST /analyze`, single `image` field, same response shape.
