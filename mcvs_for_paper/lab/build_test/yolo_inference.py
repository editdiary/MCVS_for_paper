import cv2
from ultralytics import YOLO
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load a model
#pretrain_weights_path = os.path.join(BASE_DIR, "weights", "best.pt")
#model = YOLO(pretrain_weights_path)  # load a custom model
pretrain_weights_path = os.path.join(BASE_DIR, "weights", "best.engine")
model = YOLO(pretrain_weights_path)

sample_image = os.path.join(BASE_DIR, "inference_test_img.jpg")

im = cv2.imread(sample_image)
results = model.predict(source=im, save=False)

for result in results:
    boxes = result.boxes
    result.save(filename="./temp.jpg")

#results = model.predict(source=[sample_image1, sample_image2], save=True, save_txt=True)