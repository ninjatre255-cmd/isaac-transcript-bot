import json
import os
import re
import subprocess

from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from google.oauth2.service_account import Credentials
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

CHANNEL_URL = "https://www.youtube.com/@isaac_davydov/videos"
SEEN_VIDEOS_FILE = "seen_videos.json"


def get_recent_videos(limit=10):
    """Use yt-dlp to list recent videos from the channel."""
    print(f"Fetching recent videos from {CHANNEL_URL}...")
    result = subprocess.run(
        [
            "yt-dlp",
            "--flat-playlist",
            "--print", "%(id)s|||%(title)s|||%(upload_date)s",
            "--playlist-end", str(limit),
            "--quiet", "--no-warnings",
            CHANNEL_URL,
        ],
        capture_output=True, text=True,
    )
    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|||")
        if len(parts) >= 2:
            vid_id = parts[0].strip()
            title = parts[1].strip()
            date = parts[2].strip() if len(parts) > 2 else "unknown"
            if vid_id:
                videos.append({"id": vid_id, "title": title, "date": date})
    print(f"Found {len(videos)} recent videos on the channel")
    return videos


def get_transcript(video_id):
    """Fetch transcript using youtube-transcript-api (no bot detection issues)."""
    try:
        # Support both old (class method) and new (instance method) API styles
        try:
            api = YouTubeTranscriptApi()
            transcript_list = api.fetch(video_id, languages=["en", "en-US"])
        except TypeError:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US"])
        lines = []
        for entry in transcript_list:
            # Handle both dict entries and object entries (new API returns objects)
            if hasattr(entry, 'text'):
                t = int(entry.start)
                text = entry.text.strip()
            else:
                t = int(entry["start"])
                text = entry["text"].strip()
            minutes = t // 60
            seconds = t % 60
            if text:
                lines.append(f"[{minutes:02d}:{seconds:02d}] {text}")
        result = "\n".join(lines)
        return result if result else None
    except (NoTranscriptFound, TranscriptsDisabled):
        print(f"  No transcript available for this video")
        return None
    except Exception as e:
        print(f"  Could not get transcript: {e}")
        return None


def load_seen_videos():
    if os.path.exists(SEEN_VIDEOS_FILE):
        with open(SEEN_VIDEOS_FILE, "r") as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else set()
    return set()


def save_seen_videos(seen):
    with open(SEEN_VIDEOS_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=2)


def main():
    creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(
        creds_json, scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    drive_service = build("drive", "v3", credentials=creds)
    folder_id = os.environ["DRIVE_FOLDER_ID"]

    videos = get_recent_videos(limit=10)
    seen = load_seen_videos()
    uploaded = 0

    for video in videos:
        vid_id = video["id"]
        title = video["title"]
        date = video["date"]

        if vid_id in seen:
            print(f"  Already seen: {title}")
            continue

        print(f"\n  New video found: {title}")
        transcript = get_transcript(vid_id)
        if not transcript:
            print(f"  Skipping (no transcript)")
            continue

        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:80]
        filename = f"{date}_{safe_title}.txt"
        header = (
            f"Title: {title}\n"
            f"Video ID: {vid_id}\n"
            f"URL: https://www.youtube.com/watch?v={vid_id}\n"
            f"Date: {date}\n\n"
        )
        content = (header + transcript).encode("utf-8")
        file_metadata = {"name": filename, "parents": [folder_id]}
        media = MediaInMemoryUpload(content, mimetype="text/plain")
        drive_service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()
        print(f"  Uploaded: {filename}")
        seen.add(vid_id)
        save_seen_videos(seen)
        uploaded += 1

    print(f"\nDone. Uploaded {uploaded} new transcript(s).")


if __name__ == "__main__":
    main()
