import boto3
import os
import time
import queue
import threading

# No credentials here on purpose. boto3 finds them automatically from:
# env vars -> ~/.aws/credentials -> IAM role (if running on AWS compute)
s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
BUCKET_NAME = os.environ["S3_BUCKET_NAME"]  # crash loudly if not set

upload_queue = queue.Queue()


def _worker():
    """Runs forever in the background, uploading whatever shows up on the queue."""
    while True:
        filepath = upload_queue.get()  # blocks here until something is queued
        try:
            filename = os.path.basename(filepath)
            key = f"snapshots/{filename}"
            s3.upload_file(filepath, BUCKET_NAME, key)
            print(f"Uploaded {filename} -> s3://{BUCKET_NAME}/{key}")
            os.remove(filepath)  # don't keep local copies once safely in S3
        except Exception as e:
            print(f"Upload failed for {filepath}: {e}")
            time.sleep(2)  # avoid hammering the network if it's actually down
            upload_queue.put(filepath)  # retry later
        finally:
            upload_queue.task_done()


def start_upload_worker():
    """Call this once at startup. daemon=True means it won't block program exit."""
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread


def enqueue_upload(filepath):
    """Call this from capture.py right after saving a snapshot."""
    upload_queue.put(filepath)