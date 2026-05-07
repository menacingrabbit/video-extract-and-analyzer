# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Python tool that processes video files by extracting thumbnails and generating AI-analyzed metadata. Scans for `.mp4`/`.mov` files, extracts middle-frame thumbnails via ffmpeg, sends them to a configured webhook, and writes per-video CSV files with title, description, and keywords.

## Tech Stack
- Python 3 single-script tool (no framework)
- Dependencies: `ffmpeg-python`, `requests`
- System requirement: `ffmpeg` must be installed and available in PATH

## Common Commands
### Setup
```bash
pip install ffmpeg-python requests
```
Install ffmpeg system-wide (e.g., `brew install ffmpeg` on macOS).

### Run
```bash
python analyzer.py [VIDEO_DIR]  # Default: current directory
```

## Architecture
Single entry point `analyzer.py` with three core steps per video:
1. **Thumbnail extraction**: Probes video duration with `ffmpeg.probe`, extracts frame at 50% duration via ffmpeg CLI.
2. **AI analysis**: Sends thumbnail as multipart form-data to `WEBHOOK_URL` (hardcoded in `analyzer.py:35`) with Bearer token auth from `.env`.
3. **CSV output**: Writes per-video CSV with metadata from webhook response (expects `{"title": "...", "description": "...", "keywords": "..."}`).

### Configuration
- **Auth**: API key loaded from `.env` file (`API_KEY` key), sent as `X-API-Key` header. `.env` is gitignored and not committed.
- **Webhook**: Modify `WEBHOOK_URL` in `analyzer.py:35` to change the AI service endpoint.
- **Form fields sent**: `image` (file), `filename` (video name), `generateTwoPartKeywords=true`, `useFilename=true`

## Output
- Thumbnails: `<basename>_001.jpg` per video (optional deletion commented out at `analyzer.py:126`)
- Metadata: `<basename>.csv` per video with columns Filename, Title, Description, Keywords
