import cv2
import argparse
import numpy as np
import os
from PIL import Image

def load_sam3(weights_path, device):
    from ultralytics import SAM
    try:
        from ultralytics.models.sam import SAM3SemanticPredictor
    except ImportError:
        SAM3SemanticPredictor = None

    overrides = dict(
        conf=0.25,
        task="segment",
        mode="predict",
        model=weights_path,
        device=device
    )
    
    print(f"Loading SAM 3.1 model from {weights_path}...")
    if SAM3SemanticPredictor:
        predictor = SAM3SemanticPredictor(overrides=overrides)
    else:
        print("Warning: SAM3SemanticPredictor not found. Trying standard SAM interface.")
        predictor = SAM(weights_path)
    return predictor

def load_falcon(device):
    from transformers import AutoModelForCausalLM
    import torch
    model = AutoModelForCausalLM.from_pretrained(
        "tiiuae/falcon-perception", 
        trust_remote_code=True, 
        device_map=device,
        torch_dtype=torch.float16
    )
    return model

def main(model_choice="sam", weights_path="sam3.1_multiplex.pt", prompt="person", device="0", debug=False):
    if debug:
        os.environ['CUDA_LAUNCH_BLOCKING'] = '1'
        print("Debug mode enabled: CUDA_LAUNCH_BLOCKING=1")
        
    # 1. Initialize the chosen model
    if model_choice.lower() == "sam":
        predictor = load_sam3(weights_path, device)
        falcon_model = None
    elif model_choice.lower() == "falcon":
        falcon_model = load_falcon(f"cuda:{device}" if device.isnumeric() else device)
        predictor = None
    else:
        print("Invalid model choice. Use 'sam' or 'falcon'.")
        return

    # 2. Open the webcam
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    print(f"Starting webcam feed. Using {model_choice.upper()} mode. Segmenting for: '{prompt}'")
    print("Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # SAM 3.1 max stride is 14; pad/resize explicitly to avoid CUDA indexing bugs
        # out of bounds errors in device asserts. Using 32 for better alignment.
        h, w = frame.shape[:2]
        new_h = (h // 32) * 32
        new_w = (w // 32) * 32
        if h != new_h or w != new_w:
            frame = cv2.resize(frame, (new_w, new_h))

        # 3. Perform prediction
        if model_choice.lower() == "sam":
            try:
                from ultralytics.models.sam import SAM3SemanticPredictor
            except ImportError:
                SAM3SemanticPredictor = None
                
            if SAM3SemanticPredictor and isinstance(predictor, SAM3SemanticPredictor):
                predictor.set_image(frame)
                # Wrap prompt in a list as multiplexed SAM 3.1 expects a list of query strings
                results = predictor(text=[prompt])
            else:
                results = predictor(frame)
                
            if results:
                annotated_frame = results[0].plot()
            else:
                annotated_frame = frame
                
        elif model_choice.lower() == "falcon":
            # Falcon uses PIL images
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb_frame)
            
            try:
                # The model generates a list of detected instances (list[list[dict]])
                # We take the first element as we pass a single image.
                # We disable compile by default here to avoid the 5-minute freeze on the first frame.
                preds_list = falcon_model.generate(pil_image, prompt, compile=True)
                preds = preds_list[0] if preds_list else []
                
                annotated_frame = frame.copy()
                
                # Check for instances
                if preds:
                    try:
                        from pycocotools import mask as mask_utils
                        
                        for p in preds:
                            # 1. Decode the mask from RLE
                            rle = p.get("mask_rle")
                            if not rle:
                                continue
                                
                            m_data = {"size": rle["size"], "counts": rle["counts"].encode("utf-8")}
                            mask = mask_utils.decode(m_data).astype(bool)
                            
                            # 2. Draw mask on frame (using a random color for each instance)
                            color = np.random.randint(0, 255, (3,)).tolist()
                            
                            # Create a tinted overlay for the mask
                            mask_img = np.zeros_like(annotated_frame)
                            mask_img[mask] = color
                            
                            # Blend with original frame (0.5 alpha)
                            annotated_frame = cv2.addWeighted(annotated_frame, 1.0, mask_img, 0.5, 0)
                            
                            # 3. Draw a dot at the center (xy)
                            if "xy" in p:
                                cx, cy = int(p["xy"][0]), int(p["xy"][1])
                                cv2.circle(annotated_frame, (cx, cy), 5, (255, 255, 255), -1)
                                cv2.putText(annotated_frame, prompt, (cx + 5, cy + 5), 
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                    except ImportError:
                        cv2.putText(annotated_frame, "Error: pycocotools not installed", (10, 30), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                        print("Error: pycocotools is required to decode Falcon masks.")
                else:
                    cv2.putText(annotated_frame, f"No '{prompt}' detected", (10, 30), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            except Exception as e:
                print("Error during Falcon inference:", e)
                annotated_frame = frame
                
        # 4. Display results
        cv2.imshow("Webcam Segmentation Test", annotated_frame)

        # 5. Break on 'q'
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Webcam Test Script (SAM 3.1 & Falcon Perception)")
    parser.add_argument("--model", type=str, choices=["sam", "falcon"], default="sam", help="Choose which model to use: 'sam' or 'falcon'")
    parser.add_argument("--weights", type=str, default="sam3.1_multiplex.pt", help="Path to sam3.1_multiplex.pt weights (SAM only)")
    parser.add_argument("--prompt", type=str, default="person", help="Text prompt for segmentation")
    parser.add_argument("--device", type=str, default="0", help="Device to run on (e.g., '0' for GPU, 'cpu')")
    parser.add_argument("--debug", action="store_true", help="Enable CUDA synchronous debugging")
    
    args = parser.parse_args()
    main(args.model, args.weights, args.prompt, args.device, args.debug)
