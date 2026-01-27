# modules/pipe_tracker.py

import cv2
import numpy as np
import math
from typing import Optional, Tuple
from core.data_types import PipeResult

class PipeTracker:
    """
    주행 경로(파이프)를 탐지하고 분석하는 클래스.
    설정된 ROI 영역 내에서 파이프의 위치뿐만 아니라, 로봇의 조향을 위한
    기울기(Angle)와 벡터(Start/End Point)를 추출합니다.
    """
    def __init__(self, roi_config: dict):
        self.roi = roi_config   # {'x': int, 'y': int, 'w': int, 'h': int}

    def process(self, frame: np.ndarray) -> PipeResult:
        """
        이미지 프레임에서 파이프 라인을 검출합니다.
        
        [변경 사항 - 2026.01.18]
        단일 중심점(Track Point)만 반환하던 기존 방식에서,
        파이프의 시작점, 끝점, 그리고 각도를 포함하는 벡터 정보를 반환하도록 개선되었습니다.
        """
        if frame is None: return PipeResult()

        # 1. ROI Crop
        rx, ry, rw, rh = self.roi['x'], self.roi['y'], self.roi['w'], self.roi['h']
        roi_img = frame[ry:ry+rh, rx:rx+rw]
        
        if roi_img.size == 0: return PipeResult()
        
        # 2. 알고리즘 수행
        result = PipeResult(roi_coords=self.roi)

        # [Mod] Start, End, Angle 추출
        fit_data = self._find_best_fit_line(roi_img)

        if fit_data:
            (sx, sy), (ex, ey), angle_deg = fit_data

            # Local(ROI) -> Global 좌표 변환
            global_start = (sx + rx, sy + ry)
            global_end = (ex + rx, ey + ry)
            
            # 결과 저장
            result.start_point = global_start
            result.end_point = global_end
            result.angle = angle_deg

            # [Legacy Support] 기존 로직과의 호환성을 위한 중심점 계산
            center_x = (global_start[0] + global_end[0]) // 2
            center_y = (global_start[1] + global_end[1]) // 2
            
            result.track_point = {'x': center_x, 'y': center_y}
            result.track_point_ratio = float(sx) / rw
            
        return result
    
    def _find_best_fit_line(self, img: np.ndarray) -> Optional[Tuple[Tuple[int, int], Tuple[int, int], float]]:
        """
        ROI 이미지에서 파이프의 대표 직선(Main Vector)을 추출합니다.

        [알고리즘 변경 사항]
        - 기존: 검출된 모든 선분의 X좌표 평균(Mean) 사용 -> 위치만 파악 가능
        - 변경: 검출된 모든 점들에 대해 직선 피팅(cv2.fitLine) 수행 -> 기울기(Angle) 파악 가능

        [파라미터 튜닝 노트]
        - minLineLength: 130 -> 60 (감소)
          -> 이유: fitLine을 위해서는 긴 직선 하나보다, 끊겨 있더라도 많은 수의 점 데이터(Sample)를 
             확보하는 것이 통계적으로 유리하기 때문에 제약 조건을 완화함.
        - maxLineGap: 15 -> 20 (증가)
          -> 이유: 끊어진 파이프 라인을 하나의 덩어리로 더 잘 묶기 위함.

        Returns:
            ((start_x, start_y), (end_x, end_y), angle_degree)
            - start_point: 이미지 하단 (로봇과 가까운 쪽)
            - end_point: 이미지 상단 (로봇과 먼 쪽)
            - angle: 수직 기준 각도 (0도=우측 수평, 90도=수직)
        """
        h, w = img.shape[:2]
        
        # 전처리: Gray -> Equalize -> Blur -> Canny
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(cv2.equalizeHist(gray), (5, 5), 0)
        edges = cv2.Canny(blur, 50, 150)
        
        # 직선 검출 (확률적 허프 변환)
        # 앵글 계산을 위해 조금 더 자잘한 선분도 포함하도록 파라미터 조정됨 (docstring 참조)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 40, minLineLength=60, maxLineGap=20)
        
        if lines is None: return None
        
        # 유효한 점 수집 (각도 필터링: 수평선 노이즈 제거)
        valid_points = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            dx, dy = x2 - x1, y2 - y1
            
            # 수직에 가까운 선(>60도)만 유효 데이터로 인정
            angle = math.degrees(math.atan2(abs(dy), abs(dx)))
            if angle > 60: 
                valid_points.append([x1, y1])
                valid_points.append([x2, y2])
                
        if not valid_points: return None
        
        # [핵심] fitLine을 이용한 대표 직선 추출
        valid_points = np.array(valid_points)
        # vx, vy: 정규화된 단위 벡터
        # x, y: 직선 위의 한 점
        vx, vy, x, y = cv2.fitLine(valid_points, cv2.DIST_L2, 0, 0.01, 0.01)
        
        # 벡터 방향 보정 (항상 이미지 상단(위쪽)을 향하도록 통일: vy < 0)
        # 이미지 좌표계는 아래가 y+, 위가 y- 이므로, 위로 가는 벡터는 vy가 음수여야 함
        if vy > 0:
            vx, vy = -vx, -vy

        # 앵글 계산 (이미지 좌표계 기준)
        angle_rad = math.atan2(-vy, vx)     # y축 반전 고려 (이미지좌표계 -> 카르테시안)
        angle_deg = math.degrees(angle_rad)
        
        # 직선 방정식을 이용해 ROI 상단(y=0)과 하단(y=h)의 교점 계산
        # 공식: (X - x)/vx = (Y - y)/vy  =>  X = x + (Y - y) * (vx/vy)
        try:
            # Start Point (이미지 하단, Y=h)
            start_y = h
            start_x = int(x + (start_y - y) * (vx / vy))
            
            # End Point (이미지 상단, Y=0)
            end_y = 0
            end_x = int(x + (end_y - y) * (vx / vy))
            
            # 좌표 클램핑 (이미지 밖으로 튀지 않게 안전장치)
            start_x = np.clip(start_x, 0, w)
            end_x = np.clip(end_x, 0, w)
            
            return ((start_x, start_y), (end_x, end_y), angle_deg)
            
        except ZeroDivisionError:
            return None     # 완전 수평선(vy=0)은 취급 안 함

    # 기존 파이프 탐지 알고리즘
    # def _find_track_point_algorithm(self, img: np.ndarray) -> Optional[Tuple[int, int]]:
    #     """
    #     이미지 처리 파이프라인:
    #     Gray -> EqualizeHist -> GaussianBlur -> Canny -> HoughLinesP
    #     """
    #     # 전처리
    #     gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    #     blur = cv2.GaussianBlur(cv2.equalizeHist(gray), (5, 5), 0)
    #     edges = cv2.Canny(blur, 50, 150)
        
    #     # 직선 검출 (확률적 허프 변환)
    #     lines = cv2.HoughLinesP(edges, 1, np.pi/180, 40, minLineLength=130, maxLineGap=15)
        
    #     x_coords = []
    #     if lines is not None:
    #         for line in lines:
    #             x1, y1, x2, y2 = line[0]
    #             # 각도 계산 (수직에 가까운 선만 필터링)
    #             if x2 != x1:
    #                 angle = abs(np.rad2deg(np.arctan2(y2 - y1, x2 - x1)))
    #             else:
    #                 angle = 90.0

    #             if angle > 70:  # 70도 이상인 선만 유효
    #                 x_coords.extend([x1, x2])
        
    #     # 검출된 선들의 평균 X좌표 반환
    #     return (int(np.mean(x_coords)), img.shape[0]//2) if x_coords else None