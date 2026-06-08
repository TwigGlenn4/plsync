#!/usr/bin/python3
# Twig Griffin
# Download a playlist from YouTube/YouTube Music, without redownloading existing tracks.
# * Detects existing tracks using the 'purl' metadata tag populated with the URL by yt-dlp by default
# Dependencies
#   tinytag - read metadata on existing tracks
#   yt-dlp - get playlist information and download tracks
#   rsgain - automatically adjust ReplayGain metadata for a more consistent volume across tracks
#   yt-dlp-ejs, deno - solve JS challenges required by YouTube
# Install Dependencies
#   pip3 install tinytag yt-dlp yt-dlp-ejs
#   apt install rsgain deno

import argparse
import json
from os import getcwd, listdir, makedirs, path

from tinytag import TinyTag
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError, PostProcessingError

CONFIG_PATH = "~/.config/plsync/config.json"
DEFAULT_CONFIG = {
  "ask_before_downloading": True,
  "cookies_path": "~/.config/plsync/cookies.txt",
  "filename_format": "%(artist,channel|Unknown)s - %(track,title|Unknown)s.%(ext)s",
  "ytdlp_quiet": False,
  "playlists": [
    {
      "path": "~/Music/Tracks",
      "urls": [ "https://music.youtube.com/playlist?list=OLAK5uy_k8FKntOa4ITd-iDboWkQD-0z0Ju__9cEk",
                "https://music.youtube.com/playlist?list=OLAK5uy_nYgA6_SXlD09Kc6G0TmA91je3qDeD9lzs" ]
    }
  ]
}


YDL_OPTS = {
  'cookiefile': "",
  'extract_flat': 'discard_in_playlist',
  'final_ext': 'mp3',
  'format': 'bestaudio/best',
  'fragment_retries': 2,
  'ignoreerrors': 'only_download',
  'outtmpl': {'default': '%(artist,channel|Unknown)s - %(track,title|Unknown)s.%(ext)s',
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
  'quiet': True,
  'writethumbnail': True
}

YDL_DATA_OPTS = {
  'cookiefile': "",
  'extract_flat': True,  # Extract only the video information, not the actual videos
  'force_generic_extractor': True,
  'noplaylist': False,
  'quiet': True,  # Suppress console output
  'no_warnings': True, # Hide "YouTube Music is not directly supported" warning
  'simulate': True # Don't actually download, just simulate to get info
}


def expand_path(work_path:str) -> str:
  """Expand environment vars and the '~' home shortcut"""
  return path.abspath(path.expanduser(path.expandvars(work_path)))


def read_config_file(config_path: str) -> dict:
  # expand vars ($HOME) and user (~)
  config_path = expand_path(config_path)


  try:
    with open(config_path, "r") as config_file:
      print("Using config file", config_path)
      loaded_config = json.load(config_file)
      config = DEFAULT_CONFIG.copy()
      for key in config:
        if key in loaded_config:
          config[key] = loaded_config[key]
  except IOError:
    print(f"Could not open config file \"{config_path}\", using defaults.")
    config = DEFAULT_CONFIG.copy()


  # expand and sanitize cookies_path
  config["cookies_path"] = expand_path(config["cookies_path"])
  if not path.isfile(config["cookies_path"]):
    print(f"[CONFIG] could not open cookie file \"{config["cookies_path"]}\"")
    config["cookies_path"] = None

  # store yt-dlp cookie file
  YDL_OPTS["cookiefile"] = config["cookies_path"]
  YDL_DATA_OPTS["cookiefile"] = config["cookies_path"]

  YDL_OPTS["quiet"] = config["ytdlp_quiet"]
  if config["ytdlp_quiet"]: # if ytdlp_quiet, also make rsgain quiet
    for post_processor in YDL_OPTS["postprocessors"]:
      if "exec_cmd" in post_processor:
        if post_processor["exec_cmd"][0][:6] == "rsgain":
          post_processor["exec_cmd"][0] += " -q"

  # verify playlist list
  for playlist in config["playlists"]:
    if "path" not in playlist or "urls" not in playlist: # if playlist is malformed, skip it
      config["playlists"].remove(playlist)
      print("[CONFIG] malformed playlist (missing \"path\" or \"urls\" keys):", playlist)
    else:
      playlist["path"] = expand_path(playlist["path"])

  return config


def get_youtube_slug( link:str ) -> str:
  splitStr = "v="
  v_param = link.split(splitStr, 1)[1]
  slug:str = v_param.split("&", 1)[0]

  return slug


def find_local_tracks( folder: str ) -> list[str]:
  found_songs = []

  # print(os_listdir(path))

  for fname in listdir(folder):
    filename = path.join(folder, fname)
    # print(filename)

    if not TinyTag.is_supported(filename):
      # print("  Unsupported file, skipping " + filename)
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
  print("  Finding metadata using yt-dlp...    ", end="", flush=True)

  found_songs: list[str] = []
  playlist_info: dict = {}

  with YoutubeDL(YDL_DATA_OPTS) as ytdl: # type: ignore[arg-type]
    try:
      playlist_info = dict( ytdl.extract_info(playlist_link, download=False) ) # explicitly cast YoutubeDL._InfoDict to dict
    except (DownloadError, ExtractorError):
      # ytdl.extract_info() already printed an error message
      return []


  if "_type" in playlist_info and playlist_info["_type"] == "playlist":
    print(f"found playlist \"{playlist_info['title']}\" containing {playlist_info['playlist_count']} songs")
    for song in playlist_info["entries"]:
      slug = song['id']
      found_songs.append(slug)
      # print("    "+slug)

  elif "duration_string" in playlist_info:
    print(f"found video \"{playlist_info['title']}\" by {playlist_info['channel']}")
    slug = playlist_info['id']
    found_songs = [slug]
    # print("    "+slug)

  else:
    print("Invalid link!")

  return found_songs



# Find the songs in remote_songs that are not in local_songs
def get_songs_needed(local_songs:list[str], remote_songs:list[str]) -> list[str]:
  songs_needed = []
  for song in remote_songs:
    if song not in local_songs:
      songs_needed.append(song)

  return songs_needed



def download_song(ytdl:YoutubeDL, slug:str) -> str:
  # print(f"Downloading {slug}...")
  error = ""
  try:
    track_info = ytdl.extract_info(slug, download=False)
    if "artists" in track_info:
      print(track_info["artists"][0], end="")
    elif "channel" in track_info:
      print(track_info["channel"], end="")
    else:
      print("MISSING_ARTIST_KEY", end="")

    print(" - ", end="")

    if "title" in track_info:
      print(track_info["title"])
    elif "fulltitle" in track_info:
      print(track_info["fulltitle"])
    else:
      print("MISSING_TITLE_KEY")

    ytdl.process_ie_result(track_info, download=True)

  except (DownloadError, ExtractorError, PostProcessingError) as e:
    error = slug
    print(f"Error while downloading [{slug}]: {e}")

  return error


def deduplicate(list1:list, list2:list):
  for item in list2:
    if item not in list1:
      list1.append(item)
  return list1


def download_playlist(download_path: str, playlist_urls: list[str], config: dict) -> int:
  print("Processing", download_path)

  makedirs(download_path, exist_ok=True) # ensure download path exists

  local_tracks = find_local_tracks(download_path)
  print(f"  Found {len(local_tracks)} songs locally." )


  # Build list of downloads
  download_list = []
  seen_tracks = local_tracks.copy()
  unique_playlist_tracks = []

  for url in playlist_urls:
    playlist_tracks = find_playlist_songs_ytdlp(url)
    new_tracks = get_songs_needed(seen_tracks, playlist_tracks)

    unique_playlist_tracks = deduplicate(unique_playlist_tracks, playlist_tracks)

    seen_tracks.extend(new_tracks)
    download_list.extend(new_tracks)


  # Inform the user of how many songs will be downloaded, or return if none
  if len(download_list) == 0:
    print(f"All {len(unique_playlist_tracks)} songs already downloaded.")
    return 0
  # print(download_list)
  print(f"  Need to download {len(download_list)} of {len(unique_playlist_tracks)} songs.")


  if config["ask_before_downloading"]:
    download = input("  Continue with download? (y/N): ").strip().lower()
    if not (download == "y" or download == "yes"):
      return 0

  errored_track_slugs = []

  # setup yt-dlp options with path.

  yt_dlp_opts = YDL_OPTS.copy()
  yt_dlp_opts["outtmpl"]["default"] = path.join(download_path, config["filename_format"])

  # Download the songs
  with YoutubeDL(yt_dlp_opts) as yt_downloader: # type: ignore[arg-type]
    num_songs_downloaded = 0
    for slug in download_list:
      num_songs_downloaded += 1
      print(f"    Downloading song {num_songs_downloaded}/{len(download_list)}: ", end="", flush=True)
      error_slug = download_song(yt_downloader, slug)
      if error_slug != "":
        errored_track_slugs.append(error_slug)
      if not config["ytdlp_quiet"]:
        print("----------------------------------------")

  print(f"  Downloaded {len(download_list)} songs!")

  if len(errored_track_slugs) > 0:
    print(f"  Errored tracks: ({len(errored_track_slugs)}) {str(errored_track_slugs)}")

  return len(download_list)


def write_config(new_config_path: str) -> int:

  new_config_path = expand_path(new_config_path)
  makedirs(path.dirname(new_config_path), exist_ok=True) # ensure path to the new config file exists

  if path.isfile(new_config_path):
    prompt = input(f"Overwrite existing file at \"{new_config_path}\"? (y/N): ").strip().lower()
    if not (prompt == "y" or prompt == "yes"):
      return 0

  try:
    with open(new_config_path, "w") as new_config_file:
      json.dump(DEFAULT_CONFIG, new_config_file, indent=2)
  except IOError:
    print(f"Error: Could not write to \"{new_config_path}\"")
    return -1

  print(f"Wrote default config to \"{new_config_path}\"")
  return 0



def main():

  parser = argparse.ArgumentParser(description="Synchronize youtube playlists into folders with reduced redownloading")
  parser.add_argument("-c", "--config", type=str, default=CONFIG_PATH, help="Path to config file (default: \"~/.config/plsync/config.json\").")
  parser.add_argument("-w", "--wconf", type=str, nargs="?", default="", const=CONFIG_PATH, help="Write a default config file at the given path (default: \"~/.config/plsync/config.json\").")
  prompt_group = parser.add_mutually_exclusive_group()
  prompt_group.add_argument("-y", "--yes", action="store_true", help="Skip the \"Continue with download?\" prompt.")
  prompt_group.add_argument("-a", "--ask", action="store_true", help="Force the \"Continue with download?\" prompt.")
  parser.add_argument("url", type=str, nargs="?", default="", help="Download this playlist or video into the current working directory")
  args = parser.parse_args()

  # write config and exit if -w argument used
  if args.wconf != "":
    return write_config(args.wconf)

  # read config file
  config = read_config_file(args.config)

  # override ask_before_downloading if -y passed
  if args.yes:
    config["ask_before_downloading"] = False
  elif args.ask:
    config["ask_before_downloading"] = True

  # download url into CWD if url argument used
  if args.url:
    download_playlist(getcwd(), [args.url], config)
    return 0

  # regular behaviour downloading playlists from config
  for playlist in config["playlists"]:
    download_playlist(playlist["path"], playlist["urls"], config)

  return 0


if __name__ == "__main__":
  try:
    main()
  except KeyboardInterrupt:
    exit(0)
