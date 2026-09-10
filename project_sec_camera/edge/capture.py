import cv2
import time
import os
# from uploader import start_upload_worker, enqueue_upload


def save_snapshot(frame):
    os.makedirs("snapshots", exist_ok=True)
    filename = f"snapshots/snapshot_{int(time.time() * 1000)}.jpg"
    cv2.imwrite(filename, frame)
    print("Saved snapshot:", filename)
    #enqueue_upload(filename)  # hand off to background thread, don't block here


def motionDetection():
    #start_upload_worker()  # background thread starts once, keeps running

    cap = cv2.VideoCapture(0)  # default 640x480

    ret, frame1 = cap.read()
    ret, frame2 = cap.read()

    last_snapshot_time = 0
    SNAPSHOT_COOLDOWN = 3
    pending_snapshot_time = None

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
            if cv2.contourArea(contour) < 900:
                continue
            motion = True
            (x, y, w, h) = cv2.boundingRect(contour)
            cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        now = time.time()

        if motion and (now - last_snapshot_time) > SNAPSHOT_COOLDOWN:
            save_snapshot(frame2)
            last_snapshot_time = now
            pending_snapshot_time = now + 0.5

        if pending_snapshot_time and now >= pending_snapshot_time:
            save_snapshot(frame2)
            pending_snapshot_time = None

        cv2.imshow("Video", display_frame)

        frame1 = frame2
        ret, frame2 = cap.read()

        if cv2.waitKey(1) == 27:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    motionDetection()