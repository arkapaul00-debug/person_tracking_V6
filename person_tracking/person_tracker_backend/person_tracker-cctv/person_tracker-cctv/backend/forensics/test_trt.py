from ultralytics import YOLO
import cv2
import numpy as np
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TRT_Test")

def test_engine():
    model_path = "/home/temp_user/arjit/backend/forensics/ai_core/weights/yolov10x.engine"
    logger.info(f"Loading model: {model_path}")
    
    try:
        model = YOLO(model_path, task='detect')
        logger.info("Model loaded successfully.")
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        return

    # Create dummy image
    img = np.zeros((640, 640, 3), dtype=np.uint8)
    cv2.rectangle(img, (100, 100), (200, 200), (255, 255, 255), -1) # White box
    
    logger.info("Running inference...")
    try:
        # Run with SAME parameters as in ai_wrapper
        results = model([img], conf=0.1, verbose=True) # Lower conf to see ANY output
        
        logger.info(f"Results type: {type(results)}")
        if results:
            r = results[0]
            logger.info(f"Boxes: {r.boxes}")
            if r.boxes:
                logger.info(f"XYXY: {r.boxes.xyxy}")
                logger.info(f"Conf: {r.boxes.conf}")
                logger.info(f"Cls: {r.boxes.cls}")
            else:
                logger.info("No boxes detected.")
    except Exception as e:
        logger.error(f"Inference failed: {e}")

if __name__ == "__main__":
    test_engine()
