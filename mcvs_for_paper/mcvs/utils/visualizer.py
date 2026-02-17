# utils/visualizer.py

import cv2
import numpy as np
from typing import List, Optional
from mcvs.core.data_types import YoloResult

class Visualizer:
    """
    OpenCV를 사용하여 이미지 위에 원본 이미지와 YOLO 탐지 결과(BBox, Label)만 
    단순하게 그리는 클래스.
    """
    # 최소한의 색상 정의 (BGR)
    COLOR_RED   = (0, 0, 255)    # BBox 색상
    COLOR_BLACK = (0, 0, 0)      # 텍스트 색상
    
    def __init__(self):
        self.font = cv2.FONT_HERSHEY_SIMPLEX

    def draw_yolo(self, image: np.ndarray, yolo_results: List[YoloResult]) -> Optional[np.ndarray]:
        """
        YOLO 탐지 결과(바운딩 박스, 라벨, 신뢰도)만 단순하게 그립니다.
        """
        if image is None: return None
        out = image.copy()

        # 탐지된 모든 객체에 대해 바운딩 박스와 라벨 표시
        for res in yolo_results:
            x1, y1, x2, y2 = res.bbox
            
            # 1. Bounding Box 그리기 (일괄 빨강색)
            cv2.rectangle(out, (x1, y1), (x2, y2), self.COLOR_RED, 2)

            # 2. Label 텍스트 구성
            id_str = f"ID:{res.track_id} " if res.track_id else ""
            conf_str = f"{res.conf:.2f}"
            label = f"{id_str}{res.label} {conf_str}"
            
            # 3. Label 텍스트 배경 및 글씨 그리기 (가독성 확보)
            (tw, th), _ = cv2.getTextSize(label, self.font, 0.5, 1)
            cv2.rectangle(out, (x1, y1 - 20), (x1 + tw, y1), self.COLOR_RED, -1)
            cv2.putText(out, label, (x1, y1 - 5), self.font, 0.5, self.COLOR_BLACK, 1)
        
        return out