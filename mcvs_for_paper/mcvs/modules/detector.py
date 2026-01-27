# modules/detector.py

import cv2
import numpy as np
from ultralytics import YOLO
from typing import List, Tuple
from core.data_types import YoloResult

class HarvestAnalyzer:
    """
    [Logic] 탐지된 객체가 '수확 가능한 상태'인지 판단하는 분석기
    Vision System 내부에서 Pixel Access가 필요하므로 여기에 위치함.
    """
    def __init__(self, config: dict):
        self.cfg = config 
        # config 예시: {'harvest_zone': [0.2, 0.1, 0.8, 0.9], 'min_area': 0.05, 'ripeness_threshold': 0.6}

    def analyze(self, image: np.ndarray, bbox: Tuple[int, int, int, int]) -> dict:
        """
        객체의 BBox와 설정을 비교하여 수확 적합성 판단 (XY축 모두 고려)
        Return: {'is_candidate': bool, 'is_trigger': bool, 'reason': str}
        """
        x1, y1, x2, y2 = bbox
        h_img, w_img, _ = image.shape
        
        # 중심점(Ratio) 및 면적 계산
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0 # [New] Y중심

        cx_ratio = cx / w_img
        cy_ratio = cy / h_img # [New] Y비율

        area = (x2 - x1) * (y2 - y1)
        area_ratio = area / (w_img * h_img)
        
        # [NEW] 결과 딕셔너리 확장 (Blackboard Logic 필드 대응)
        result = {
            'is_candidate': False,
            'is_trigger': False,
            'in_harvest_zone': False,
            'reason': "Ready"
        }

        # 1. Harvest Zone Check (XY축 검사)
        hx_min = self.cfg.get('zone_x_min', 0.0)
        hx_max = self.cfg.get('zone_x_max', 1.0)
        hy_min = self.cfg.get('zone_y_min', 0.0) # [New]
        hy_max = self.cfg.get('zone_y_max', 1.0) # [New]

        # [Logic] XY 모두 만족해야 Zone In
        is_x_ok = (hx_min <= cx_ratio <= hx_max)
        is_y_ok = (hy_min <= cy_ratio <= hy_max)

        # Zone 안에 있는지 먼저 체크하여 플래그 설정
        if is_x_ok and is_y_ok:
            result['in_harvest_zone'] = True
        else:
            result['reason'] = "Out of Harvest Zone"
            return result # Zone 밖이면 바로 리턴 (Candidate 탈락)
        
        # 2. Size Check
        if area_ratio < self.cfg.get('min_area_ratio', 0.005):
            result['reason'] = "Too Small"
            return result
        
        # [통과] Zone 안에 있고 크기도 적절함 -> 수확 후보 인정
        result['is_candidate'] = True

        # 3. Trigger Zone Check (XY축 정밀 검사)
        tx_min = self.cfg.get('trigger_x_min', 0.45)
        tx_max = self.cfg.get('trigger_x_max', 0.55)
        ty_min = self.cfg.get('trigger_y_min', 0.0) # [New]
        ty_max = self.cfg.get('trigger_y_max', 1.0) # [New]

        is_tx_ok = (tx_min <= cx_ratio <= tx_max)
        is_ty_ok = (ty_min <= cy_ratio <= ty_max)
        
        if is_tx_ok and is_ty_ok:
            result['is_trigger'] = True
            result['reason'] = "Triggered!"
        
        return result

    # [TODO] 추후에는 색상 검증도 도입할까 고민 중
    # def _calculate_yellowness(self, roi_bgr: np.ndarray) -> float:
    #     """HSV 색공간을 이용해 노란색 픽셀 비율 계산"""
    #     hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    #     # 노란색 범위 (H: 20~35 정도가 참외색에 가까움, 튜닝 필요)
    #     lower_yellow = np.array([15, 100, 100])
    #     upper_yellow = np.array([35, 255, 255])
        
    #     mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
    #     yellow_pixels = cv2.countNonZero(mask)
    #     total_pixels = roi_bgr.shape[0] * roi_bgr.shape[1]
        
    #     return yellow_pixels / total_pixels if total_pixels > 0 else 0.0

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
            
            # [핵심 수정] 로드 직후 강제로 한 번 실행해봄 (여기서 에러가 나야 try-except가 잡음)
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