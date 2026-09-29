"""Bağlantı testi: album.getInfo (Cher - Believe)."""
from lastfm_client import call

data = call("album.getinfo", artist="Cher", album="Believe")
album = data["album"]
print("Bağlantı başarılı!")
print(f"Albüm     : {album['name']}")
print(f"Sanatçı   : {album['artist']}")
print(f"Dinleyici : {int(album['listeners']):,}")
print(f"Çalınma   : {int(album['playcount']):,}")
print(f"Parça sayısı: {len(album.get('tracks', {}).get('track', []))}")
