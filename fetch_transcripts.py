import glob
import json
import os
import re
import shutil
import subprocess
import tempfile

from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from google.oauth2.service_account import Credentials

CHANNEL_URL = "https://www.youtube.com/@isaac_davydov/videos"
SEEN_VIDEOS_FILE = "seen_videos.json"


def get_recent_videos(limit=10):
    """Use yt-dlp to list recent videos from the channel (no API key needed)."""
    print(f"Fetching recent videos from {CHANNEL_URL}...")
    result = subprocess.run(
        [
            "yt-dlp",
            "--flat-playlist",
            "--print", "%(id)s|||%(title)s|||%(upload_date)s",
            "--playlist-end", str(limit),
            "--quiet",
            "--no-warnings",
            CHANNEL_URL,
        ],
        capture_output=True,
        text=True,
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


def parse_vtt_to_text(vtt_content):
    """Parse a VTT subtitle file into timestamped plain text, deduplicating repeated lines."""
    lines = []
    current_time = None
    current_text = []
    seen_texts = set()

    for line in vtt_content.split("\n"):
        line = line.strip()
        time_match = re.match(r"(\d+):(\d+):(\d+\.\d+)\s*-->", line)
        if time_match:
            if current_text:
                text = " ".join(current_text)
                if text not in seen_texts:
                    seen_texts.add(text)
                    lines.append(f"[{current_time}] {text}")
                current_text = []
            hours = int(time_match.group(1))
            minutes = int(time_match.group(2)) + hours * 60
            seconds = int(float(time_match.group(3)))
            current_time = f"{minutes:02d}:{seconds:02d}"
        elif (
            line
            and not line.startswith("WEBVTT")
            and not line.startswith("NOTE")
            and "-->" not in line
            and not line.isdigit()
        ):
            clean = re.sub(r"<[^>]+>", "", line).strip()
            if clean:
                current_text.append(clean)

    if current_text and current_time:
        text = " ".join(current_text)
        if text not in seen_texts:
            lines.append(f"[{current_time}] {text}")

    return "\n".join(lines) if lines else None


def get_transcript(video_id):
    """Use yt-dlp to download auto-generated English subtitles for a video."""
    cookies_content = os.environ.get("YOUTUBE_COOKIES", "")
    cookies_path = None
    tmpdir = None

    try:
        if cookies_content:
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
            tmp.write(cookies_content)
            tmp.close()
            cookies_path = tmp.name

        tmpdir = tempfile.mkdtemp()
        url = f"https://www.youtube.com/watch?v={video_id}"

        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-auto-subs",
            "--sub-lang", "en.*",
            "--sub-format", "vtt",
            "--output", os.path.join(tmpdir, "%(id)s"),
            "--quiet",
            "--no-warnings",
        ]

        if cookies_path:
            cmd.extend(["--cookies", cookies_path])

        cmd.append(url)
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        vtt_files = glob.glob(os.path.join(tmpdir, "*.vtt"))
        if not vtt_files:
            print(f"  No subtitles found for this video")
            return None

        with open(vtt_files[0], "r", encoding="utf-8") as f:
            content = f.read()

        return parse_vtt_to_text(content)

    except Exception as e:
        print(f"  Could not get transcript: {e}")
        return None
    finally:
        if cookies_path and os.path.exists(cookies_path):
            os.unlink(cookies_path)
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


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
        header = f"Title: {title}\nVideo ID: {vid_id}\nURL: https://www.youtube.com/watch?v={vid_id}\nDate: {date}\n\n"
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
