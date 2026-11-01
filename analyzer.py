"""
Video Extract and Analyzer

Processes video files by extracting thumbnails and generating AI-based metadata.

Usage:
    python analyzer.py [VIDEO_DIR] [OPTIONS]

Arguments:
    VIDEO_DIR    Folder containing the videos to process (optional)
                 Default: current directory (.)

The script:
1. Searches the top level of the given folder for video files
2. Extracts one frame per configured fraction of the video duration
3. Drops near-identical frames using a perceptual hash
4. Sends the remaining frames in one request to POST /analyze-multiple
5. Writes one CSV file per video with AI-generated metadata

Note: The API key is loaded from the .env file (see .env.example).
"""

import argparse
import csv
import os
import subprocess
import time
from contextlib import ExitStack
from dataclasses import dataclass
from typing import List, Optional, Tuple

import ffmpeg
import requests

# --- CONFIGURATION ---
DEFAULT_WEBHOOK_URL = 'https://stock-photo-metadata-api-145532000117.us-central1.run.app/analyze'
DEFAULT_EXTENSIONS = '.mp4,.mov'
DEFAULT_FRAMES = '0.5'
DEFAULT_DEDUP_THRESHOLD = 8

MAX_FRAMES = 5
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1, 2, 4)
REQUEST_TIMEOUT = (10, 120)
DEDUP_HASH_WIDTH = 9
DEDUP_HASH_HEIGHT = 8


@dataclass
class Config:
    """Resolved runtime configuration."""
    api_key: str
    webhook_url: str
    analyze_multiple_url: str
    output_dir: str
    fractions: List[float]
    dedup_threshold: int
    cleanup_thumbnails: bool
    force: bool
    extensions: Tuple[str, ...]
    provider: Optional[str] = None


def parse_fractions(value):
    """Parse and validate a comma-separated list of frame fractions."""
    parts = [part.strip() for part in value.split(',') if part.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("--frames needs at least one fraction")

    fractions = []
    for part in parts:
        try:
            fraction = float(part)
        except ValueError:
            raise argparse.ArgumentTypeError(f"invalid frame fraction: {part!r}")
        if not 0 < fraction < 1:
            raise argparse.ArgumentTypeError(
                f"frame fraction must be between 0 and 1 (exclusive): {part!r}"
            )
        fractions.append(fraction)

    unique = sorted(set(fractions))
    if len(unique) > MAX_FRAMES:
        raise argparse.ArgumentTypeError(f"at most {MAX_FRAMES} frames are supported")
    return unique


def parse_extensions(value):
    """Parse and normalize a comma-separated list of file extensions."""
    extensions = []
    for part in value.split(','):
        part = part.strip().lower()
        if not part:
            continue
        if not part.startswith('.'):
            part = '.' + part
        extensions.append(part)
    if not extensions:
        raise argparse.ArgumentTypeError("--extensions needs at least one extension")
    return tuple(extensions)


def non_negative_int(value):
    """Argparse type for a non-negative integer."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}")
    if number < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return number


def parse_args(argv=None):
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
        type=parse_extensions,
        default=DEFAULT_EXTENSIONS,
        help='Comma-separated list of video extensions (default: .mp4,.mov)'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Re-analyze already processed videos (CSV exists)'
    )
    parser.add_argument(
        '--frames',
        type=parse_fractions,
        default=DEFAULT_FRAMES,
        help='Comma-separated frame positions as fractions of the duration, '
             'e.g. 0.5 or 0.5,0.9 (default: 0.5)'
    )
    parser.add_argument(
        '--dedup-threshold',
        type=non_negative_int,
        default=DEFAULT_DEDUP_THRESHOLD,
        help='Perceptual-hash distance under which frames are considered duplicates; '
             '0 disables deduplication (default: 8)'
    )
    parser.add_argument(
        '--provider',
        choices=('gemini', 'openrouter'),
        default=None,
        help='LLM provider for the API (default: server default)'
    )
    return parser.parse_args(argv)


def load_env(env_file='.env'):
    """Load API_KEY and WEBHOOK_URL from the .env file."""
    api_key = None
    webhook_url = None
    if not os.path.exists(env_file):
        print("Warning: .env file not found. Please copy .env.example and add your key.")
        return api_key, webhook_url
    with open(env_file, 'r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line.startswith('API_KEY='):
                api_key = line.split('=', 1)[1]
            elif line.startswith('WEBHOOK_URL='):
                webhook_url = line.split('=', 1)[1]
    if not api_key:
        print("Warning: API_KEY not found in .env file.")
    return api_key, webhook_url


def derive_analyze_multiple_url(webhook_url):
    """Derive the /analyze-multiple URL from the configured webhook URL."""
    base = webhook_url.rstrip('/')
    if base.endswith('/analyze'):
        base = base[: -len('/analyze')]
    return f"{base}/analyze-multiple"


def build_config(args):
    """Combine CLI arguments and environment into a Config."""
    api_key, webhook_url = load_env()
    webhook_url = webhook_url or DEFAULT_WEBHOOK_URL
    return Config(
        api_key=api_key or '',
        webhook_url=webhook_url,
        analyze_multiple_url=derive_analyze_multiple_url(webhook_url),
        output_dir=args.output_dir or args.video_dir,
        fractions=args.frames,
        dedup_threshold=args.dedup_threshold,
        cleanup_thumbnails=args.cleanup_thumbnails,
        force=args.force,
        extensions=args.extensions,
        provider=args.provider,
    )


def build_headers(config):
    """Build the HTTP headers for API requests."""
    return {
        'X-API-Key': config.api_key,
        'Accept': 'application/json',
    }


def extract_frame(video_path, image_path, duration, fraction):
    """Extract a single frame at a fraction of the video duration."""
    try:
        (
            ffmpeg
            .input(video_path, ss=duration * fraction)
            .output(image_path, vframes=1)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return True
    except ffmpeg.Error as error:
        stderr = error.stderr.decode(errors='replace') if error.stderr else str(error)
        print(
            f"FFmpeg error for {os.path.basename(video_path)} "
            f"at {fraction:.0%}: {stderr}"
        )
        return False


def extract_frames(video_path, output_dir, base_name, fractions):
    """Extract one frame per fraction and return the paths that succeeded."""
    try:
        probe = ffmpeg.probe(video_path)
        duration = float(probe['format']['duration'])
    except (ffmpeg.Error, KeyError, TypeError, ValueError) as error:
        print(f"Could not read duration of {os.path.basename(video_path)}: {error}")
        return []

    frame_paths = []
    for index, fraction in enumerate(fractions, start=1):
        image_path = os.path.join(output_dir, f"{base_name}_{index:03d}.jpg")
        if extract_frame(video_path, image_path, duration, fraction):
            frame_paths.append(image_path)
    return frame_paths


def dhash_from_pixels(pixels):
    """Compute a 64-bit difference hash from 9x8 grayscale pixels."""
    expected = DEDUP_HASH_WIDTH * DEDUP_HASH_HEIGHT
    if len(pixels) < expected:
        raise ValueError(f"expected {expected} grayscale pixels, got {len(pixels)}")

    bits = 0
    for row in range(DEDUP_HASH_HEIGHT):
        offset = row * DEDUP_HASH_WIDTH
        for column in range(DEDUP_HASH_WIDTH - 1):
            bits = (bits << 1) | (1 if pixels[offset + column] > pixels[offset + column + 1] else 0)
    return bits


def compute_dhash(image_path):
    """Compute the perceptual hash of an image using ffmpeg."""
    result = subprocess.run(
        [
            'ffmpeg', '-v', 'error', '-i', image_path,
            '-vf', f'scale={DEDUP_HASH_WIDTH}:{DEDUP_HASH_HEIGHT},format=gray',
            '-f', 'rawvideo', '-',
        ],
        capture_output=True,
        check=True,
    )
    return dhash_from_pixels(result.stdout)


def hamming_distance(left, right):
    """Count the differing bits between two hashes."""
    return bin(left ^ right).count('1')


def dedupe_frames(frame_paths, threshold):
    """Drop frames that are perceptually near-identical to an earlier frame."""
    if threshold <= 0 or len(frame_paths) < 2:
        return list(frame_paths)

    kept = []
    kept_hashes = []
    for path in frame_paths:
        try:
            digest = compute_dhash(path)
        except (OSError, subprocess.CalledProcessError, ValueError) as error:
            print(f"Warning: could not hash {os.path.basename(path)}: {error}")
            kept.append(path)
            continue

        if any(hamming_distance(digest, other) <= threshold for other in kept_hashes):
            print(f"Dropping near-identical frame: {os.path.basename(path)}")
            try:
                os.remove(path)
            except OSError:
                pass
            continue

        kept.append(path)
        kept_hashes.append(digest)
    return kept


def request_with_retries(request_fn, label):
    """Run a request function, retrying 429 and 5xx responses with backoff."""
    response = None
    for attempt in range(MAX_RETRIES):
        response = request_fn()
        retryable = response.status_code == 429 or 500 <= response.status_code < 600
        if not retryable:
            return response
        if attempt == MAX_RETRIES - 1:
            break

        delay = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
        retry_after = response.headers.get('Retry-After')
        if retry_after and retry_after.isdigit():
            delay = int(retry_after)
        print(
            f"{label}: HTTP {response.status_code}, retrying in {delay}s "
            f"(attempt {attempt + 1}/{MAX_RETRIES})"
        )
        time.sleep(delay)
    return response


def post_multiple(frame_paths, filename, config):
    """Send all frames to /analyze-multiple in one multipart request."""
    with ExitStack() as stack:
        files = [
            (
                'images',
                (
                    os.path.basename(path),
                    stack.enter_context(open(path, 'rb')),
                    'image/jpeg',
                ),
            )
            for path in frame_paths
        ]
        data = {
            'filename': filename,
            'generateTwoPartKeywords': 'true',
            'useFilename': 'true',
        }
        if config.provider:
            data['provider'] = config.provider
        return requests.post(
            config.analyze_multiple_url,
            headers=build_headers(config),
            files=files,
            data=data,
            timeout=REQUEST_TIMEOUT,
        )


def post_legacy(frame_path, filename, config):
    """Send a single frame to the legacy /analyze endpoint."""
    with open(frame_path, 'rb') as handle:
        files = {
            'image': (os.path.basename(frame_path), handle, 'image/jpeg'),
        }
        data = {
            'filename': filename,
            'generateTwoPartKeywords': 'true',
            'useFilename': 'true',
        }
        return requests.post(
            config.webhook_url,
            headers=build_headers(config),
            files=files,
            data=data,
            timeout=REQUEST_TIMEOUT,
        )


def parse_metadata(response):
    """Validate and return the metadata JSON object."""
    try:
        metadata = response.json()
    except ValueError:
        print(f"Error: invalid JSON from API: {response.text[:500]}")
        return None

    if not isinstance(metadata, dict):
        print(f"Error: expected a JSON object from API, got {type(metadata).__name__}")
        return None

    required_keys = ('title', 'description', 'keywords')
    if not all(key in metadata for key in required_keys):
        print(
            "Warning: API response is missing expected keys. "
            f"Received: {list(metadata.keys())}"
        )
    return metadata


def analyze_frames(frame_paths, filename, config):
    """Analyze frames, falling back to the legacy endpoint on 404/405."""
    response = request_with_retries(
        lambda: post_multiple(frame_paths, filename, config),
        'analyze-multiple',
    )

    if response.status_code in (404, 405):
        print(
            f"analyze-multiple not available (HTTP {response.status_code}); "
            "falling back to legacy /analyze"
        )
        response = request_with_retries(
            lambda: post_legacy(frame_paths[0], filename, config),
            'analyze',
        )

    if response.status_code != 200:
        print(f"AI error: {response.status_code} - {response.text[:500]}")
        return None

    return parse_metadata(response)


def write_csv(csv_path, filename, metadata):
    """Write one metadata row to a per-video CSV file."""
    with open(csv_path, mode='w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['Filename', 'Title', 'Description', 'Keywords'])
        writer.writerow([
            filename,
            metadata.get('title', ''),
            metadata.get('description', ''),
            metadata.get('keywords', ''),
        ])


def process_videos(video_dir, config):
    """Process every matching video in a directory."""
    if not os.path.isdir(video_dir):
        print("Folder not found!")
        return

    os.makedirs(config.output_dir, exist_ok=True)

    for filename in sorted(os.listdir(video_dir)):
        if not filename.lower().endswith(config.extensions):
            continue

        base_name = os.path.splitext(filename)[0]
        video_path = os.path.join(video_dir, filename)
        csv_path = os.path.join(config.output_dir, f"{base_name}.csv")

        # Skip if CSV already exists and --force not set
        if os.path.exists(csv_path) and not config.force:
            print(f"Skipping (CSV exists): {filename} (use --force to overwrite)")
            continue

        print(f"Processing: {filename}...")

        frames = extract_frames(
            video_path, config.output_dir, base_name, config.fractions
        )
        if not frames:
            print(f"Skipping (no frames extracted): {filename}")
            continue

        kept_frames = dedupe_frames(frames, config.dedup_threshold)
        metadata = analyze_frames(kept_frames, filename, config)

        if metadata:
            write_csv(csv_path, filename, metadata)
            print(f"Success: created {csv_path}.")

        # Delete thumbnails if requested
        if config.cleanup_thumbnails:
            for frame_path in frames:
                if os.path.exists(frame_path):
                    os.remove(frame_path)
                    print(f"Thumbnail deleted: {frame_path}")


def main(argv=None):
    args = parse_args(argv)
    config = build_config(args)
    process_videos(args.video_dir, config)


if __name__ == "__main__":
    main()
