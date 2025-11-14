#!/usr/bin/python3
# Twig Griffin
# Download a playlist from YouTube/YouTube Music, without redownloading existing tracks.
# Detects existing tracks using the 'purl' metadata tag populated with the URL by yt-dlp by default
# Dependencies
#   tinytag - read metadata on existing tracks
#   yt-dlp - get playlist information and download tracks
#   rsgain - automatically adjust ReplayGain metadata for a more consistent volume across tracks
# Install Dependencies
#   pip3 install tinytag yt-dlp
#   apt install rsgain

from os import listdir as os_listdir
from os import path as path
from os import sep as PATH_SEPARATOR
from sys import argv as sys_argv
from tinytag import TinyTag
import yt_dlp

CONFIG_MUSIC_PATH = "/home/twig/Music/Tracks/"
CONFIG_COOKIES_PATH = "cookies.txt"
CONFIG_DEFAULT_PLAYLIST_URLS = [ "https://music.youtube.com/playlist?list=PL899RuEJchv4GsWD1onvazX51kF3naNJN",
                                 "https://music.youtube.com/playlist?list=PL899RuEJchv6ShrUrjGMunZFUl9VYdVNI"]
CONFIG_ASK_BEFORE_DOWNLOADING = True

# validate paths
MUSIC_PATH = path.abspath(CONFIG_MUSIC_PATH) + PATH_SEPARATOR
COOKIES_PATH = path.abspath(CONFIG_COOKIES_PATH)


YDL_OPTS = {
  'cookiefile': COOKIES_PATH,
  'extract_flat': 'discard_in_playlist',
  'final_ext': 'mp3',
  'format': 'bestaudio/best',
  'fragment_retries': 2,
  'ignoreerrors': 'only_download',
  'outtmpl': {'default': MUSIC_PATH+'%(artist,channel|Unknown)s - %(track,title|Unknown)s.%(ext)s',
      'pl_thumbnail': ''},
  'postprocessors': [{'key': 'FFmpegExtractAudio',
      'nopostoverwrites': False,
      'preferredcodec': 'mp3',
      'preferredquality': '5'},
    {'add_chapters': True,
      'add_infojson': 'if_exists',
      'add_metadata': True,
      'key': 'FFmpegMetadata'},
    {'already_have_thumbnail': False, 'key': 'EmbedThumbnail'},
    {'key': 'FFmpegConcat',
      'only_multi_video': True,
      'when': 'playlist'},
    {'exec_cmd': ['rsgain custom -c a -l -10'],
      'key': 'Exec',
      'when': 'after_move'}],
  'retries': 1,
  'warn_when_outdated': True,
  # 'quiet': True,
  'writethumbnail': True}

YDL_DATA_OPTS = {
  'cookiefile': COOKIES_PATH,
  'extract_flat': True,  # Extract only the video information, not the actual videos
  'force_generic_extractor': True,
  'noplaylist': False,
  'quiet': True,  # Suppress console output
  'no_warnings': True, # Hide "YouTube Music is not directly supported" warning
  'simulate': True, # Don't actually download, just simulate to get info
}

def get_youtube_slug( link:str ) -> str:
  splitStr = "v="
  v_param = link.split(splitStr, 1)[1]
  slug:str = v_param.split("&", 1)[0]

  return slug


def find_local_songs( path:str ) -> list[str]:
  found_songs = []

  # print(os_listdir(path))
  for fname in os_listdir(path):
    filename = path + fname
    # print(filename)

    if not TinyTag.is_supported(filename):
      print("  Unsupported file, skipping " + filename)
      continue

    tag = TinyTag.get(filename)
    purl = tag.other.get("purl")

    if purl is None:
      # print(f"  No purl tag to read slug from, skipping {filename}")
      continue

    slug = get_youtube_slug(purl[0])
    if slug == "":
      print(f"  Could not parse youtube slug, skipping {filename}")
      continue
    
    # print("  [" + slug + "]: " + tag.artist + " - " + tag.title)
    # print()
    
    found_songs.append(slug)

  return found_songs


def find_playlist_songs_ytdlp(playlist_link:str) -> list[str]:
  print("Finding playlist using yt-dlp...")

  found_songs = []
  playlist_info = None
  
  with yt_dlp.YoutubeDL(YDL_DATA_OPTS) as ytdl:
    playlist_info = ytdl.extract_info(playlist_link, download=False)

  # print(playlist_info['_type'])
  # print(playlist_info)

  if "_type" in playlist_info and playlist_info["_type"] == "playlist":
    print(f"  Found playlist \"{playlist_info['title']}\" containing {playlist_info['playlist_count']} songs")
    for song in playlist_info['entries']:
      slug = song['id']
      found_songs.append(slug)
      # print("    "+slug)

  elif "duration_string" in playlist_info:
    print(f"  Found video \"{playlist_info['title']}\" by {playlist_info['channel']}")
    slug = playlist_info['id']
    found_songs = [slug]
    # print("    "+slug)

  else:
    print("  Invalid link!")
    
  return found_songs
    


# Find the songs in remote_songs that are not in local_songs
def get_songs_needed(local_songs:list[str], remote_songs:list[str]) -> list[str]:
  songs_needed = []
  for song in remote_songs:
    if not song in local_songs:
      songs_needed.append(song)

  return songs_needed



def download_song(ytdl:yt_dlp.YoutubeDL, slug:str) -> str:
  # print(f"Downloading {slug}...")
  error_code = 1
  error_slug = ""
  # try:
  error_code = ytdl.download(slug)

  if error_code != 0:
    error_slug = slug
    # with yt_dlp.YoutubeDL(YDL_DATA_OPTS) as ytdl:
    print(f"    ERROR: Error while downloading [{slug}]. NOTE: Can't tell if serious or non-fatal error. Song may have been downloaded fine.")
    
  return error_slug


def deduplicate(list1:list, list2:list):
  for item in list2:
    if item not in list1:
      list1.append(item)
  return list1


def main():

  print(COOKIES_PATH)
  exit()

  # Find all local songs
  print("Finding local songs...")
  found_songs = find_local_songs(MUSIC_PATH)
  print(f"  Found {len(found_songs)} songs locally." )


  # Use arguments as playlist urls if they exist, default to CONFIG_DEFAULT_PLAYLIST_URLS
  # print(f"len(sys_argv)={len(sys_argv)}")
  playlist_urls = CONFIG_DEFAULT_PLAYLIST_URLS
  if len(sys_argv) > 1:
    playlist_urls = []
    for i in range(1, len(sys_argv)):
      playlist_urls[i-1] = sys_argv[i]
  
  if (playlist_urls == [] or not isinstance(playlist_urls[0], str)):
    print("No URL specified! Please give a URL in quotes as an argument, or populate the CONFIG_DEFAULT_PLAYLIST_URLS constant in the script.")
    return 1

  # Find songs in the online playlists that don't exist locally
  download_list = []
  unique_pl_list = []
  for pl_url in playlist_urls:
    playlist_songs = find_playlist_songs_ytdlp(pl_url)
    new_songs = get_songs_needed(found_songs, playlist_songs)

    unique_pl_list = deduplicate(unique_pl_list, playlist_songs)
    download_list.extend(new_songs)
    found_songs.extend(new_songs)

  # Inform the user of how many songs will be downloaded, or return if none
  if len(download_list) == 0:
    print("All songs already downloaded.")
    return 0
  # print(download_list)
  print(f"Need to download {len(download_list)} of {len(unique_pl_list)} songs.")

  if CONFIG_ASK_BEFORE_DOWNLOADING:
    download = input("Continue with Download? (y/N): ")
    if not (download == "y" or download == "Y"):
      return 0
    
  errored_slugs = []
  
  # Download the songs
  with yt_dlp.YoutubeDL(YDL_OPTS) as yt_downloader:
    num_songs_downloaded = 0
    for slug in download_list:
      num_songs_downloaded += 1
      print(f"  Downloading song {num_songs_downloaded}/{len(download_list)}")
      error_slug = download_song(yt_downloader, slug)
      if error_slug != "":
        errored_slugs.append(error_slug)
      print("--------------------")

  print(f"Done, downloaded {len(download_list)} songs!")

  if len(errored_slugs) > 0:
    print("Errored songs: " + str(errored_slugs))
  return 0

if __name__ == "__main__":
  try:
    main()
  except KeyboardInterrupt:
    exit(0)
