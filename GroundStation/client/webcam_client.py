"""
Simple video client. Captures webcam frames, JPEG-encodes them,
sends to the server over TCP.

Protocol (per frame):
    [4 bytes big-endian length N] [N bytes JPEG data]

Requirements: pip install opencv-python numpy

Usage:
    # On the same machine as the server:
    python client/webcam_client.py

    # On a different machine (point at server's IP):
    python client/webcam_client.py 192.168.1.42

Press 'q' in the preview window to quit.
"""

import socket
import struct
import sys

import cv2

DEFAULT_HOST = "127.0.0.1"
PORT = 5000
JPEG_QUALITY = 70  # 1-100; lower = smaller/faster, blockier


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # CAP_DSHOW = faster open on Windows
    if not cap.isOpened():
        sys.exit("[client] ERROR: could not open webcam (index 0).")

    print(f"[client] Connecting to {host}:{PORT} ...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, PORT))
    print("[client] Connected. Streaming. Press 'q' in the preview to quit.")

    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[client] Webcam read failed.")
                break

            ok, encoded = cv2.imencode(".jpg", frame, encode_params)
            if not ok:
                continue

            payload = encoded.tobytes()
            sock.sendall(struct.pack(">I", len(payload)) + payload)

            cv2.imshow("Local Preview", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    except (BrokenPipeError, ConnectionResetError):
        print("[client] Server closed the connection.")
    finally:
        cap.release()
        sock.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
