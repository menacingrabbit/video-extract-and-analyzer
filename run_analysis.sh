#!/usr/bin/env bash
#
# Run the full video analysis pipeline:
#   environment setup -> frame extraction -> multi-image API -> CSV output
#
# Usage:
#   ./run_analysis.sh [VIDEO_DIR] [OPTIONS] [--merge] [--setup]
#
# All analyzer options are passed through. See ./run_analysis.sh --help-analyzer.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ORIGINAL_PWD="$PWD"
VENV_DIR="$SCRIPT_DIR/venv"
PYTHON="$VENV_DIR/bin/python"
DEFAULT_FRAMES="0.5,0.9"

SETUP_ONLY=0
MERGE=0
DRY_RUN=0
VIDEO_DIR_ARG=""
OUTPUT_DIR_ARG=""
FRAMES_GIVEN=0
PASSTHROUGH=()

usage() {
  cat <<'EOF'
Usage: ./run_analysis.sh [VIDEO_DIR] [OPTIONS] [--merge] [--setup] [--dry-run]

Runs the full pipeline: prepares the virtual environment, extracts frames,
sends them to POST /analyze-multiple, and writes one CSV per video.

Wrapper options:
  --setup          Create/repair the venv and install dependencies, then exit
  --merge          Merge the generated CSVs into one file after processing
  --dry-run        Print the analyzer command without running it
  -h, --help       Show this help
  --help-analyzer  Show analyzer.py options

All other options are passed to analyzer.py.
Defaults: --frames 0.5,0.9
EOF
}

abs_path() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *) printf '%s/%s' "$ORIGINAL_PWD" "$1" ;;
  esac
}

require_value() {
  if [[ $# -lt 2 ]]; then
    echo "Error: $1 requires a value." >&2
    exit 2
  fi
}

ensure_environment() {
  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Error: ffmpeg is not installed or not in PATH." >&2
    echo "Install it first (e.g. 'brew install ffmpeg')." >&2
    exit 1
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is not installed or not in PATH." >&2
    exit 1
  fi

  if [[ ! -x "$PYTHON" ]]; then
    echo "Creating virtual environment in $VENV_DIR ..."
    python3 -m venv --clear "$VENV_DIR"
  fi

  if ! "$PYTHON" -c 'import ffmpeg, requests' >/dev/null 2>&1; then
    echo "Installing dependencies ..."
    "$PYTHON" -m pip install --quiet --upgrade pip
    "$PYTHON" -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
  fi
}

check_env_file() {
  if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
    if [[ -f "$SCRIPT_DIR/.env.example" ]]; then
      cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
      echo "Created $SCRIPT_DIR/.env from .env.example." >&2
      echo "Add your API_KEY to .env and re-run." >&2
    else
      echo "Error: .env is missing and no .env.example was found." >&2
    fi
    exit 1
  fi

  if ! grep -qE '^API_KEY=[^[:space:]]+' "$SCRIPT_DIR/.env"; then
    echo "Error: API_KEY is not set in $SCRIPT_DIR/.env." >&2
    exit 1
  fi

  if grep -qE '^API_KEY=(your_api_key_here|your_actual_key_here)[[:space:]]*$' "$SCRIPT_DIR/.env"; then
    echo "Error: API_KEY in .env is still the placeholder value." >&2
    exit 1
  fi
}

# --- parse wrapper options; pass everything else to analyzer.py -------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --setup) SETUP_ONLY=1; shift ;;
    --merge) MERGE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --help-analyzer)
      ensure_environment
      "$PYTHON" "$SCRIPT_DIR/analyzer.py" --help
      exit 0
      ;;
    -o|--output-dir)
      require_value "$@"
      OUTPUT_DIR_ARG="$(abs_path "$2")"
      PASSTHROUGH+=("$1" "$OUTPUT_DIR_ARG")
      shift 2
      ;;
    --output-dir=*)
      OUTPUT_DIR_ARG="$(abs_path "${1#*=}")"
      PASSTHROUGH+=("--output-dir=$OUTPUT_DIR_ARG")
      shift
      ;;
    --frames)
      require_value "$@"
      FRAMES_GIVEN=1
      PASSTHROUGH+=("$1" "$2")
      shift 2
      ;;
    --frames=*)
      FRAMES_GIVEN=1
      PASSTHROUGH+=("$1")
      shift
      ;;
    -e|--extensions|--dedup-threshold|--provider)
      require_value "$@"
      PASSTHROUGH+=("$1" "$2")
      shift 2
      ;;
    --extensions=*|--dedup-threshold=*|--provider=*)
      PASSTHROUGH+=("$1")
      shift
      ;;
    -c|--cleanup-thumbnails|-f|--force)
      PASSTHROUGH+=("$1")
      shift
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        if [[ -n "$VIDEO_DIR_ARG" ]]; then
          echo "Error: only one VIDEO_DIR is allowed." >&2
          exit 2
        fi
        VIDEO_DIR_ARG="$(abs_path "$1")"
        shift
      done
      ;;
    -*)
      echo "Error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -n "$VIDEO_DIR_ARG" ]]; then
        echo "Error: only one VIDEO_DIR is allowed." >&2
        exit 2
      fi
      VIDEO_DIR_ARG="$(abs_path "$1")"
      shift
      ;;
  esac
done

# Default to the caller's directory, not the repository directory.
if [[ -z "$VIDEO_DIR_ARG" ]]; then
  VIDEO_DIR_ARG="$ORIGINAL_PWD"
fi
if [[ -z "$OUTPUT_DIR_ARG" ]]; then
  OUTPUT_DIR_ARG="$VIDEO_DIR_ARG"
fi
if [[ "$FRAMES_GIVEN" -eq 0 ]]; then
  PASSTHROUGH+=("--frames" "$DEFAULT_FRAMES")
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'Would run:'
  printf ' %q' "$PYTHON" "$SCRIPT_DIR/analyzer.py" "$VIDEO_DIR_ARG" "${PASSTHROUGH[@]}"
  printf '\n'
  exit 0
fi

ensure_environment

if [[ "$SETUP_ONLY" -eq 1 ]]; then
  echo "Environment is ready."
  exit 0
fi

check_env_file

echo "Video directory:  $VIDEO_DIR_ARG"
echo "Output directory: $OUTPUT_DIR_ARG"
echo "Frames:           $( [[ "$FRAMES_GIVEN" -eq 1 ]] && echo "custom" || echo "$DEFAULT_FRAMES" )"
echo

# analyzer.py resolves .env relative to the working directory.
cd "$SCRIPT_DIR"
"$PYTHON" "$SCRIPT_DIR/analyzer.py" "$VIDEO_DIR_ARG" "${PASSTHROUGH[@]}"

if [[ "$MERGE" -eq 1 ]]; then
  shopt -s nullglob
  csv_files=("$OUTPUT_DIR_ARG"/*.csv)
  merge_inputs=()
  for csv_file in "${csv_files[@]}"; do
    case "$csv_file" in
      *-merged.csv) ;;
      *) merge_inputs+=("$csv_file") ;;
    esac
  done

  if [[ ${#merge_inputs[@]} -eq 0 ]]; then
    echo "No CSV files found in $OUTPUT_DIR_ARG; nothing to merge."
  else
    echo
    echo "Merging ${#merge_inputs[@]} CSV file(s) ..."
    "$PYTHON" "$SCRIPT_DIR/merge_csvs.py" "${merge_inputs[@]}"
  fi
fi
