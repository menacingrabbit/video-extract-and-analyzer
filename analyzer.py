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
import ffmpeg
import requests
import csv
import json

# --- KONFIGURATION ---
VIDEO_DIR = sys.argv[1] if len(sys.argv) > 1 else '.'
WEBHOOK_URL = 'https://stock-photo-metadata-api-145532000117.us-central1.run.app/analyze'

def load_api_key():
    """Lädt den API Key aus der .env Datei."""
    env_file = '.env'
    if not os.path.exists(env_file):
        print("Warnung: .env Datei nicht gefunden. Bitte .env.example kopieren und Key eintragen.")
        return None
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('API_KEY='):
                return line.split('=', 1)[1]
    return None


API_KEY = load_api_key()
HEADERS = {
    'X-API-Key': API_KEY if API_KEY else '',
    'Accept': 'application/json'
}

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
        return response.json() # Erwartet {"title": "...", "description": "...", "keywords": "..."}
    else:
        print(f"KI-Fehler: {response.status_code} - {response.text}")
        return None

def main():
    if not os.path.exists(VIDEO_DIR):
        print("Ordner nicht gefunden!")
        return

    for filename in os.listdir(VIDEO_DIR):
        if filename.lower().endswith(('.mp4', '.mov')):
            base_name = os.path.splitext(filename)[0]
            video_path = os.path.join(VIDEO_DIR, filename)
            image_name = f"{base_name}_001.jpg"
            image_path = os.path.join(VIDEO_DIR, image_name)
            csv_path = os.path.join(VIDEO_DIR, f"{base_name}.csv")

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
                
                # Optional: Lösche das JPG nach der Verarbeitung, um Platz zu sparen
                # os.remove(image_path)

if __name__ == "__main__":
    main()