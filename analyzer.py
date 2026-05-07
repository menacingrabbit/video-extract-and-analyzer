"""
Video Extract and Analyzer

Verarbeitet Video-Dateien durch Extraktion von Thumbnails und KI-basierte Metadaten-Generierung.

Verwendung:
    python analyzer.py [VIDEO_DIR]

Argumente:
    VIDEO_DIR    Ordner mit den zu verarbeitenden Videos (optional)
                 Default: aktuelles Verzeichnis (.)

Beispiele:
    python analyzer.py                          # Verarbeitet Videos im aktuellen Ordner
    python analyzer.py ./videos_to_process      # Verarbeitet Videos in einem spezifischen Ordner

Das Skript:
1. Sucht nach Video-Dateien (.mp4, .mov) im angegebenen Ordner
2. Extrahiert ein Thumbnail aus der Mitte jedes Videos mit ffmpeg
3. Sendet das Bild an den konfigurierten KI-Webhook zur Analyse
4. Schreibt eine CSV-Datei pro Video mit KI-generierten Metadaten (Titel, Beschreibung, Keywords)

Hinweis: Der API Key wird aus der .env Datei geladen (siehe .env.example).
"""

import os
import sys
import argparse
import ffmpeg
import requests
import csv
import json

# --- KONFIGURATION ---
DEFAULT_WEBHOOK_URL = 'https://stock-photo-metadata-api-145532000117.us-central1.run.app/analyze'
DEFAULT_EXTENSIONS = ('.mp4', '.mov')


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Video Extract and Analyzer - Extrahiert Thumbnails und generiert KI-Metadaten'
    )
    parser.add_argument(
        'video_dir',
        nargs='?',
        default='.',
        help='Ordner mit den zu verarbeitenden Videos (default: aktuelles Verzeichnis)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default=None,
        help='Ordner für Ausgabedateien (default: gleich wie video_dir)'
    )
    parser.add_argument(
        '--cleanup-thumbnails', '-c',
        action='store_true',
        help='Löscht Thumbnails nach der Verarbeitung'
    )
    parser.add_argument(
        '--extensions', '-e',
        default='.mp4,.mov',
        help='Kommagetrennte Liste der Video-Extensions (default: .mp4,.mov)'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Bereits verarbeitete Videos (CSV existiert) erneut analysieren'
    )
    return parser.parse_args()


def load_env():
    """Lädt API_KEY und WEBHOOK_URL aus der .env Datei."""
    env_file = '.env'
    api_key = None
    webhook_url = None
    if not os.path.exists(env_file):
        print("Warnung: .env Datei nicht gefunden. Bitte .env.example kopieren und Key eintragen.")
        return api_key, webhook_url
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('API_KEY='):
                api_key = line.split('=', 1)[1]
            elif line.startswith('WEBHOOK_URL='):
                webhook_url = line.split('=', 1)[1]
    if not api_key:
        print("Warnung: API_KEY nicht in .env Datei gefunden.")
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
    """Extrahiert ein Bild aus der Mitte des Videos."""
    try:
        probe = ffmpeg.probe(video_path)
        duration = float(probe['format']['duration'])
        # Extrahiere Frame bei 50% der Laufzeit
        (
            ffmpeg
            .input(video_path, ss=duration/2)
            .output(image_path, vframes=1)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return True
    except ffmpeg.Error as e:
        print(f"Fehler bei FFmpeg: {e.stderr.decode()}")
        return False


def get_ai_metadata(image_path, video_filename):
    """Sendet das Bild an den Webhook und holt Metadaten."""
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
            print(f"Fehler: Ungültiges JSON von API: {response.text}")
            return None
        # Basic validation - check expected keys exist
        required_keys = ['title', 'description', 'keywords']
        if not all(key in metadata for key in required_keys):
            print(f"Warnung: API-Antwort hat nicht alle erwarteten Keys. Erhalten: {list(metadata.keys())}")
        return metadata
    else:
        print(f"KI-Fehler: {response.status_code} - {response.text}")
        return None


def main():
    if not os.path.exists(VIDEO_DIR):
        print("Ordner nicht gefunden!")
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
                print(f"Überspringe (CSV existiert): {filename} (--force zum Überschreiben)")
                continue

            print(f"Verarbeite: {filename}...")

            # 1. Extraktion
            if extract_thumbnail(video_path, image_path):
                # 2. KI-Abfrage
                metadata = get_ai_metadata(image_path, filename)

                if metadata:
                    # 3. CSV Erstellung (Pro Video eine Datei)
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
                    print(f"Erfolg: {csv_path} erstellt.")

                # Thumbnail löschen falls gewünscht
                if args.cleanup_thumbnails and os.path.exists(image_path):
                    os.remove(image_path)
                    print(f"Thumbnail gelöscht: {image_path}")

if __name__ == "__main__":
    main()
