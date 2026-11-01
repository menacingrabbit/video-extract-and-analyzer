# Project Review — Video Extract and Analyzer

**Date:** 2026-10-31
**Scope:** `translate-to-english` @ `64ed95a` (the latest state). `main` is behind and lacks the CLI options, `merge_csvs.py`, `requirements.txt`, and the translation.
**All line references below are for that branch.**

Ranking goes from must-fix (correctness, data safety, security) to nice-to-have. Effort: **S** ≈ under 30 min, **M** ≈ 1–2 h, **L** ≈ half a day or more.

---

## Top 5 to do first

1. **R1/R2** — the merge script can silently corrupt columns or crash on empty input (both reproduced below).
2. **R3** — no HTTP timeout; one stalled response freezes the whole batch.
3. **R4** — a missing API key only warns, then every video is sent with an empty key.
4. **R7** — the script always exits 0, even when every video failed.
5. **R14** — README contradicts the actual configuration path (`.env` vs. editing `analyzer.py`).

---

## P0 — Correctness, data safety, security

### R1. `merge_csvs.py` merges files with different headers without warning
**Where:** `merge_csvs.py:98-113`
**Status:** Reproduced. Merging a file with `Filename,Title,Description,Keywords` and one with `Name,Alt,Desc,Kw` succeeded with exit 0 and wrote the second file's values under the first file's headers.
**Why it matters:** Silent data corruption — a downstream import will attribute titles to the wrong columns and nobody gets an error.
**Fix:** Read the header of every input. If it differs from the first, abort (or map columns by name). Also validate that each data row's length matches the header width.

### R2. Empty first CSV crashes the merge and leaves a partial output
**Where:** `merge_csvs.py:99-113`
**Status:** Reproduced: `merge_csvs.py empty.csv b.csv` → `'NoneType' object has no attribute 'writerow'`, exit 1, truncated output file left behind.
**Why it matters:** The `writer` is only created while processing file 0; if that file is empty, later files hit `None`.
**Fix:** Determine the header from the first *non-empty* file before creating the writer; if all inputs are empty, fail cleanly without creating an output file. Write to a temp file and rename on success.

### R3. No timeout on the webhook request
**Where:** `analyzer.py:134`
**Why it matters:** `requests.post` without `timeout` can hang indefinitely. In a batch this blocks all remaining videos with no indication of progress.
**Fix:** `timeout=(10, 120)` (connect, read), ideally configurable via CLI/env.

### R4. Missing API key does not stop the run
**Where:** `analyzer.py:88-100`
**Why it matters:** An empty `X-API-Key` is sent for every video. The script still does all ffmpeg work, then gets 401s, and (see R7) exits successfully. It also contradicts the security expectation set by `.env.example`.
**Fix:** Fail fast with exit code 2 before scanning when `API_KEY` is missing/empty. If you need keyless testing, add an explicit `--allow-empty-key` flag. Update `CLAUDE.md:52`, which currently documents the unsafe behavior.

### R5. Non-object JSON responses crash the analyzer
**Where:** `analyzer.py:138-146`, `analyzer.py:189-191`
**Why it matters:** `response.json()` can legally return a list or a string. Then `metadata.keys()` (line 145) or `metadata.get(...)` (line 189) raises `AttributeError`, aborting the whole run.
**Fix:** `if not isinstance(metadata, dict): print error; return None`. Also coerce `keywords` to a string if the API ever returns a list.

---

## P1 — Reliability and operational correctness

### R6. No retry/backoff for transient API failures
**Where:** `analyzer.py:134-149`
**Why it matters:** A single 429/500/503 loses that video silently; on a 500-file batch, transient errors are near-certain.
**Fix:** Retry 429/5xx (and connection errors) 3–5 times with exponential backoff + jitter, honoring `Retry-After`. Do not retry 4xx such as 401/403.

### R7. Exit code is always 0, and there is no run summary
**Where:** `analyzer.py:152-201`
**Why it matters:** CI/cron can't distinguish "all good" from "0 of 200 processed". Missing folder also returns 0 (`analyzer.py:153-155`).
**Fix:** Count `processed / skipped / failed`, print a summary, and `sys.exit(1)` if any video failed or nothing was found (define the policy explicitly).

### R8. `.env` is resolved relative to the current working directory
**Where:** `analyzer.py:75`
**Why it matters:** Running `python /path/to/analyzer.py /videos` from another directory prints a warning and continues with no key and the default webhook — a confusing failure that R4 would otherwise make loud.
**Fix:** Look next to the script (`Path(__file__).resolve().parent / ".env"`), optionally with an `--env-file` override, or support real environment variables first.

### R9. Duration probing is fragile
**Where:** `analyzer.py:109-118`
**Why it matters:** `probe['format']['duration']` is absent for some containers → uncaught `KeyError`; at 50 % of a very short or damaged file, frame extraction can yield no frame; `ffmpeg.Error` is the only caught type.
**Fix:** Fall back to a stream duration; clamp the seek to `max(0, duration/2 - small epsilon)`; retry at 25 % / 10 % / 0 s; catch `KeyError`/`ValueError` and report the filename.

### R10. Only the top level of the video folder is scanned
**Where:** `analyzer.py:160`
**Why it matters:** Nested libraries are common; users will silently get only the first level.
**Fix:** Add `--recursive` (preferred, explicit) using `os.walk`/`Path.rglob`, and/or accept a glob. Print the number of candidates found before processing.

### R11. Basename collisions silently skip or overwrite
**Where:** `analyzer.py:162-169`
**Why it matters:** `a.mp4` and `a.mov` both map to `a.csv`. Without `--force` the second is reported as "CSV exists" and skipped; with `--force` it overwrites the first. Either way, data is lost with no warning.
**Fix:** Detect duplicate basenames up front and either suffix them (`a_1.csv`) or fail with a clear message.

### R12. Extension handling is inconsistent
**Where:** `analyzer.py:103`, `analyzer.py:161`
**Why it matters:** The filename is lowercased but the extensions are not: `--extensions .MP4` silently matches nothing. Spaces are not stripped (`".mp4, .mov"` breaks the second one), and `--extensions ""` produces `('',)`, which matches every file.
**Fix:** Normalize: `tuple(e.strip().lower() for e in args.extensions.split(',') if e.strip())`, ensure a leading dot, and reject an empty result.

### R13. Input path is not validated as a directory
**Where:** `analyzer.py:153-158`
**Why it matters:** Passing a file path passes `os.path.exists` and then raises an uncaught `NotADirectoryError` at `os.listdir`.
**Fix:** Use `os.path.isdir(VIDEO_DIR)` and exit non-zero with a clear message.

### R14. Thumbnails are deleted even when analysis failed
**Where:** `analyzer.py:195-198`
**Why it matters:** With `--cleanup-thumbnails`, an API failure removes the only evidence you'd need to retry or debug. The block is a sibling of `if metadata:`, not inside it.
**Fix:** Delete on success; on failure keep the thumbnail (or add `--keep-thumbnails-on-error`).

### R15. README setup and webhook instructions are wrong/inconsistent
**Where:** `README.md:17`, `README.md:44`
**Why it matters:**
- Line 17 tells users to `pip install ffmpeg-python requests` instead of using `requirements.txt` (the requested single source of truth).
- Line 44 says to edit `analyzer.py:35`, but `WEBHOOK_URL` is supported in `.env` (`analyzer.py:86-96`), and `CLAUDE.md:41` already documents that correctly.
**Fix:** `pip install -r requirements.txt`; document `WEBHOOK_URL` in `.env` (or drop the `WEBHOOK_URL` support and stop advertising it).

---

## P2 — Maintainability and testability

### R16. Module-level side effects make the code untestable
**Where:** `analyzer.py:93-103`
**Why it matters:** Importing `analyzer` runs `parse_args()` and `load_env()` and creates globals (`args`, `HEADERS`, `VIDEO_DIR`, …). You cannot unit-test `extract_thumbnail` or `get_ai_metadata` without hijacking `sys.argv`.
**Fix:** Move all wiring into `main()`; pass a small config object/dataclass (or explicit parameters) into the functions. Keep `if __name__ == "__main__": main()`.

### R17. No tests
**Where:** repository
**Why it matters:** Both P0 merge bugs would have been caught by three lines of tests.
**Fix:** Add `pytest` with stdlib-only tests for `merge_csvs` (empty first file, header mismatch, single file, duplicate rows) and mocked tests for `analyzer` (`requests.post`, `ffmpeg.probe`, `ffmpeg.run`), covering skip/force, extension normalization, CSV schema, and failure exit codes.

### R18. A committed `__pycache__` binary
**Where:** `__pycache__/analyzer.cpython-313.pyc` (tracked since `d6b8cb0`)
**Why it matters:** Python bytecode doesn't belong in git; it's stale and still contains the old German strings. `.gitignore` already lists `__pycache__/`, but that doesn't affect tracked files.
**Fix:** `git rm --cached __pycache__/analyzer.cpython-313.pyc`.

### R19. Unpinned dependencies
**Where:** `requirements.txt:1-2`
**Why it matters:** `ffmpeg-python` and `requests` without versions means two machines can resolve differently; `requests` major versions have changed APIs.
**Fix:** Pin compatible ranges (e.g. `requests>=2.31,<3`) or use a lock file (`pip-tools`/`uv`).

### R20. Dead code and unused imports
**Where:** `analyzer.py:27` (`sys` never used), `analyzer.py:36` (`DEFAULT_EXTENSIONS` never referenced; the default is duplicated at `analyzer.py:62`)
**Fix:** Remove, or use `DEFAULT_EXTENSIONS` as the single default in `parse_args`.

### R21. Broad `except Exception` in the merge hides real bugs
**Where:** `merge_csvs.py:118-120`
**Why it matters:** Programming errors are reported as "Error merging CSV files", which is why R2 looked like a clean failure rather than a traceback.
**Fix:** Catch `OSError`/`csv.Error` explicitly and let unexpected exceptions surface (or re-raise after logging).

### R22. Non-atomic output writes
**Where:** `analyzer.py:182-193`, `merge_csvs.py:89`
**Why it matters:** Interrupting a run leaves a partial CSV. Because the analyzer's skip logic is "CSV exists", a truncated file is treated as completed work forever.
**Fix:** Write to `<name>.csv.tmp` and `os.replace()` on success; optionally validate the CSV has a header + data row before considering it done.

### R23. No lint or CI
**Where:** repository
**Why it matters:** R20 (unused imports) and several consistency issues are lint-detectable.
**Fix:** Add `ruff` (+ optional `black`) config and a GitHub Actions workflow running lint + pytest on push/PR. Keep it to one small file to start.

### R24. `merge_csvs.py` is undocumented
**Where:** `README.md`
**Why it matters:** A second entry point that users won't discover; its output naming (`<first>-merged.csv`) and header behavior are non-obvious.
**Fix:** Add a short "Merging results" section with examples, including the shell-glob caveat below.

---

## P3 — Quality of life

### R25. Structured logging instead of `print`
Add `logging` with timestamps and `--quiet`/`--verbose`. Also truncate `response.text` in error messages — a 50 KB HTML error page currently floods the terminal.

### R26. Bounded parallelism
`--workers N` with `ThreadPoolExecutor` for large batches. Keep the default at 1 to avoid API rate limits, and pair with R6 backoff.

### R27. Make the request configurable
Expose the hardcoded form fields (`generateTwoPartKeywords`, `useFilename`, `analyzer.py:129-133`) and thumbnail choices (timestamp/quality/scale) as flags or env vars.

### R28. Merge ergonomics
- `--output FILE` (today the name is always derived from the first input)
- accept a directory or glob directly (`merge_csvs.py results/*.csv` is expanded by the shell, but `results/` alone isn't)
- `--dedupe` by `Filename`, `--sort` by `Filename`
- avoid clobbering, and **exclude already-merged files** — rerunning `python merge_csvs.py *.csv` after a merge will re-ingest `*-merged.csv` and duplicate rows

### R29. `--dry-run` and `--version`
`--dry-run` lists what would be processed (and what would be skipped) without calling ffmpeg or the API. `--version` is useful for bug reports.

### R30. Progress and summary
Print `[12/180] processing x.mp4` and a final tally. This pairs naturally with R7.

### R31. Packaging
A `pyproject.toml` with a console script (`video-analyzer = analyzer:main`) and `requirements-dev.txt` would make installation and testing conventional. This also forces the R16 refactor (importable module).

### R32. `.env` parsing robustness
The hand-rolled parser doesn't handle quotes, inline comments, `export KEY=...`, or a missing trailing newline. Either support those cases or add `python-dotenv` (small, well-known dependency) — and document the tradeoff.

### R33. Combined output from the analyzer
An option like `--combined results.csv` would remove the need to run `merge_csvs.py` for the common case; keep the merge script for existing per-video results.

---

## Environment and repository notes

- **Broken virtualenv:** `venv/bin/python3.13` symlinks to `/opt/homebrew/opt/python@3.13/bin/python3.13`, which no longer exists. Recreate with `python3 -m venv venv && venv/bin/pip install -r requirements.txt`.
- **Plaintext token:** `.claude/settings.json` contains an `ANTHROPIC_AUTH_TOKEN`. It is gitignored, so it isn't committed, but rotate it if this directory is ever shared or synced.
- **Branch state:** `main` is 1 commit ahead of `origin/main` and does not contain the feature branches. Decide the merge/PR order before further work; this review file is untracked and currently sits on `main`.
- **No license file:** add one if the project will be shared.
- **`examples/` is ignored:** the sample CSVs/videos are useful documentation but not versioned. Consider committing a tiny fixture set instead.

---

## Suggested sequence

1. **Data integrity:** R1, R2 (+ tests for them in R17).
2. **Batch safety:** R3, R4, R5, R7.
3. **Correctness edges:** R8–R15 (start with R15, since it's documentation-only).
4. **Refactor + tests:** R16, R17, then R18–R23.
5. **Polish:** R25–R33 as time allows.
