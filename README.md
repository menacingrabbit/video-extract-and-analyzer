# Video Extract and Analyzer

Python tool that processes video files by extracting thumbnails and generating metadata via AI analysis.

## How it works

1. Scans the top level of a folder for video files (`.mp4`, `.mov` by default)
2. Extracts one frame per configured position (default: 50% of the duration) using ffmpeg
3. Drops near-identical frames using a perceptual hash
4. Sends the remaining frames in one request to `POST /analyze-multiple`
5. Writes one CSV file per video with AI-generated metadata (title, description, keywords)

## Prerequisites

- Python 3
- `ffmpeg` available in your `PATH` (e.g., `brew install ffmpeg` on macOS)

## Setup

Create a virtual environment and install the dependencies from `requirements.txt`:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`ffmpeg` is a system dependency and is not installed by pip, so it must be installed separately (see Prerequisites).

For development, install the test dependencies and run the suite:

```bash
pip install -r requirements-dev.txt
pytest
```

Run the opt-in integration test (real ffmpeg extraction plus a local HTTP server, no external API):

```bash
RUN_INTEGRATION=1 pytest tests/test_integration.py
```

## Quick Start

`run_analysis.sh` wraps the whole pipeline: it creates or repairs the virtual environment, installs dependencies, checks `ffmpeg` and `.env`, extracts frames, calls the API, and optionally merges the CSVs.

```bash
./run_analysis.sh /path/to/videos
./run_analysis.sh /path/to/videos --merge
./run_analysis.sh /path/to/videos --frames 0.5 --cleanup-thumbnails
```

- Defaults to `--frames 0.5,0.9`; pass `--frames` to override.
- `--merge` combines the generated CSVs into one `*-merged.csv`.
- `--setup` only prepares the environment and exits.
- `--dry-run` prints the analyzer command without running it.
- `--help-analyzer` shows the underlying `analyzer.py` options.
- Relative `VIDEO_DIR` and `--output-dir` paths are resolved from the directory you run it in.

## Configuration

1. Copy the example env file and add your API key:

```bash
cp .env.example .env
```

2. Edit `.env` and add your API key:

```
API_KEY=your_actual_key_here
```

**API Request format:** The script sends a multipart form request with:
- `images`: One or more extracted frames (repeated field), in chronological order
- `filename`: Original video filename
- `generateTwoPartKeywords`: Set to `"true"`
- `useFilename`: Set to `"true"`

If `/analyze-multiple` is unavailable, the fallback request uses the legacy single `image` field with the first frame.

Authentication is done via the `X-API-Key` header.

3. (Optional) Change the AI service endpoint by setting `WEBHOOK_URL` in `.env`:

```
WEBHOOK_URL=https://your-endpoint.example.com/analyze
```

If `WEBHOOK_URL` is not set, the default hardcoded in `analyzer.py` is used.

The client derives `POST /analyze-multiple` from `WEBHOOK_URL` (same service). If that endpoint is unavailable (`404`/`405`), it falls back to the legacy `/analyze` endpoint using the first frame.

Note: The `.env` file is excluded from git via `.gitignore` to keep your key secure.

## Usage

Run the analyzer with optional arguments:

```bash
python analyzer.py [VIDEO_DIR] [OPTIONS]
```

**Positional arguments:**
- `video_dir`: Folder containing videos to process (optional, default: current directory)

**Options:**
- `--output-dir`, `-o`: Output directory for CSV and thumbnail files (default: same as video_dir)
- `--cleanup-thumbnails`, `-c`: Delete thumbnails after processing
- `--extensions`, `-e`: Comma-separated list of video extensions (default: `.mp4,.mov`)
- `--force`, `-f`: Reprocess videos even if CSV already exists (default: skip existing)
- `--frames`: Comma-separated frame positions as fractions of the duration, e.g. `0.5,0.9` (default: `0.5`)
- `--dedup-threshold`: Perceptual-hash distance below which frames are treated as duplicates; `0` disables dedup (default: `8`)
- `--provider`: LLM provider, `gemini` or `openrouter` (default: server default)

Examples:

```bash
python analyzer.py                                          # Process videos in current folder (skips existing CSVs)
python analyzer.py ./videos_to_process                      # Process videos in specific folder
python analyzer.py . --cleanup-thumbnails                   # Delete thumbnails after processing
python analyzer.py . --output-dir ./output                  # Save output to different directory
python analyzer.py . --extensions .mp4,.mov,.avi            # Process additional video formats
python analyzer.py . --force                                # Re-analyze all videos (overwrite existing CSVs)
python analyzer.py . --frames 0.5,0.9                       # Analyze the middle and late frames
python analyzer.py . --frames 0.5,0.9 --dedup-threshold 0   # Keep near-identical frames
```

## Output

For each processed video, two files are written to the output directory:

- `<basename>.csv` — one row with the columns `Filename, Title, Description, Keywords`
- `<basename>_001.jpg`, `<basename>_002.jpg`, … — one frame per configured position (removed after processing when `--cleanup-thumbnails` is set). Near-identical frames are deleted before the API call.

The output directory defaults to the input directory; use `--output-dir` to change it.

## Merging Results

Combine the per-video CSVs from a batch into a single file:

```bash
python merge_csvs.py *.csv
```

- The output is named after the first input file with `-merged` appended (e.g. `video1-merged.csv`) and is written next to it. Use `--output-dir`, `-o` to write it elsewhere.
- The header row is taken from the first file; the headers of the remaining files are skipped.
- If you re-run the merge with a shell glob after an earlier merge, the existing `*-merged.csv` is picked up again and its rows are duplicated.

## Expected Webhook Response

The AI service should return JSON:

```json
{
  "title": "Video title",
  "description": "Video description",
  "keywords": "keyword1, keyword2"
}
```
