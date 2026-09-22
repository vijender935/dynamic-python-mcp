"""
Google Drive (AI_Input folder) -> Cloudflare R2 upload
Uses Modal secret `google-drive`:
  - GOOGLE_SERVICE_ACCOUNT_JSON
  - INPUT_FOLDER_ID
R2 credentials are hardcoded as requested.
"""

import os
import io
import json
import mimetypes

import boto3
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ============================================================
# R2 (hardcoded)
# ============================================================
R2_ACCOUNT_ID = "bf2ae6f6ea76029634f47b01a5897db8"
R2_ACCESS_KEY_ID = "bbf944fc194b1b85746e64c28a6cd1dd"
R2_SECRET_ACCESS_KEY = "963ef4c622e95c876e4c3753248bd320d599a7c22ee017b7e56e61cd3816865a"
R2_BUCKET_NAME = "ai-images"
R2_PREFIX = ""  # empty = same relative key

REUPLOAD_WRONG_SIZE = True

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".bmp", ".tif", ".tiff", ".avif",
}

# ============================================================
# Google Drive from Modal secret
# ============================================================
def get_drive_service():
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON missing from env (secret google-drive)")

    info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_image_files(service, folder_id):
    """List image files in folder (non-recursive for simplicity; can extend)."""
    files = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"

    while True:
        resp = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, size)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for f in resp.get("files", []):
            name = f.get("name", "")
            ext = os.path.splitext(name)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                files.append(f)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def download_file(service, file_id) -> bytes:
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# ============================================================
# R2 helpers
# ============================================================
def get_s3():
    endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def get_r2_size(s3, key):
    try:
        return s3.head_object(Bucket=R2_BUCKET_NAME, Key=key)["ContentLength"]
    except Exception:
        return None


def content_type_for(name):
    mime, _ = mimetypes.guess_type(name)
    return mime or "application/octet-stream"


# ============================================================
# Main
# ============================================================
def main():
    folder_id = os.environ.get("INPUT_FOLDER_ID")
    if not folder_id:
        raise RuntimeError("INPUT_FOLDER_ID missing from env (secret google-drive)")

    print("=" * 70)
    print("Drive -> R2 sync")
    print("=" * 70)
    print(f"INPUT_FOLDER_ID: {folder_id}")
    print(f"R2 bucket     : {R2_BUCKET_NAME}")

    drive = get_drive_service()
    s3 = get_s3()

    s3.head_bucket(Bucket=R2_BUCKET_NAME)
    print("✅ R2 connection OK")

    files = list_image_files(drive, folder_id)
    total = len(files)
    print(f"🖼️ Images found: {total}")
    print("=" * 70)

    uploaded = fixed = skipped = failed = 0

    for i, f in enumerate(files, 1):
        name = f["name"]
        file_id = f["id"]
        r2_key = f"{R2_PREFIX.strip('/')}/{name}".lstrip("/") if R2_PREFIX.strip("/") else name

        print(f"\n[{i}/{total}] {name}")

        try:
            data = download_file(drive, file_id)
            local_size = len(data)
            if local_size == 0:
                print("❌ EMPTY FILE")
                failed += 1
                continue

            existing = get_r2_size(s3, r2_key)
            if existing is not None and existing == local_size:
                print(f"⏭️ SKIP | {local_size:,} bytes | {r2_key}")
                skipped += 1
                continue

            if existing is not None and existing != local_size:
                print(f"⚠️ WRONG SIZE | Drive {local_size:,} vs R2 {existing:,}")
                if not REUPLOAD_WRONG_SIZE:
                    failed += 1
                    continue
                print("   🔄 Re-uploading...")

            s3.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=r2_key,
                Body=data,
                ContentType=content_type_for(name),
            )

            r2_size = get_r2_size(s3, r2_key)
            if r2_size != local_size:
                print(f"❌ SIZE MISMATCH after upload: {r2_size} vs {local_size}")
                failed += 1
                continue

            if existing is None:
                uploaded += 1
                print(f"✅ UPLOADED + VERIFIED | {local_size:,} bytes | {r2_key}")
            else:
                fixed += 1
                print(f"✅ FIXED + VERIFIED | {local_size:,} bytes | {r2_key}")

        except Exception as e:
            print(f"❌ FAILED: {e}")
            failed += 1

    print()
    print("=" * 70)
    print("🎯 SYNC COMPLETE")
    print(f"🖼️ Total    : {total}")
    print(f"🆕 Uploaded : {uploaded}")
    print(f"🔄 Fixed    : {fixed}")
    print(f"⏭️ Skipped  : {skipped}")
    print(f"❌ Failed   : {failed}")
    print("=" * 70)


if __name__ == "__main__":
    main()
