# Video Extract and Analyzer

Python tool that processes video files by extracting thumbnails and generating metadata via AI analysis.

## How it works

1. Scans the top level of a folder for video files (`.mp4`, `.mov` by default)
2. Extracts a thumbnail from the middle of each video using ffmpeg
3. Sends the thumbnail to a configured AI webhook for analysis
4. Writes a CSV file per video with AI-generated metadata (title, description, keywords)

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
- `image`: The extracted thumbnail file
- `filename`: Original video filename
- `generateTwoPartKeywords`: Set to `"true"`
- `useFilename`: Set to `"true"`

Authentication is done via the `X-API-Key` header.

3. (Optional) Change the AI service endpoint by setting `WEBHOOK_URL` in `.env`:

```
WEBHOOK_URL=https://your-endpoint.example.com/analyze
```

If `WEBHOOK_URL` is not set, the default hardcoded in `analyzer.py` is used.

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

Examples:

```bash
python analyzer.py                                          # Process videos in current folder (skips existing CSVs)
python analyzer.py ./videos_to_process                      # Process videos in specific folder
python analyzer.py . --cleanup-thumbnails                   # Delete thumbnails after processing
python analyzer.py . --output-dir ./output                  # Save output to different directory
python analyzer.py . --extensions .mp4,.mov,.avi            # Process additional video formats
python analyzer.py . --force                                # Re-analyze all videos (overwrite existing CSVs)
```

## Output

For each processed video, two files are written to the output directory:

- `<basename>.csv` — one row with the columns `Filename, Title, Description, Keywords`
- `<basename>_001.jpg` — the extracted thumbnail (removed after processing when `--cleanup-thumbnails` is set)

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
