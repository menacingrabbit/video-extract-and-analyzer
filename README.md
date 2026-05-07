# Video Extract and Analyzer

Python tool that processes video files by extracting thumbnails and generating metadata via AI analysis.

## How it works

1. Scans a folder for video files (`.mp4`, `.mov`)
2. Extracts a thumbnail from the middle of each video using ffmpeg
3. Sends the thumbnail to a configured AI webhook for analysis
4. Writes a CSV file per video with AI-generated metadata (title, description, keywords)

## Setup

Install dependencies:

```bash
pip install ffmpeg-python requests
```

Ensure ffmpeg is installed on your system (e.g., `brew install ffmpeg` on macOS).

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

3. (Optional) Edit the `WEBHOOK_URL` in `analyzer.py` (line 35) to change the AI service endpoint.

Note: The `.env` file is excluded from git via `.gitignore` to keep your key secure.

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
