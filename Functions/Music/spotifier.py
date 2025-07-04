import os, time, glob, shutil, spotipy, requests, threading, subprocess, zipfile, signal, asyncio
from Gears.Ids import CMusic
from flask import Flask, send_file, make_response, request, send_from_directory
from spotipy.oauth2 import SpotifyOAuth
from concurrent.futures import ThreadPoolExecutor, as_completed
from yt_dlp import YoutubeDL
from urllib.parse import quote
from bot_Function import Client_secret, Refresh_token

BASE_DIR = os.path.abspath(os.path.dirname(__file__)) if '__file__' in globals() else os.getcwd()
path_downloads = os.path.join(BASE_DIR, 'Downloads_playlists/')

# Spotify credentials
CLIENT_ID = '382cbaacee964b1f9bafdf14ab86f549'
CLIENT_SECRET = Client_secret
REDIRECT_URI = 'https://www.google.com/?hl=es'
SCOPE = 'playlist-read-private playlist-read-collaborative'
REFRESH_TOKEN = Refresh_token

auth_manager = SpotifyOAuth(client_id=CLIENT_ID, client_secret=CLIENT_SECRET, redirect_uri=REDIRECT_URI, scope=SCOPE)
token_info = auth_manager.refresh_access_token(REFRESH_TOKEN)
access_token = token_info['access_token']
sp = spotipy.Spotify(auth=access_token)


app = Flask(__name__)
DOWNLOAD_FOLDER = path_downloads


@app.route('/Functions/Music/Downloads_playlists/<path:filename>')
def download_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)


def start_flask():
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()


def normalize_str(string):
    return string.translate(str.maketrans('\\/:*?"<>|', "__       "))


def download_from_youtube(track, playlist_name):
    track_name = normalize_str(track["name"]).strip()
    artist_name = normalize_str(", ".join([a["name"] for a in track["artists"]]))
    download_path = f"{path_downloads}{playlist_name}"

    os.makedirs(download_path, exist_ok=True)
    if any(glob.glob(os.path.join(download_path, f"*{track_name}*.mp3"))):
        return

    ydl_opts = {
        'quiet': True,
        'noplaylist': True,
        'no-warnings': True,
        'extract_flat': True,
        'force_generic_extractor': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        try:
            search_results = ydl.extract_info(f"ytsearch3:{track_name} {artist_name}", download=False).get('entries', [])
            if not search_results:
                print(f"No se encontró: {track_name} - {artist_name}")
                return
            track_duration = track['duration_ms'] // 1000
            best_match = min(search_results, key=lambda x: abs(x.get('duration', 0) - track_duration))
            best_url = best_match['url']
        except Exception as e:
            print(f"Error en búsqueda: {str(e)}")
            return

    print(f"Descargando: {track_name} - {artist_name}\nURL: {best_url}")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{download_path}/{artist_name} - {track_name}.%(ext)s",
        "ignoreerrors": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }],
        'quiet': True,
        'no_warnings': True
    }

    for attempt in range(2):
        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([best_url])
                normalize_audio(f"{download_path}/{artist_name} - {track_name}.mp3")
                break
        except Exception as e:
            print(e)
            time.sleep(.5)


def normalize_audio(input_file):
    output_file = input_file.replace(".mp3", "_normalized.mp3")
    ffmpeg_cmd = [
        "ffmpeg", "-loglevel", "quiet", "-i", input_file,
        "-af", "loudnorm=I=-16:LRA=11:TP=-1.5", "-ar", "44100", "-b:a", "320k", output_file
    ]
    subprocess.run(ffmpeg_cmd, check=True)
    os.remove(input_file)
    os.rename(output_file, input_file)
    print("Audio normalizado correctamente.")


async def get_playlist(playlist_url):
    loop = asyncio.get_running_loop()

    # Obtener playlist de Spotify
    playlist_id = playlist_url.split("/")[-1].split("?")[0]
    playlist = sp.playlist(playlist_id)
    playlist_name = normalize_str(playlist['name']).strip()

    results = sp.playlist_items(playlist_id, limit=100, offset=0)
    all_tracks = results['items']
    while results['next']:
        results = sp.next(results)
        all_tracks.extend(results['items'])
    
    # Asegurar carpeta
    os.makedirs(f"{path_downloads}/{playlist_name}", exist_ok=True)

    # Función bloqueante
    def blocking_download_and_zip():
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(download_from_youtube, item['track'], playlist_name)
                for item in all_tracks
            ]
            # Esperar a que terminen todos
            for future in as_completed(futures):
                future.result()

        # Crear zip
        zip_path = f'{path_downloads}/{playlist_name}.zip'
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for root, dirs, files in os.walk(f'{path_downloads}/{playlist_name}'):
                for file in files:
                    zipf.write(os.path.join(root, file), file)

        # Limpiar carpeta
        shutil.rmtree(f"{path_downloads}/{playlist_name}")

        return zip_path

    # Ejecutar en thread pool
    zip_path = await loop.run_in_executor(None, blocking_download_and_zip)
    return zip_path


async def upload_file(zip_file, ctx):
    DOMAIN = os.environ.get("DOMAIN_URL", "http://localhost:8080")
    file_name = os.path.basename(zip_file)
    public_url = f"{DOMAIN}/Functions/Music/Downloads_playlists/{file_name}"
    print(public_url)

    #await ctx.response.send_message(f"✅ Playlist descargada. Puedes bajarla aquí:\n{public_url}")
    return


async def set_up(ctx, url, bot):
    await ctx.response.send_message('Descargando...')
    zip_file = await get_playlist(url)
    await upload_file(zip_file, ctx)


start_flask()
