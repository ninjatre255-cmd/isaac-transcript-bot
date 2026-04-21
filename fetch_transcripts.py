import json
import os
import subprocess
from youtube_transcript_api import YouTubeTranscriptApi
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
            "--no-warnings",
            CHANNEL_URL,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"yt-dlp error: {result.stderr}")
        return []

    videos = []
    for line in result.stdout.strip().split("\n"):
        if "|||" in line:
            parts = line.split("|||")
            if len(parts) >= 2:
                videos.append(
                    {
                        "id": parts[0].strip(),
                        "title": parts[1].strip(),
                        "date": parts[2].strip() if len(parts) > 2 else "unknown",
                    }
                )
    return videos


def load_seen_videos():
    """Load the set of already-processed video IDs."""
    if os.path.exists(SEEN_VIDEOS_FILE):
        with open(SEEN_VIDEOS_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen_videos(seen):
    """Save the updated set of processed video IDs."""
    with open(SEEN_VIDEOS_FILE, "w") as f:
        json.dump(sorted(list(seen)), f, indent=2)


def get_transcript(video_id):
    """Pull transcript for a video using youtube-transcript-api."""
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        lines = []
        for entry in transcript:
            minutes = int(entry["start"] // 60)
            seconds = int(entry["start"] % 60)
            lines.append(f"[{minutes:02d}:{seconds:02d}] {entry['text']}")
        return "\n".join(lines)
    except Exception as e:
        print(f"  Could not get transcript: {e}")
        return None


def upload_to_drive(filename, content, folder_id, service):
    """Upload a text file to the specified Google Drive folder."""
    media = MediaInMemoryUpload(
        content.encode("utf-8"),
        mimetype="text/plain",
        resumable=False,
    )
    file_metadata = {
        "name": filename,
        "parents": [folder_id],
        "mimeType": "text/plain",
    }
    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id,name",
    ).execute()
    return uploaded


def main():
    # Authenticate with Google Drive using service account credentials
    creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(
        creds_json,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    drive_service = build("drive", "v3", credentials=creds)
    folder_id = os.environ["DRIVE_FOLDER_ID"]

    videos = get_recent_videos(limit=10)
    print(f"Found {len(videos)} recent videos on the channel")

    seen = load_seen_videos()
    new_count = 0

    for video in videos:
        vid_id = video["id"]
        if vid_id in seen:
            print(f"  Skipping (already processed): {video['title'][:60]}")
            continue

        print(f"\n  New video found: {video['title']}")
        transcript = get_transcript(vid_id)

        if transcript:
            # Build a clean filename
            safe_title = (
                "".join(c for c in video["title"] if c.isalnum() or c in " -_")
                .strip()[:80]
            )
            filename = f"{video['date']}_{safe_title}.txt"

            # Add a header with metadata before the transcript
            header = (
                f"Title:   {video['title']}\n"
                f"Video ID: {vid_id}\n"
                f"Date:    {video['date']}\n"
                f"URL:     https://www.youtube.com/watch?v={vid_id}\n"
                f"\n{'=' * 60}\n\n"
            )
            full_content = header + transcript

            result = upload_to_drive(filename, full_content, folder_id, drive_service)
            print(f"  Uploaded to Drive: {result['name']}")
            new_count += 1
        else:
            print(f"  No transcript available for this video, skipping")

        # Mark as seen regardless (so we don't retry videos with no transcript)
        seen.add(vid_id)

    save_seen_videos(seen)
    print(f"\nDone. {new_count} new transcript(s) uploaded.")


if __name__ == "__main__":
    main()
