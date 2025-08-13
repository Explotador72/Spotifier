import os
import asyncio
import logging
import subprocess
import zipfile
import shutil
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import threading
import time
import re
import requests
import json
import ssl
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from yt_dlp import YoutubeDL
from dotenv import load_dotenv
import discord

# Configuración
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Usar directorio temporal del sistema
TEMP_DIR = Path(tempfile.gettempdir()) / 'spotify_downloads'
TEMP_DIR.mkdir(exist_ok=True)

# Spotify config
SPOTIFY_CONFIG = {
    'client_id': '382cbaacee964b1f9bafdf14ab86f549',
    'client_secret': os.getenv('CLIENT_SECRET'),
    'redirect_uri': 'https://www.google.com/?hl=es',
    'scope': 'playlist-read-private playlist-read-collaborative',
    'refresh_token': os.getenv('REFRESH_TOKEN')
}

class FileHostUploader:
    """Clase para subir archivos a servicios de hosting gratuitos"""
    
    @staticmethod
    def get_robust_session():
        """Crear sesión robusta con reintentos y configuración SSL"""
        session = requests.Session()
        
        # Configurar reintentos
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Headers comunes
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        return session
    
    @staticmethod
    def upload_to_0x0_st(file_path: Path) -> Optional[str]:
        """Subir a 0x0.st (sin límites, confiable)"""
        try:
            session = FileHostUploader.get_robust_session()
            with open(file_path, 'rb') as f:
                files = {'file': f}
                response = session.post('https://0x0.st', files=files, timeout=120)
            
            if response.status_code == 200:
                url = response.text.strip()
                logger.info(f"Subido a 0x0.st: {url}")
                return url
            return None
        except Exception as e:
            logger.error(f"Error subiendo a 0x0.st: {e}")
            return None
    
    @staticmethod
    def upload_to_catbox(file_path: Path) -> Optional[str]:
        """Subir a catbox.moe (200MB max, permanente)"""
        try:
            session = FileHostUploader.get_robust_session()
            with open(file_path, 'rb') as f:
                files = {'fileToUpload': f}
                data = {'reqtype': 'fileupload'}
                response = session.post('https://catbox.moe/user/api.php', 
                                      files=files, data=data, timeout=120)
            
            if response.status_code == 200 and response.text.startswith('https://'):
                url = response.text.strip()
                logger.info(f"Subido a catbox.moe: {url}")
                return url
            return None
        except Exception as e:
            logger.error(f"Error subiendo a catbox.moe: {e}")
            return None
    
    @staticmethod
    def upload_to_gofile(file_path: Path) -> Optional[str]:
        """Subir a gofile.io (archivo temporal)"""
        try:
            session = FileHostUploader.get_robust_session()
            
            # Obtener servidor
            server_resp = session.get('https://api.gofile.io/getServer', timeout=30)
            if server_resp.status_code != 200:
                return None
            
            server_data = server_resp.json()
            if server_data.get('status') != 'ok':
                return None
            
            server = server_data['data']['server']
            
            # Subir archivo
            with open(file_path, 'rb') as f:
                files = {'file': f}
                upload_url = f'https://{server}.gofile.io/uploadFile'
                response = session.post(upload_url, files=files, timeout=120)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'ok':
                    download_page = data['data']['downloadPage']
                    logger.info(f"Subido a gofile.io: {download_page}")
                    return download_page
            return None
        except Exception as e:
            logger.error(f"Error subiendo a gofile.io: {e}")
            return None
    
    @staticmethod
    def upload_file(file_path: Path) -> Optional[str]:
        """Intentar subir archivo usando múltiples servicios"""
        # Lista de servicios a intentar
        upload_methods = [
            ('0x0.st', FileHostUploader.upload_to_0x0_st),
            ('catbox.moe', FileHostUploader.upload_to_catbox),
            ('gofile.io', FileHostUploader.upload_to_gofile),
        ]
        
        for service_name, upload_method in upload_methods:
            try:
                logger.info(f"Intentando subir a {service_name}...")
                url = upload_method(file_path)
                if url:
                    return url
            except Exception as e:
                logger.error(f"Fallo en {service_name}: {e}")
                continue
        
        logger.error("No se pudo subir a ningún servicio")
        return None

class SpotifyDownloader:
    def __init__(self):
        self.ffmpeg_ok = self._check_ffmpeg()
        self.sp = None
        self._init_spotify()
    
    def _init_spotify(self):
        """Inicializar cliente de Spotify"""
        try:
            if not SPOTIFY_CONFIG['client_secret'] or not SPOTIFY_CONFIG['refresh_token']:
                raise Exception("Faltan credenciales de Spotify en el .env")
                
            auth = SpotifyOAuth(**{k: v for k, v in SPOTIFY_CONFIG.items() if k != 'refresh_token'})
            token = auth.refresh_access_token(SPOTIFY_CONFIG['refresh_token'])
            self.sp = spotipy.Spotify(auth=token['access_token'])
            logger.info("✅ Spotify inicializado correctamente")
        except Exception as e:
            logger.error(f"Error inicializando Spotify: {e}")
            raise
    
    def _check_ffmpeg(self) -> bool:
        """Verificar si FFmpeg está disponible"""
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
            logger.info("✅ FFmpeg disponible")
            return True
        except:
            logger.warning("⚠️ FFmpeg no encontrado. Audio sin normalizar.")
            return False
    
    @staticmethod
    def clean_name(text: str) -> str:
        """Limpia nombres para archivos"""
        return text.translate(str.maketrans('\\/.:*?"<>|', '__________')).strip()[:50]
    
    def _extract_playlist_id(self, url: str) -> Optional[str]:
        """Extrae el ID de playlist de diferentes formatos de URL de Spotify"""
        patterns = [
            r'open\.spotify\.com/playlist/([a-zA-Z0-9]+)',
            r'spotify:playlist:([a-zA-Z0-9]+)',
            r'spotify\.com/playlist/([a-zA-Z0-9]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None
    
    def _search_youtube(self, track: str, artist: str, duration: int = 0) -> Optional[str]:
        """Busca en YouTube"""
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'socket_timeout': 10
        }
        
        try:
            with YoutubeDL(opts) as ydl:
                results = ydl.extract_info(f"ytsearch3:{track} {artist}"[:60], download=False)
                entries = results.get('entries', [])
                
                if not entries:
                    return None
                
                if not duration:
                    return entries[0].get('url')
                
                best_match = min(entries, key=lambda x: abs(x.get('duration', 0) - duration))
                return best_match.get('url')
                
        except Exception as e:
            logger.debug(f"Error buscando en YouTube: {e}")
            return None
    
    def _download_track(self, url: str, path: Path, name: str) -> Optional[Path]:
        """Descarga una pista"""
        temp = f"temp_{hash(url) % 10000}"
        opts = {
            "format": "bestaudio/best",
            "outtmpl": str(path / f"{temp}.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }] if self.ffmpeg_ok else [],
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 15,
            'retries': 1,
        }
        
        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([url])
            
            extensions = ['*.mp3', '*.m4a', '*.webm', '*.opus'] if not self.ffmpeg_ok else ['*.mp3']
            for ext in extensions:
                for f in path.glob(f"{temp}{ext}"):
                    final = path / f"{name}.mp3"
                    f.rename(final)
                    return final
                    
        except Exception as e:
            logger.debug(f"Error descargando: {e}")
            return None
    
    def _process_track(self, track_data: tuple) -> bool:
        """Procesa una pista - versión para ThreadPoolExecutor"""
        track, path, progress_callback = track_data
        
        name = self.clean_name(track["name"])
        artist = self.clean_name(", ".join([a["name"] for a in track["artists"]]))
        filename = f"{artist} - {name}"
        
        if list(path.glob(f"*{name}*.mp3")) or list(path.glob(f"*{name}*.m4a")):
            if progress_callback:
                progress_callback("skip")
            return True
        
        duration = track.get('duration_ms', 0) // 1000 if track.get('duration_ms') else 0
        url = self._search_youtube(name, artist, duration)
        
        if not url:
            if progress_callback:
                progress_callback("fail")
            return False
        
        file = self._download_track(url, path, filename)
        success = file is not None
        
        if progress_callback:
            progress_callback("success" if success else "fail")
        
        return success
    
    async def download_playlist(self, url: str, message_updater=None) -> Optional[str]:
        """Descarga playlist y la sube a la nube"""
        try:
            playlist_id = self._extract_playlist_id(url)
            if not playlist_id:
                raise Exception("No se pudo extraer el ID de la playlist")
            
            playlist = self.sp.playlist(playlist_id)
            name = self.clean_name(playlist['name'])
            
            # Crear directorio temporal único
            temp_id = str(int(time.time()))
            path = TEMP_DIR / f"{name}_{temp_id}"
            path.mkdir(exist_ok=True)
            
            if message_updater:
                await message_updater(f"📋 **{name}**\n⏳ Obteniendo pistas...")
            
            # Obtener pistas
            tracks = []
            offset = 0
            while True:
                results = self.sp.playlist_items(playlist_id, limit=100, offset=offset)
                valid_tracks = [item['track'] for item in results['items'] 
                              if item['track'] and item['track'].get('id')]
                tracks.extend(valid_tracks)
                if not results['next']: 
                    break
                offset += 100
            
            if not tracks:
                raise Exception("No se encontraron pistas válidas")
            
            if message_updater:
                await message_updater(f"📋 **{name}**\n🎵 {len(tracks)} pistas encontradas\n📊 Descargando: 0/{len(tracks)} (✅0 ❌0)")
            
            # Contadores thread-safe
            downloaded = 0
            failed = 0
            skipped = 0
            progress_lock = threading.Lock()
            current_loop = asyncio.get_event_loop()
            
            def sync_callback(status: str):
                nonlocal downloaded, failed, skipped
                with progress_lock:
                    if status == "success":
                        downloaded += 1
                    elif status == "fail":
                        failed += 1
                    elif status == "skip":
                        downloaded += 1
                        skipped += 1
                    
                    total_processed = downloaded + failed
                    
                    # Actualizar cada 3 pistas o al final
                    if total_processed % 3 == 0 or total_processed == len(tracks):
                        if message_updater:
                            progress_msg = f"📋 **{name}**\n🎵 {len(tracks)} pistas encontradas\n📊 Descargando: {total_processed}/{len(tracks)} (✅{downloaded} ❌{failed})"
                            current_loop.call_soon_threadsafe(
                                lambda: asyncio.create_task(message_updater(progress_msg))
                            )
            
            track_data = [(track, path, sync_callback) for track in tracks]
            
            # Descargar en paralelo
            with ThreadPoolExecutor(max_workers=6) as executor:
                await current_loop.run_in_executor(
                    executor, 
                    lambda: list(executor.map(self._process_track, track_data))
                )
            
            if message_updater:
                await message_updater(f"📋 **{name}**\n✅ Descarga completada: {downloaded}/{len(tracks)}\n📦 Creando ZIP y subiendo...")
            
            # Crear ZIP
            zip_path = TEMP_DIR / f"{name}.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                audio_files = list(path.glob("*.mp3")) + list(path.glob("*.m4a"))
                for audio_file in audio_files:
                    zf.write(audio_file, audio_file.name)
            
            # Limpiar directorio temporal
            shutil.rmtree(path, ignore_errors=True)
            
            if not audio_files:
                raise Exception("No se descargaron archivos de audio")
            
            # Subir a la nube
            download_url = FileHostUploader.upload_file(zip_path)
            
            # Limpiar archivo local
            if zip_path.exists():
                zip_path.unlink()
            
            if not download_url:
                raise Exception("No se pudo subir el archivo a la nube")
            
            return download_url
            
        except Exception as e:
            logger.error(f"Error: {e}")
            # Limpiar en caso de error
            if 'path' in locals() and path.exists():
                shutil.rmtree(path, ignore_errors=True)
            if 'zip_path' in locals() and zip_path.exists():
                zip_path.unlink()
            raise

# Instancia global
_downloader = None

async def set_up(ctx, url: str, bot):
    """Función principal con mensajes optimizados"""
    global _downloader
    
    try:
        # Responder inmediatamente para evitar timeout
        await ctx.response.defer()
        
        # Mensaje inicial usando followup
        if _downloader is None:
            initial_message = await ctx.followup.send("🔧 Inicializando downloader...", wait=True)
            try:
                _downloader = SpotifyDownloader()
            except Exception as e:
                await initial_message.edit(content=f"❌ Error inicializando: {str(e)}")
                return
        else:
            initial_message = await ctx.followup.send("🚀 Iniciando descarga...", wait=True)
        
        # Validaciones
        if not url:
            await initial_message.edit(content="❌ No se proporcionó una URL.")
            return
        
        playlist_id = _downloader._extract_playlist_id(url)
        if not playlist_id:
            await initial_message.edit(content="❌ URL de Spotify inválida.\n**Formatos válidos:**\n• `https://open.spotify.com/playlist/ID`\n• `spotify:playlist:ID`")
            return
        
        try:
            playlist = _downloader.sp.playlist(playlist_id, fields="name,public")
        except Exception as e:
            await initial_message.edit(content=f"❌ No se pudo acceder a la playlist: {str(e)}")
            return
        
        # Función para actualizar el mensaje de progreso
        async def update_progress(message: str):
            try:
                await initial_message.edit(content=message)
            except Exception as e:
                logger.debug(f"Error actualizando mensaje: {e}")
        
        # Descargar y subir
        download_url = await _downloader.download_playlist(url, update_progress)
        
        # Mensaje final con embed
        embed = discord.Embed(
            title="🎵 Descarga Completada",
            description="Tu playlist está lista para descargar",
            color=0x1DB954
        )
        embed.add_field(name="📋 Playlist", value=f"**{playlist['name']}**", inline=False)
        embed.add_field(name="🔗 Enlace", value=f"[📥 Descargar ZIP]({download_url})", inline=False)
        embed.add_field(name="⏰ Válido por", value="Permanente*", inline=True)
        embed.add_field(name="📦 Formato", value="MP3 (192kbps)", inline=True)
        embed.set_footer(text="*Según las políticas del servicio de hosting")
        
        await ctx.followup.send(embed=embed)
        
    except Exception as e:
        try:
            # Si initial_message existe, editarlo
            if 'initial_message' in locals() and initial_message is not None:
                await initial_message.edit(content=f"❌ Error: {str(e)}")
            else:
                # Si no existe, enviar mensaje nuevo
                await ctx.followup.send(f"❌ Error: {str(e)}")
        except:
            # Último recurso
            logger.error(f"Error crítico en set_up: {e}")

def cleanup_old_files():
    """Limpiar archivos temporales antiguos"""
    try:
        current_time = time.time()
        for file in TEMP_DIR.glob("*"):
            if current_time - file.stat().st_mtime > 3600:  # 1 hora
                if file.is_file():
                    file.unlink()
                elif file.is_dir():
                    shutil.rmtree(file, ignore_errors=True)
    except Exception as e:
        logger.error(f"Error limpiando: {e}")

# Limpiar al iniciar
cleanup_old_files()