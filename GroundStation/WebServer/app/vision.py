import threading
import time
import logging
import traceback
import cv2
import numpy as np
from pydantic import BaseModel
import os
from pathlib import Path

log = logging.getLogger(__name__)

# Resolve model path securely
BASE_DIR = Path(__file__).resolve().parent.parent.parent
MODEL_PATH = BASE_DIR / "models" / "sam3.1_multiplex.pt"

class VisionDaemon:
    def __init__(self, registry, device: str = "0"):
        self.registry = registry
        self.device = device
        self.master_prompt = ""
        self._lock = threading.Lock()

        self.running = False
        self._thread = None

        # Load weights lazily inside the thread to avoid blocking FastAPI boot
        self.predictor = None
        
    def start(self):
        if self.running: return
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, name="VisionSAMLoop", daemon=True)
        self._thread.start()
        log.info("VisionDaemon: Background SAM multiplex thread started.")
        
    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=3)
        log.info("VisionDaemon: Shut down.")
        
    def set_prompt(self, prompt: str):
        with self._lock:
            self.master_prompt = prompt.strip()
            if self.master_prompt:
                log.info(f"VisionDaemon: Master tracking prompt set to: '{self.master_prompt}'")
            else:
                log.info("VisionDaemon: Master tracking prompt cleared.")

    def _run_loop(self):
        # 1. Initialize PyTorch / SAM Model persistently in VRAM
        try:
            from ultralytics.models.sam import SAM3SemanticPredictor
            from ultralytics.utils import LOGGER
            import logging
            
            # Silence Ultralytics spam
            LOGGER.setLevel(logging.ERROR)
            
            # Explicitly make sure the directory exists just in case
            if not MODEL_PATH.parent.exists():
                MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
                
            log.info(f"VisionDaemon: Initializing SAM 3.1 on device={self.device} from {MODEL_PATH}")
            overrides = dict(
                conf=0.25,
                task="segment",
                mode="predict",
                model=str(MODEL_PATH),
                device=self.device,
                verbose=False
            )
            self.predictor = SAM3SemanticPredictor(overrides=overrides)
            log.info("VisionDaemon: SAM 3.1 Model successfully hoisted into VRAM.")
        except Exception as e:
            log.error(f"VisionDaemon: Failed to load SAM 3.1 model. {e}")
            log.debug(traceback.format_exc())
            # We don't crash the server, just stop the vision loop if ML environment lacks weights.
            self.running = False
            return

        # 2. Infinite Multiplexing Loop
        while self.running:
            with self._lock:
                current_prompt = self.master_prompt
                
            if not current_prompt:
                time.sleep(1.0)
                continue
                
            # Grab atomic snapshot of active drones
            drones = self.registry.list()
            
            if len(drones) == 0:
                time.sleep(0.5)
                continue
                
            # Iterate and feed frames securely
            for drone_data in drones:
                drone_id = drone_data["id"]
                
                # Fetch directly from physical registry to avoid stale snapshot bytes
                drone_raw = self.registry.get(drone_id)
                if not drone_raw: continue
                
                frame_bytes = drone_raw.get("latest_frame")
                if not frame_bytes: continue
                
                try:
                    # Parse bytes to OpenCV image
                    np_arr = np.frombuffer(frame_bytes, np.uint8)
                    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    if frame is None: continue
                    
                    # Prevent stride alignment crashes in SAM 14-max bounds
                    # Force resize to nearest 32
                    h, w = frame.shape[:2]
                    new_h = (h // 32) * 32
                    new_w = (w // 32) * 32
                    if h != new_h or w != new_w:
                        frame = cv2.resize(frame, (new_w, new_h))
                        
                    # Execute heavy CUDA payload
                    self.predictor.set_image(frame)
                    results = self.predictor(text=[current_prompt])
                    
                    # Determine detection trigger accurately
                    if results and len(results) > 0:
                        # Depending on ultralytics version, it might be in `masks` or `boxes`
                        r = results[0]
                        if (hasattr(r, 'masks') and r.masks is not None and len(r.masks) > 0) or \
                           (hasattr(r, 'boxes') and r.boxes is not None and len(r.boxes) > 0):
                            print(f"\n[SAM THREAT ALERT] POSITIVE IDENTIFICATION -> '{current_prompt}' identified physically via {drone_id}!\n")

                            # Compose an annotated JPEG: the BGR frame with SAM mask + boxes drawn on top.
                            jpeg_bytes = None
                            try:
                                annotated = r.plot() if hasattr(r, 'plot') else frame
                                ok, buf = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                                if ok:
                                    jpeg_bytes = buf.tobytes()
                            except Exception as enc_exc:
                                log.warning(f"VisionDaemon: failed to encode annotated frame for {drone_id}: {enc_exc}")

                            # Snapshot GPS at detection time; fall back through telemetry → homeLocation.
                            loc = (drone_raw.get("telemetry") or {}).get("location") or {}
                            lat = loc.get("latitude", loc.get("lat"))
                            lng = loc.get("longitude", loc.get("lon"))
                            if lat is None or lng is None:
                                home = drone_raw.get("homeLocation") or {}
                                lat = home.get("latitude", home.get("lat", 0.0))
                                lng = home.get("longitude", home.get("lon", 0.0))

                            self.registry.record_detection(
                                drone_id=drone_id,
                                drone_label=drone_raw.get("label", drone_id),
                                prompt=current_prompt,
                                ts_ms=int(time.time() * 1000),
                                lat=float(lat),
                                lng=float(lng),
                                jpeg_bytes=jpeg_bytes,
                            )
                            # Add a brief pause to stop console spamming during lock
                            time.sleep(1.0)
                            
                except Exception as e:
                    # Drop the frame but don't kill the multiplexer
                    log.error(f"VisionDaemon: Inference throw on drone {drone_id}: {e}")
            
            # Spin interval between round robin
            time.sleep(0.1)
