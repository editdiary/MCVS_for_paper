from ultralytics import YOLO
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
weights_path = os.path.join(BASE_DIR, "weights", "best.pt")
model = YOLO(weights_path)

# Export the model to TensorRT
model.export(format="engine", half=True, dynamic=True, device=0)
# - dynamic=True: 배치 사이즈가 변해도 처리가 가능한 엔진을 만듦
#                 보통 별도의 옵션 없이 export하면 batch=1로 고정된 엔진이 생성
#                 따라서 다른 배치의 이미지가 들어오면 에러가 남