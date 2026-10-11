import cv2
import time
import os
from pathlib import Path
from uploader import start_upload_worker, enqueue_upload
from dotenv import load_dotenv

load_dotenv()
SNAPSHOT_DIR = "snapshots"
SNAPSHOT_COOLDOWN = 3          # min seconds between snapshots inside one event
FOLLOWUP_DELAY = 0.3           # second shot right after the first, to dodge blur
MIN_CONTOUR_AREA = 900
EVENT_QUIET_PERIOD = 30        # seconds with NO motion before a new event (= new email) can start
MAX_SNAPSHOTS_PER_EVENT = 20   # safety cap so a long event can't flood S3


def clear_snapshots():
    """Delete every .jpg left in the snapshots folder from earlier runs."""
    folder = Path(SNAPSHOT_DIR)
    if not folder.exists():
        return
    removed = 0
    for p in folder.glob("*.jpg"):
        p.unlink()
        removed += 1
    print(f"Cleared {removed} old snapshot(s)")


def save_snapshot(frame, event_id, idx):
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    filename = f"{SNAPSHOT_DIR}/{event_id}_{idx}.jpg"
    cv2.imwrite(filename, frame)
    print("Saved snapshot:", filename)
    enqueue_upload(filename)  # hand off to background thread, don't block here
    return filename


def new_event_id(now):
    return time.strftime("%Y%m%dT%H%M%S", time.localtime(now)) \
        + f"-{int(now * 1000) % 1000:03d}"


def motionDetection():
    clear_snapshots()      # must run BEFORE the worker starts, or it re-queues the old files
    start_upload_worker()  # background thread starts once, keeps running

    cap = cv2.VideoCapture(0)  # default 640x480

    ret1, frame1 = cap.read()
    ret2, frame2 = cap.read()
    if not (ret1 and ret2):
        print("Could not read from camera")
        cap.release()
        return

    event_id = None
    event_idx = 0              # next snapshot index within the current event
    last_motion_time = 0
    last_snapshot_time = 0
    pending = None             # (time_to_fire, event_id, idx)

    while cap.isOpened():
        diff = cv2.absdiff(frame1, frame2)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(diff_gray, (5, 5), 0)
        _, thresh = cv2.threshold(blur, 20, 255, cv2.THRESH_BINARY)
        dilated = cv2.dilate(thresh, None, iterations=3)
        contours, _ = cv2.findContours(
            dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        display_frame = frame2.copy()

        motion = False
        for contour in contours:
            if cv2.contourArea(contour) < MIN_CONTOUR_AREA:
                continue
            motion = True
            (x, y, w, h) = cv2.boundingRect(contour)
            cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        now = time.time()

        if motion:
            # A new event starts only after EVENT_QUIET_PERIOD seconds without motion.
            # Only the first snapshot of an event is named *_0.jpg, and only
            # *_0.jpg uploads trigger the alert email.
            if event_id is None or (now - last_motion_time) > EVENT_QUIET_PERIOD:
                event_id = new_event_id(now)
                event_idx = 0
            last_motion_time = now

            if (now - last_snapshot_time) > SNAPSHOT_COOLDOWN \
                    and event_idx < MAX_SNAPSHOTS_PER_EVENT:
                if event_idx == 0:
                    save_snapshot(frame2, event_id, 0)
                    pending = (now + FOLLOWUP_DELAY, event_id, 1)
                    event_idx = 2  # index 1 is reserved for the follow-up
                else:
                    save_snapshot(frame2, event_id, event_idx)
                    event_idx += 1
                last_snapshot_time = now

        if pending and now >= pending[0]:
            save_snapshot(frame2, pending[1], pending[2])
            pending = None

        cv2.imshow("Video", display_frame)

        frame1 = frame2
        ret, frame2 = cap.read()
        if not ret:  # camera dropped a frame or disconnected
            break

        if cv2.waitKey(1) == 27:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    motionDetection()