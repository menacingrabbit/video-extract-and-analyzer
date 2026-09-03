# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Python tool that processes video files by extracting thumbnails and generating AI-analyzed metadata. Scans for video files, extracts middle-frame thumbnails via ffmpeg, sends them to a configured webhook, and writes per-video CSV files with title, description, and keywords.

## Tech Stack
- Python 3 single-script tool (no framework)
- Dependencies: `ffmpeg-python`, `requests` (see `requirements.txt`)
- System requirement: `ffmpeg` must be installed and available in PATH
- Virtual environment: `venv/` directory in project root

## Common Commands
### Setup
```bash
source venv/bin/activate  # Activate virtual environment
pip install -r requirements.txt
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

## Architecture
Single entry point `analyzer.py` with three core steps per video:
1. **Thumbnail extraction**: Probes video duration with `ffmpeg.probe`, extracts frame at 50% duration via ffmpeg CLI.
2. **AI analysis**: Sends thumbnail as multipart form-data to `WEBHOOK_URL` with `X-API-Key` header auth from `.env`.
3. **CSV output**: Writes per-video CSV with metadata from webhook response (expects `{"title": "...", "description": "...", "keywords": "..."}`).

### Configuration
- **Auth**: API key loaded from `.env` file (`API_KEY` key), sent as `X-API-Key` header. `.env` is gitignored and not committed.
- **Webhook**: Configurable via `WEBHOOK_URL` in `.env`, defaults to hardcoded URL in `analyzer.py`.
- **Form fields sent**: `image` (file), `filename` (video name), `generateTwoPartKeywords=true`, `useFilename=true`
- **Environment loading**: `load_env()` function reads `.env` manually (no python-dotenv dependency).

### Processing Behavior
- **Skip existing**: By default, videos with existing CSV files are skipped (message printed)
- **Force reprocessing**: Use `--force` / `-f` flag to reprocess all videos and overwrite existing CSVs
- **Extensions**: Configurable via `--extensions` flag (default: `.mp4,.mov`)

### Error Handling
- API response validated for JSON format and expected keys (`title`, `description`, `keywords`)
- Missing API key generates warning but continues (empty key sent)
- ffmpeg errors caught and printed via `ffmpeg.Error` exception

## Output
- Thumbnails: `<basename>_001.jpg` per video (can auto-delete with `--cleanup-thumbnails`)
- Metadata: `<basename>.csv` per video with columns Filename, Title, Description, Keywords
- Output location controlled by `--output-dir` (defaults to input directory)
