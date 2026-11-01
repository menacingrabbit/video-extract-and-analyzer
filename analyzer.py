"""
Video Extract and Analyzer

Processes video files by extracting thumbnails and generating AI-based metadata.

Usage:
    python analyzer.py [VIDEO_DIR]

Arguments:
    VIDEO_DIR    Folder containing the videos to process (optional)
                 Default: current directory (.)

Examples:
    python analyzer.py                          # Process videos in the current folder
    python analyzer.py ./videos_to_process      # Process videos in a specific folder

The script:
1. Searches for video files (.mp4, .mov) in the given folder
2. Extracts a thumbnail from the middle of each video using ffmpeg
3. Sends the image to the configured AI webhook for analysis
4. Writes one CSV file per video with AI-generated metadata (title, description, keywords)

Note: The API key is loaded from the .env file (see .env.example).
"""

import os
import sys
import argparse
import ffmpeg
import requests
import csv
import json

# --- CONFIGURATION ---
DEFAULT_WEBHOOK_URL = 'https://stock-photo-metadata-api-145532000117.us-central1.run.app/analyze'
DEFAULT_EXTENSIONS = ('.mp4', '.mov')


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Video Extract and Analyzer - Extracts thumbnails and generates AI metadata'
    )
    parser.add_argument(
        'video_dir',
        nargs='?',
        default='.',
        help='Folder containing the videos to process (default: current directory)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default=None,
        help='Output directory for generated files (default: same as video_dir)'
    )
    parser.add_argument(
        '--cleanup-thumbnails', '-c',
        action='store_true',
        help='Delete thumbnails after processing'
    )
    parser.add_argument(
        '--extensions', '-e',
        default='.mp4,.mov',
        help='Comma-separated list of video extensions (default: .mp4,.mov)'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Re-analyze already processed videos (CSV exists)'
    )
    return parser.parse_args()


def load_env():
    """Load API_KEY and WEBHOOK_URL from the .env file."""
    env_file = '.env'
    api_key = None
    webhook_url = None
    if not os.path.exists(env_file):
        print("Warning: .env file not found. Please copy .env.example and add your key.")
        return api_key, webhook_url
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('API_KEY='):
                api_key = line.split('=', 1)[1]
            elif line.startswith('WEBHOOK_URL='):
                webhook_url = line.split('=', 1)[1]
    if not api_key:
        print("Warning: API_KEY not found in .env file.")
    return api_key, webhook_url


args = parse_args()
API_KEY, WEBHOOK_URL = load_env()
if not WEBHOOK_URL:
    WEBHOOK_URL = DEFAULT_WEBHOOK_URL
HEADERS = {
    'X-API-Key': API_KEY if API_KEY else '',
    'Accept': 'application/json'
}
VIDEO_DIR = args.video_dir
OUTPUT_DIR = args.output_dir if args.output_dir else VIDEO_DIR
VIDEO_EXTENSIONS = tuple(args.extensions.split(','))


def extract_thumbnail(video_path, image_path):
    """Extract a frame from the middle of the video."""
    try:
        probe = ffmpeg.probe(video_path)
        duration = float(probe['format']['duration'])
        # Extract frame at 50% of the runtime
        (
            ffmpeg
            .input(video_path, ss=duration/2)
            .output(image_path, vframes=1)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return True
    except ffmpeg.Error as e:
        print(f"FFmpeg error: {e.stderr.decode()}")
        return False


def get_ai_metadata(image_path, video_filename):
    """Send the image to the webhook and retrieve metadata."""
    with open(image_path, 'rb') as f:
        files = {'image': f}
        data = {
            'filename': video_filename,
            'generateTwoPartKeywords': 'true',
            'useFilename': 'true'
        }
        response = requests.post(WEBHOOK_URL, headers=HEADERS, files=files, data=data)

    if response.status_code == 200:
        try:
            metadata = response.json()
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON from API: {response.text}")
            return None
        # Basic validation - check expected keys exist
        required_keys = ['title', 'description', 'keywords']
        if not all(key in metadata for key in required_keys):
            print(f"Warning: API response is missing expected keys. Received: {list(metadata.keys())}")
        return metadata
    else:
        print(f"AI error: {response.status_code} - {response.text}")
        return None


def main():
    if not os.path.exists(VIDEO_DIR):
        print("Folder not found!")
        return

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    for filename in os.listdir(VIDEO_DIR):
        if filename.lower().endswith(VIDEO_EXTENSIONS):
            base_name = os.path.splitext(filename)[0]
            video_path = os.path.join(VIDEO_DIR, filename)
            image_name = f"{base_name}_001.jpg"
            image_path = os.path.join(OUTPUT_DIR, image_name)
            csv_path = os.path.join(OUTPUT_DIR, f"{base_name}.csv")

            # Skip if CSV already exists and --force not set
            if os.path.exists(csv_path) and not args.force:
                print(f"Skipping (CSV exists): {filename} (use --force to overwrite)")
                continue

            print(f"Processing: {filename}...")

            # 1. Extraction
            if extract_thumbnail(video_path, image_path):
                # 2. AI request
                metadata = get_ai_metadata(image_path, filename)

                if metadata:
                    # 3. CSV creation (one file per video)
                    with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        # Header
                        writer.writerow(['Filename', 'Title', 'Description', 'Keywords'])
                        # Data
                        writer.writerow([
                            filename,
                            metadata.get('title', ''),
                            metadata.get('description', ''),
                            metadata.get('keywords', '')
                        ])
                    print(f"Success: created {csv_path}.")

                # Delete thumbnail if requested
                if args.cleanup_thumbnails and os.path.exists(image_path):
                    os.remove(image_path)
                    print(f"Thumbnail deleted: {image_path}")

if __name__ == "__main__":
    main()
