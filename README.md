# Video Extract and Analyzer

Python tool that processes video files by extracting thumbnails and generating metadata via AI analysis.

## How it works

1. Scans a folder (`videos_to_process/`) for video files (`.mp4`, `.mov`)
2. Extracts a thumbnail from the middle of each video using ffmpeg
3. Sends the thumbnail to a configured AI webhook for analysis
4. Writes a CSV file per video with AI-generated metadata (title, description, keywords)

## Setup

Install dependencies:

```bash
pip install ffmpeg-python requests
```

Ensure ffmpeg is installed on your system.

## Configuration

1. Copy the example env file and add your token:

```bash
cp .env.example .env
```

2. Edit `.env` and add your Bearer token:

```
BEARER_TOKEN=your_actual_token_here
```

3. (Optional) Edit the constants in `analyzer.py` if you need to change the webhook URL:

```python
WEBHOOK_URL = 'https://your-api.com/api/analyze'  # AI service endpoint
```

Note: The `.env` file is excluded from git via `.gitignore` to keep your token secure.

## Usage

Run the analyzer with an optional video directory argument:

```bash
python analyzer.py [VIDEO_DIR]
```

- `VIDEO_DIR`: Folder containing videos to process (optional)
- Default: current directory (`.`)

Examples:

```bash
python analyzer.py                          # Process videos in current folder
python analyzer.py ./videos_to_process      # Process videos in specific folder
```

After running, find the generated CSV files (one per video) in the specified folder.

## Expected Webhook Response

The AI service should return JSON:

```json
{
  "title": "Video title",
  "description": "Video description",
  "keywords": "keyword1, keyword2"
}
```
