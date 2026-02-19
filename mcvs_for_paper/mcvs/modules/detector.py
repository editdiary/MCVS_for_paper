# modules/detector.py

import numpy as np
from ultralytics import YOLO
from typing import List, Tuple
from mcvs.core.data_types import YoloResult

class YoloDetector:
    """
    YOLOv11 모델을 로드하여 객체 탐지(Detection) 및 추적(Tracking)을 수행합니다.
    TensorRT 엔진(.engine) 사용을 권장합니다.
    """
    def __init__(self, weights_path: str, conf_threshold: float = 0.6):
        self.conf = conf_threshold
        self.model = None
        
        # [Step 1] Primary Load: 지정된 경로(주로 .engine) 시도
        print(f"[Detector] YOLO 모델 로딩 시도: {weights_path}")
        
        # [수정] 더미 데이터 생성 (워밍업용)
        dummy_img = np.zeros((640, 640, 3), dtype=np.uint8)
        
        try:
            # 1차 시도: 설정된 경로(.engine) 로드
            self.model = YOLO(weights_path, task='detect')
            
            # 로드 직후 강제로 한 번 실행해봄 (여기서 에러가 나야 try-except가 잡음)
            print("[Detector] 엔진 무결성 검사 중...")
            self.model(dummy_img, verbose=False) 
            
            print(f"[Detector] ✅ 메인 모델 로드 성공 (.engine)")
        except Exception as e:
            print(f"[Detector] ⚠️ 엔진 로드/검증 실패 ({e}). ONNX로 전환합니다.")
            self.model = None # 초기화 실패로 간주
            
            # 2차 시도: 확장자만 바꿔서 ONNX 로드 (파일이 있다고 가정)
            onnx_path = weights_path.replace('.engine', '.onnx')
            try:
                self.model = YOLO(onnx_path, task='detect')
                
                # ONNX도 잘 되는지 테스트
                self.model(dummy_img, verbose=False)
                
                print(f"[Detector] ✅ 백업 모델 로드 성공 (.onnx)")
            except Exception as e2:
                print(f"[Detector] ❌ 치명적 오류: ONNX 로드도 실패했습니다. ({e2})")
                raise e2

    def track(self, image: np.ndarray) -> List[YoloResult]:
        """
        ByteTrack을 사용하여 객체 추적을 수행합니다. (ID 유지)
        연속된 프레임에서 호출해야 ID가 끊기지 않습니다.
        """
        results = []
        if self.model is None or image is None: return results

        # persist=True: 이전 프레임의 추적 상태 유지
        preds = self.model.track(
            image,
            persist=True,
            conf=self.conf,
            tracker="bytetrack.yaml",
            verbose=False
        )
        
        if not preds or not preds[0].boxes: return results
        
        # 결과 파싱
        pred = preds[0]
        boxes = pred.boxes.xyxy.cpu().numpy().astype(int)
        confs = pred.boxes.conf.cpu().numpy()
        clss = pred.boxes.cls.cpu().numpy().astype(int)
        
        # ID가 없는 경우(첫 프레임 등) 처리
        ids = pred.boxes.id.cpu().numpy().astype(int) if pred.boxes.id is not None else [None] * len(boxes)

        for box, conf, cls_id, track_id in zip(boxes, confs, clss, ids):
            results.append(YoloResult(
                label=pred.names[cls_id],
                conf=float(conf),
                bbox=tuple(box),
                track_id=str(track_id) if track_id is not None else None
            ))
            
        return results
    
    
    def detect(self, image: np.ndarray) -> List[YoloResult]:
        """
        단순 객체 탐지를 수행합니다. (ID 없음)
        워밍업이나 추적이 필요 없는 단발성 분석에 사용됩니다.
        """
        results = []
        if self.model is None or image is None:
            return results

        preds = self.model(image, conf=self.conf, verbose=False)
        
        if not preds or not preds[0].boxes:
            return results

        pred = preds[0]
        for box in pred.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
            results.append(YoloResult(
                label=pred.names[int(box.cls[0])],
                conf=float(box.conf[0]),
                bbox=(x1, y1, x2, y2),
                track_id=None
            ))
            
        return results