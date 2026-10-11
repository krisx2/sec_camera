import os
import queue
import threading
import time
from pathlib import Path

import boto3

MAX_ATTEMPTS = 5
_queue = queue.Queue()
_s3 = None
_bucket = None


def start_upload_worker(snapshot_dir="snapshots"):
    global _s3, _bucket
    _bucket = os.environ["S3_BUCKET_NAME"]  
    _s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))

    # re-queue anything left over from a crash or a failed run
    for p in sorted(Path(snapshot_dir).glob("*.jpg")):
        enqueue_upload(str(p))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


def enqueue_upload(filepath, attempt=0):
    _queue.put((filepath, attempt))


def _worker():
    while True:
        filepath, attempt = _queue.get()
        try:
            key = f"snapshots/{os.path.basename(filepath)}"
            _s3.upload_file(filepath, _bucket, key,
                            ExtraArgs={"ContentType": "image/jpeg"})
            print(f"Uploaded {filepath} -> s3://{_bucket}/{key}")
            os.remove(filepath)
        except FileNotFoundError:
            print(f"Skipping missing file {filepath}")
        except Exception as e:
            if attempt + 1 < MAX_ATTEMPTS:
                print(f"Upload failed ({e}), retry {attempt + 1}")
                time.sleep(min(2 ** attempt, 30))  # exponential backoff
                enqueue_upload(filepath, attempt + 1)
            else:
                print(f"Giving up on {filepath}; it stays on disk for next startup")
        finally:
            _queue.task_done()