"""
Script para obtener el refresh token de Spotify
Ejecuta este script una vez para obtener el REFRESH_TOKEN para tu .env
"""

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os

load_dotenv()

# Configuración - asegúrate de que estas estén en tu .env
CLIENT_ID = '382cbaacee964b1f9bafdf14ab86f549'
CLIENT_SECRET = os.getenv('CLIENT_SECRET')  # Debes obtener esto de Spotify
REDIRECT_URI = 'https://www.google.com/?hl=es'

if not CLIENT_SECRET:
    print("❌ Error: CLIENT_SECRET no encontrado en .env")
    print("Ve a https://developer.spotify.com/dashboard y obtén tu CLIENT_SECRET")
    exit()

# Configurar OAuth
sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope='playlist-read-private playlist-read-collaborative'
)

# Obtener URL de autorización
auth_url = sp_oauth.get_authorize_url()
print("1. Ve a esta URL en tu navegador:")
print(auth_url)
print("\n2. Después de autorizar, serás redirigido a Google.")
print("3. Copia la URL completa de la página a la que fuiste redirigido y pégala aquí:")

# Obtener código de la URL de respuesta
response_url = input("\nPega la URL de respuesta aquí: ").strip()

try:
    # Extraer código de la URL
    code = sp_oauth.parse_response_code(response_url)
    
    # Obtener token
    token_info = sp_oauth.get_access_token(code)
    
    print(f"\n✅ ¡Éxito! Tu REFRESH_TOKEN es:")
    print(f"REFRESH_TOKEN={token_info['refresh_token']}")
    print(f"\nAñade esta línea a tu archivo .env")
    
except Exception as e:
    print(f"❌ Error: {e}")
    print("Asegúrate de copiar la URL completa después de la autorización.")    