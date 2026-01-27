# core/data_types.py

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np

@dataclass
class FrameBundle:
    """
    [Internal] 동기화된 멀티 카메라 프레임 묶음
    Synchronization이 완료된 후, 추론 단계로 넘어가는 기본 데이터 단위입니다.
    이미지 원본(np.ndarray)을 포함하므로 메모리를 많이 차지합니다.
    Blackboard에는 올리지 않고, 내부 파이프라인(추론/저장)에서만 돕니다.
    """
    sync_id: str
    timestamps: Dict[str, float]
    images: Dict[str, np.ndarray]

@dataclass
class YoloResult:
    """[Internal] YOLO 추론 원본 결과 (Pixel 단위)"""
    label: str
    conf: float
    bbox: Tuple[int, int, int, int]     # (x1, y1, x2, y2) Pixel 좌표
    track_id: Optional[str] = None
    
    # [New] 분석 결과 (Optional)
    # 내용: {'is_candidate': bool, 'is_trigger': bool, 'reason': str}
    analysis: Optional[dict] = None

@dataclass
class PipeResult:
    """[Internal] 파이프 라인 탐지 원본 결과"""
    roi_coords: Optional[Dict[str, int]] = None

    track_point: Optional[Dict[str, int]] = None
    track_point_ratio: Optional[float] = None

    # [New] 상세 분석 정보 (Pixel 단위)
    angle: float = 0.0
    start_point: Optional[Tuple[int, int]] = None  # (x, y) - 이미지 하단
    end_point: Optional[Tuple[int, int]] = None    # (x, y) - 이미지 상단

@dataclass
class ProcessingResult:
    """
    [Internal] Vision Pipeline의 최종 산출물 컨테이너
    용도 1: Bridge 함수에서 Blackboard 데이터로 변환 (Raw Data 제공)
    용도 2: FileSaver/Visualizer에서 영상 저장 및 시각화 (이미지 제공)
    """
    bundle: FrameBundle

    # [Mod] 변경 전: yolo_detections: List[YoloResult]
    # [Mod] 변경 후: 카메라 이름을 키로 갖는 딕셔너리
    # 예: {'left': [res1, res2], 'right': [res3]}
    yolo_detections: Dict[str, List[YoloResult]]

    pipe_result: PipeResult

    # 시각화(Annotated) 이미지 저장용
    annotated_left: Optional[np.ndarray] = None
    annotated_zed: Optional[np.ndarray] = None
    annotated_right: Optional[np.ndarray] = None