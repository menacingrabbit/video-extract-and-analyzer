# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Python tool that processes video files by extracting frames and generating AI-analyzed metadata. Scans the top level of a folder for video files, extracts frames at configurable positions via ffmpeg, drops near-identical frames, sends the rest in one request to `POST /analyze-multiple`, and writes per-video CSV files with title, description, and keywords.

## Tech Stack
- Python 3 single-script tool (no framework)
- Dependencies: `ffmpeg-python`, `requests` (see `requirements.txt`)
- Dev dependency: `pytest` (see `requirements-dev.txt`)
- System requirement: `ffmpeg` must be installed and available in PATH
- Virtual environment: `venv/` directory in project root

## Common Commands
### Setup
```bash
source venv/bin/activate  # Activate virtual environment
pip install -r requirements.txt
pip install -r requirements-dev.txt  # tests
```
Install ffmpeg system-wide (e.g., `brew install ffmpeg` on macOS).

### Run
```bash
python analyzer.py [VIDEO_DIR] [OPTIONS]  # Default: current directory
```

Options:
- `--output-dir`, `-o`: Output directory for CSV/thumbnails
- `--cleanup-thumbnails`, `-c`: Delete thumbnails after processing
- `--extensions`, `-e`: Comma-separated video extensions (default: `.mp4,.mov`)
- `--force`, `-f`: Reprocess videos even if CSV already exists (default: skip existing)
- `--frames`: Frame positions as duration fractions, e.g. `0.5,0.9` (default: `0.5`)
- `--dedup-threshold`: Perceptual-hash distance for duplicate detection; `0` disables (default: `8`)
- `--provider`: `gemini` or `openrouter` (default: server default)

### One-command run
```bash
./run_analysis.sh [VIDEO_DIR] [OPTIONS] [--merge] [--setup] [--dry-run]
```
Wrapper that creates/repairs `venv`, installs dependencies, checks `ffmpeg` and `.env`, runs `analyzer.py` with `--frames 0.5,0.9` by default, and optionally merges the CSVs. Relative `VIDEO_DIR`/`--output-dir` resolve against the caller's directory. `--help-analyzer` shows analyzer options.

### Test
```bash
pytest                                      # unit tests (mocked, fast)
RUN_INTEGRATION=1 pytest                    # adds real ffmpeg + local HTTP server
```

## Architecture
Single entry point `analyzer.py` with these steps per video:
1. **Frame extraction**: Probes duration once with `ffmpeg.probe`, extracts one frame per `--frames` fraction via ffmpeg CLI (`<basename>_001.jpg`, `_002`, …).
2. **Deduplication**: Computes a 64-bit dHash per frame (9×8 grayscale via ffmpeg) and drops frames within `--dedup-threshold` Hamming distance of an earlier frame.
3. **AI analysis**: Sends the remaining frames in one multipart request to `POST /analyze-multiple` (repeated `images` field) with `X-API-Key` auth from `.env`.
4. **CSV output**: Writes one row per video with metadata from the response (expects `{"title": "...", "description": "...", "keywords": "..."}`).

### Configuration
- **Auth**: API key loaded from `.env` (`API_KEY`), sent as `X-API-Key`. `.env` is gitignored.
- **Webhook**: `WEBHOOK_URL` in `.env` is the legacy `/analyze` URL; the multi-image URL is derived as `/analyze-multiple` on the same service. Defaults to the hardcoded URL in `analyzer.py`.
- **Form fields sent**: repeated `images` (files), `filename` (video name), `generateTwoPartKeywords=true`, `useFilename=true`, optional `provider`.
- **Environment loading**: `load_env()` reads `.env` manually (no python-dotenv dependency).

### Processing Behavior
- **Skip existing**: Videos with an existing CSV are skipped by default.
- **Force reprocessing**: `--force` / `-f` reprocesses and overwrites CSVs.
- **Extensions**: Normalized to lowercase with a leading dot; configurable via `--extensions`.
- **Partial failures**: If one frame fails to extract, the remaining frames are still analyzed; if none succeed, the video is skipped.

### Error Handling
- API response validated for JSON object type and expected keys.
- `429` and `5xx` responses are retried up to 3 times with exponential backoff (honoring `Retry-After`).
- `404`/`405` from `/analyze-multiple` triggers one fallback to the legacy `/analyze` endpoint with the first frame.
- Other `4xx` responses are not retried.
- Missing API key generates a warning but continues (empty key sent).
- ffmpeg errors are caught and printed.

## Output
- Thumbnails: `<basename>_001.jpg`, `<basename>_002.jpg`, … per video (auto-deleted with `--cleanup-thumbnails`; near-duplicates deleted before upload)
- Metadata: `<basename>.csv` per video with columns Filename, Title, Description, Keywords
- Output location controlled by `--output-dir` (defaults to input directory)
