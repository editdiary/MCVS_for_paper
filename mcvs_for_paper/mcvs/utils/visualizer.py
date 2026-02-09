# utils/visualizer.py

import cv2
import numpy as np
from typing import List, Optional
from mcvs.core.data_types import PipeResult, YoloResult

class Visualizer:
    """
    OpenCV를 사용하여 이미지 위에 탐지 결과(BBox, Lane, Text)를 그리는 클래스.
    """
    # BGR Color Constants
    COLOR_RED = (0, 0, 255)      # 탈락 / 위험
    COLOR_GREEN = (0, 255, 0)    # 후보 (Candidate) / 안전
    COLOR_BLUE = (255, 0, 0)     # 라벨 텍스트
    COLOR_YELLOW = (0, 255, 255) # Harvest Zone 가이드
    COLOR_CYAN = (255, 255, 0)   # Trigger / Trigger Zone
    COLOR_BLACK = (0, 0, 0)
    
    def __init__(self, steering_ratios: dict = None, harvest_config: dict = None):
        self.font = cv2.FONT_HERSHEY_SIMPLEX

        # Steering Ratios (Default Fallback)
        self.ratios = steering_ratios if steering_ratios else {
            'left_forbidden': 0.15, 'left_steer': 0.35, 
            'right_steer': 0.65, 'right_forbidden': 0.85
        }

        # [Fix] Harvest Config Key 동기화 (harvest_ -> zone_)
        # Fallback 값도 새로운 키 이름으로 수정
        self.harvest_conf = harvest_config if harvest_config else {
            "zone_x_min": 0.15, "zone_x_max": 0.85,
            "trigger_x_min": 0.45, "trigger_x_max": 0.55
        }

    def draw_yolo(self, image: np.ndarray, yolo_results: List[YoloResult], harvest_mode: bool = False) -> Optional[np.ndarray]:
        """
        YOLO 결과(박스, 라벨) 및 수확 모드 상태 시각화.
        HarvestAnalyzer의 분석 결과(analysis)를 기반으로 색상을 다르게 표시합니다.
        """
        if image is None: return None
        out = image.copy()
        h, w = out.shape[:2]
        
        # 1. Harvest ROI Guide Lines (2D Box Visualization)
        
        # [New-승운님 요청] Center Line (Red, 실선) - 이미지 정중앙 표시
        center_x, center_y = w//2, h//2
        cv2.line(out, (center_x, 0), (center_x, h), self.COLOR_RED, 1)
        cv2.line(out, (0, center_y), (w, center_y), self.COLOR_RED, 1) # [New] Y축 중앙선 추가
        
        # (A) Harvestable Zone (Yellow Box)
        h_x_min = int(w * self.harvest_conf.get('zone_x_min', 0.15))
        h_x_max = int(w * self.harvest_conf.get('zone_x_max', 0.85))
        h_y_min = int(h * self.harvest_conf.get('zone_y_min', 0.10)) # [New]
        h_y_max = int(h * self.harvest_conf.get('zone_y_max', 0.90)) # [New]

        # 네모 그리기
        cv2.rectangle(out, (h_x_min, h_y_min), (h_x_max, h_y_max), self.COLOR_YELLOW, 2)

        # (B) Trigger Zone (Cyan Box)
        t_x_min = int(w * self.harvest_conf.get('trigger_x_min', 0.45))
        t_x_max = int(w * self.harvest_conf.get('trigger_x_max', 0.55))
        t_y_min = int(h * self.harvest_conf.get('trigger_y_min', 0.30)) # [New]
        t_y_max = int(h * self.harvest_conf.get('trigger_y_max', 0.70)) # [New]
        
        # 네모 그리기 (조금 더 두껍게)
        cv2.rectangle(out, (t_x_min, t_y_min), (t_x_max, t_y_max), self.COLOR_CYAN, 2)

        # -------------------------------------------------------------
        # 2. Detections & Counting (Smart Logic)
        # -------------------------------------------------------------
        candidate_count = 0
        
        for res in yolo_results:
            x1, y1, x2, y2 = res.bbox
            
            # [Logic Visualization] 분석 결과에 따른 색상 분기
            # 기본값: Red (탈락/미분석)
            box_color = self.COLOR_RED
            thickness = 2
            status_text = ""
            
            if res.analysis:
                is_candidate = res.analysis.get('is_candidate', False)
                is_trigger = res.analysis.get('is_trigger', False)
                # reason = res.analysis.get('reason', '') # 필요시 사용

                if is_trigger:
                    # Trigger 상태: Cyan (가장 중요)
                    box_color = self.COLOR_CYAN
                    thickness = 3
                    candidate_count += 1
                    status_text = " [T]"
                elif is_candidate:
                    # Candidate 상태: Green
                    box_color = self.COLOR_GREEN
                    candidate_count += 1
                    status_text = " [C]"
            else:
                # 분석 데이터가 없는 경우 (좌표 기반 Fallback)
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                
                in_x_range = (h_x_min <= cx <= h_x_max)
                in_y_range = (h_y_min <= cy <= h_y_max)

                if in_x_range and in_y_range:
                    box_color = self.COLOR_GREEN # 영역 안이면 초록색 (임시 Candidate)
            
            # Draw Box
            cv2.rectangle(out, (x1, y1), (x2, y2), box_color, thickness)

            # Draw Label
            id_str = f"ID:{res.track_id} " if res.track_id else ""
            conf_str = f"{res.conf:.2f}"
            label = f"{id_str}{res.label} {conf_str}{status_text}"
            
            # 텍스트 배경 (가독성 향상)
            (tw, th), _ = cv2.getTextSize(label, self.font, 0.5, 1)
            cv2.rectangle(out, (x1, y1 - 20), (x1 + tw, y1), box_color, -1)
            cv2.putText(out, label, (x1, y1 - 5), self.font, 0.5, self.COLOR_BLACK, 1)
        
        # -------------------------------------------------------------
        # 3. HUD Info (Head-Up Display)
        # -------------------------------------------------------------
        if harvest_mode:
            # (1) 모드 상태 표시
            cv2.putText(out, "HARVEST MODE: ON", (20, 40), self.font, 0.8, self.COLOR_CYAN, 2)
            
            # (2) 후보 개수 표시
            info_text = f"Candidates: {candidate_count}"
            cv2.putText(out, info_text, (20, 75), self.font, 0.7, self.COLOR_GREEN, 2)
        else:
            # 주행 모드일 때
            cv2.putText(out, "NAVIGATING", (20, 40), self.font, 0.8, self.COLOR_GREEN, 2)

        return out

    def draw_pipe(self, image: np.ndarray, pipe_result: PipeResult) -> Optional[np.ndarray]:
        """파이프 라인 탐지 결과 시각화 (ROI, Steering Zones, Track Point)"""
        if image is None: return None
        out = image.copy()

        if pipe_result.roi_coords:
            rx, ry, rw, rh = (pipe_result.roi_coords['x'], pipe_result.roi_coords['y'],
                              pipe_result.roi_coords['w'], pipe_result.roi_coords['h'])
            
            # 1. Steering Zones (가상선 그리기)
            x_lf = rx + int(rw * self.ratios['left_forbidden'])
            x_ls = rx + int(rw * self.ratios['left_steer'])
            x_rs = rx + int(rw * self.ratios['right_steer'])
            x_rf = rx + int(rw * self.ratios['right_forbidden'])

            # 위험 구간 (Yellow), 안전 구간 (Green)
            cv2.line(out, (x_lf, ry), (x_lf, ry+rh), self.COLOR_YELLOW, 2)
            cv2.line(out, (x_rf, ry), (x_rf, ry+rh), self.COLOR_YELLOW, 2)
            cv2.line(out, (x_ls, ry), (x_ls, ry+rh), self.COLOR_GREEN, 1)
            cv2.line(out, (x_rs, ry), (x_rs, ry+rh), self.COLOR_GREEN, 1)

            # 2. ROI Box
            cv2.rectangle(out, (rx, ry), (rx + rw, ry + rh), self.COLOR_RED, 2)

            # [Mod] 점 대신 벡터(선분) 그리기
            if pipe_result.start_point and pipe_result.end_point:
                sx, sy = pipe_result.start_point
                ex, ey = pipe_result.end_point
                
                # 메인 파이프 라인 (굵은 빨강)
                cv2.line(out, (sx, sy), (ex, ey), self.COLOR_RED, 3)
                
                # 시작점 (초록 원), 끝점 (빨강 원)
                cv2.circle(out, (sx, sy), 8, self.COLOR_GREEN, -1)
                cv2.circle(out, (ex, ey), 5, self.COLOR_RED, -1)
                
                # 앵글 텍스트 표시
                cx = (sx + ex) // 2
                cy = (sy + ey) // 2
                cv2.putText(out, f"{pipe_result.angle:.1f} deg", (cx + 10, cy), 
                            self.font, 0.6, self.COLOR_YELLOW, 2)
                     
            # 3. [Mod] track_point (심플하게 점만 표시)
            if pipe_result.track_point:
                tx, ty = pipe_result.track_point['x'], pipe_result.track_point['y']
                
                # [Removed] Center Line & Error Line 제거함
                
                # Point (심플한 점 하나)
                cv2.circle(out, (tx, ty), 5, self.COLOR_RED, -1)
                
                # Error Text
                # ratio가 있으면 에러값 표시 (0.0이 중앙)
                if pipe_result.track_point_ratio is not None:
                    err = (pipe_result.track_point_ratio - 0.5) * 2.0
                    cv2.putText(out, f"Err: {err:.2f}", (tx + 10, ty - 10), self.font, 0.6, self.COLOR_YELLOW, 2)
    
        return out