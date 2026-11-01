# Multi-Image Analysis — Implementation Spec

> **Superseded (2026-11-01):** The backend now exposes `POST /analyze-multiple`.
> `docs/ANALYZE_MULTIPLE_API.md` is the authoritative contract; this document is kept
> as design history. Where the two differ, the API doc wins.

**Status:** Superseded
**Date:** 2026-10-31
**Scope:** Two coordinated changes:

1. **Backend** (`stock-photo-metadata-api`, Google Cloud Run) — accept multiple images in one request and return **one merged JSON** result.
2. **Client** (`video-extract-and-analyzer`) — extract configurable frames (`--frames`), deduplicate near-identical frames, and send them in a single request.

**Out of scope for v1:** blank-frame / fade detection, scene-change detection, client-side metadata merging, per-frame CSV rows, concurrency changes.

---

## 0. Handoff prompt (paste into the backend project's Claude Code instance)

> Implement the backend contract in section 1 of this spec. The service currently accepts a single `image` multipart field and returns `{"title","description","keywords"}`. Extend it to accept 1..N images in one request (`images` repeated field), send all of them to the vision model in a single call, and return the same JSON shape with one coherent result for the whole clip. Keep the legacy single-`image` behavior working. Add request validation, limits, error responses, and tests as specified. Do not change the response schema. Do not implement client-side concerns (sections 2–3) in the backend.

---

## 1. Backend contract

### 1.1 Endpoint

Keep the existing route:

```
POST /analyze
```

No new endpoint is required. The same route accepts either the legacy single-image form or the new multi-image form.

### 1.2 Request (multipart/form-data)

| Field | Type | Required | Notes |
|---|---|---|---|
| `images` | file, repeated | yes (new clients) | 1–5 images, chronological order, JPEG/PNG/WebP |
| `image` | file, single | yes (legacy clients) | Used only when `images` is absent |
| `filename` | string | no | Original video filename |
| `generateTwoPartKeywords` | string `"true"`/`"false"` | no | Preserve current behavior |
| `useFilename` | string `"true"`/`"false"` | no | Preserve current behavior |

**Resolution rule:** if at least one `images` part is present, use those and ignore `image`. Otherwise fall back to `image`. If both are absent → `400`.

**Order matters.** The client sends frames in ascending timestamp order. The backend must pass them to the model in that order and treat them as a temporal sequence.

### 1.3 Response

Unchanged schema — this is a hard compatibility requirement:

```json
{
  "title": "One coherent title for the whole clip",
  "description": "One coherent description of the whole clip",
  "keywords": "keyword1, keyword2, keyword3"
}
```

All three keys must always be present. Extra fields (e.g. `frames_received`) are allowed but must not replace or rename these keys.

### 1.4 Limits and validation

| Condition | Status | Body |
|---|---|---|
| 0 images | 400 | `{"error": "at least one image is required"}` |
| More than 5 images | 400 | `{"error": "at most 5 images are allowed"}` |
| Unsupported MIME type | 415 | `{"error": "unsupported image type"}` |
| Image too large (>10 MB each) | 413 | `{"error": "image too large"}` |
| Total request >25 MB | 413 | `{"error": "request too large"}` |
| Missing/invalid API key | 401 | `{"error": "unauthorized"}` |

Cloud Run caps request bodies at 32 MiB; stay below it. Errors must be JSON, not HTML.

### 1.5 Model prompt requirements

Send all images in **one** model call. The prompt must:

- State that the images are frames from a single video, in chronological order.
- Ask for **one** title, **one** description, and **one** keyword set for the clip as a whole — not a per-frame list.
- Instruct the model to describe the common subject and the overall progression when frames differ; not to invent content that is not visible.
- Require keywords to be comma-separated, deduplicated, ordered by relevance, and roughly 20–50 terms.
- Preserve the existing `generateTwoPartKeywords` semantics and output format if that flag is set.
- Preserve `useFilename` behavior if set.

Suggested prompt skeleton (adapt to the existing prompt style):

```
You are analyzing {N} frames sampled in chronological order from a single video clip.
Produce ONE coherent set of metadata for the video as a whole, not a description of
each frame. If the frames show different moments, describe the common subject and the
overall progression. Do not invent details that are not visible.

Return JSON only:
{"title": "...", "description": "...", "keywords": "kw1, kw2, ..."}

Keywords: comma-separated, deduplicated, relevance-ordered, 20-50 terms.
```

### 1.6 Backward compatibility and rollout

- Deploy the backend **before** the client starts sending `images`.
- Old clients sending `image` must keep working unchanged.
- New clients sending `images` must work with 1 image as well as N.
- The response schema must not change; a client that only knows the old schema must still parse the new responses.

### 1.7 Backend acceptance criteria

- [ ] `POST /analyze` with 2 `images` → 200 and one JSON object with all three keys.
- [ ] `POST /analyze` with 1 `images` part → 200.
- [ ] Legacy `POST /analyze` with `image` → 200, unchanged behavior.
- [ ] 0 images → 400 JSON error.
- [ ] 6 images → 400 JSON error.
- [ ] Unsupported type → 415 JSON error.
- [ ] Images are passed to the model in request order.
- [ ] A clip whose frames show different content yields one coherent title/description, not a concatenation of per-frame descriptions (manual check).
- [ ] Existing tests pass; new tests cover the cases above.

---

## 2. Client changes (`video-extract-and-analyzer`)

### 2.1 New CLI option

```
--frames 0.5,0.9
```

- Comma-separated fractions of the video duration, each strictly between 0 and 1.
- Parsed to floats, validated, sorted ascending, duplicates removed.
- **Default: `0.5`** — preserves current behavior. Recommended value once the backend is live: `0.5,0.9`.
- Maximum 5 fractions (matches the backend limit). More → exit with a clear error.
- Invalid input (non-numeric, `<=0`, `>=1`, empty) → argparse error, exit code 2.

### 2.2 Frame extraction

Refactor the current single-frame helper into something like:

```python
def extract_frame(video_path, image_path, fraction):
    duration = float(ffmpeg.probe(video_path)["format"]["duration"])
    (ffmpeg.input(video_path, ss=duration * fraction)
           .output(image_path, vframes=1)
           .overwrite_output()
           .run(capture_stdout=True, capture_stderr=True))
```

- Probe duration **once** per video, not per frame.
- Output naming: `<basename>_001.jpg`, `<basename>_002.jpg`, … zero-padded to 3 digits, in fraction order.
- If one frame fails to extract, log it and continue with the remaining frames. If **no** frame succeeds, skip the video (no API call, no CSV).
- Do **not** implement blank/fade detection in v1.

### 2.3 Frame deduplication (client-side, before upload)

Goal: avoid paying for and uploading frames that are visually near-identical.

**Algorithm — 64-bit dHash, no new dependency:**

1. For each extracted frame, run:

   ```
   ffmpeg -v error -i <frame> -vf scale=9:8,format=gray -f rawvideo -
   ```

   This yields exactly 72 bytes (9×8 grayscale).
2. For each of the 8 rows, compare each pixel with its right neighbour: `bit = pixel[i] > pixel[i+1]`. That produces 64 bits.
3. Compare hashes with Hamming distance.
4. Keep the first frame of a group; drop later frames whose distance to an already-kept frame is `<= threshold`.
5. Default threshold: **8** (of 64 bits). Expose `--dedup-threshold N`; `0` disables dedup.
6. Delete the dropped thumbnail files (log each), so the output directory only contains frames that were actually used.

If dedup leaves only one frame, send that single image (still via `images`, see 2.4).

### 2.4 Request construction

Send all kept frames in **one** request, preserving order:

```python
files = [
    ("images", (os.path.basename(p), open(p, "rb"), "image/jpeg"))
    for p in kept_frames
]
data = {
    "filename": filename,
    "generateTwoPartKeywords": "true",
    "useFilename": "true",
}
response = requests.post(WEBHOOK_URL, headers=HEADERS, files=files, data=data, timeout=(10, 120))
```

- Always use the `images` field for the new path, even with one image.
- Keep the existing `X-API-Key` and `Accept` headers.
- Add the timeout (see review item R3).

### 2.5 Fallback to legacy single-image

If `/analyze-multiple` returns **404 or 405** (endpoint not deployed), retry once with the legacy `POST /analyze` form:

```python
files = {"image": open(kept_frames[0], "rb")}
```

Log a warning that the backend appears to be older. Do not fall back on 400, 401, 403, 413, 415, 429, or 5xx — those are real request, auth, size, rate-limit, or server errors, not version mismatches.

### 2.6 Output and cleanup

- CSV remains **one row per video** with the merged response from the backend.
- `--cleanup-thumbnails` deletes **all** extracted frames, including duplicates already deleted (idempotent).
- Skip-existing (`--force`) logic is unchanged: a video is skipped if its CSV exists.
- Optional (recommended): write `<basename>_analysis.json` with the raw response and the frame list used, for debugging. Not required for v1.

### 2.7 Client acceptance criteria

- [ ] `--frames 0.5` behaves exactly like today (one frame, one image in the request).
- [ ] `--frames 0.5,0.9` extracts two thumbnails (`_001`, `_002`) and sends one request with two `images` parts.
- [ ] Frames are sent in ascending timestamp order.
- [ ] Near-identical frames are deduplicated (test with a static clip: 2 extracted → 1 uploaded).
- [ ] `--dedup-threshold 0` disables dedup.
- [ ] Invalid `--frames` values exit with code 2 and a clear message.
- [ ] More than 5 fractions is rejected.
- [ ] If one frame extraction fails, the remaining frames are still analyzed.
- [ ] If all extractions fail, the video is skipped without an API call.
- [ ] A 400/415/422 multi-image failure falls back to a single `image` request.
- [ ] `--cleanup-thumbnails` removes every frame file.
- [ ] CSV output is unchanged in shape and columns.
- [ ] Unit tests mock `requests.post` and `ffmpeg`; no network calls in tests.

---

## 3. Suggested implementation order

1. **Backend first:** accept `images` (1..N), single model call, unchanged response, validation + tests. Deploy.
2. **Client:** `--frames` parsing and multi-frame extraction (still sending only the first image if desired) — verify locally.
3. **Client:** send all kept frames via `images`; add dedup.
4. **Client:** add legacy fallback and tests.
5. Update `README.md` (`--frames`, `--dedup-threshold`, multi-image behavior) and `CLAUDE.md` (architecture note).

---

## 4. Open decisions (resolve before coding)

| Decision | Recommendation |
|---|---|
| Field name for multiple images | `images` repeated; keep `image` as legacy |
| Max frames | 5 |
| Dedup threshold default | 8/64 bits |
| Default `--frames` | `0.5` (opt in to `0.5,0.9`) |
| Client-side merge | None — backend returns the merged result |
| Blank-frame guard | Deferred (v1) |
| Sidecar JSON | Optional, recommended |

---

## 5. Reference: request examples

**New client (2 frames):**

```bash
curl -X POST "$WEBHOOK_URL" \
  -H "X-API-Key: $API_KEY" \
  -H "Accept: application/json" \
  -F "images=@clip_001.jpg;type=image/jpeg" \
  -F "images=@clip_002.jpg;type=image/jpeg" \
  -F "filename=clip.mp4" \
  -F "generateTwoPartKeywords=true" \
  -F "useFilename=true"
```

**Legacy client (unchanged):**

```bash
curl -X POST "$WEBHOOK_URL" \
  -H "X-API-Key: $API_KEY" \
  -F "image=@clip_001.jpg;type=image/jpeg" \
  -F "filename=clip.mp4"
```

Both must return:

```json
{
  "title": "...",
  "description": "...",
  "keywords": "..."
}
```
