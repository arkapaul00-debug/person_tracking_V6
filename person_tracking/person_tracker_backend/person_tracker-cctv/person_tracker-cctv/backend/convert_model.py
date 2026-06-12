import os
from ultralytics import YOLO

# Define paths relative to your project root
model_path = '/home/temp_user/arjit/backend/forensics/ai_core/weights/yolov10x.pt'

if not os.path.exists(model_path):
    print(f"ERROR: Could not find model at {model_path}")
else:
    print("Initializing YOLOv10x for TensorRT Export...")
    model = YOLO(model_path)
    
    # Exporting... this will take 3-5 minutes on an A5000
    # workspace=8 defines 8GB of GPU memory for the optimization process
    model.export(format='engine', device=0, half=True, workspace=8)
    
    print("SUCCESS: your model is now at backend/forensics/ai_core/weights/yolov10x.engine")
