# utils/file_io.py

import os
import cv2
import json
import csv
import numpy as np
from dataclasses import asdict
from typing import Optional, Union
from enum import Enum

# Config & Blackboard Import
from mcvs.utils.config import RUNTIME_OPTIONS, PATHS, CAM_CONFIG, ZED_CONFIG
from common.blackboard import VisionPerception

class NumpyEncoder(json.JSONEncoder):
    """JSON 직렬화를 위한 커스텀 인코더 (Numpy 타입 지원)"""
    def default(self, obj):
        if isinstance(obj, (np.integer, int)):
            return int(obj)
        if isinstance(obj, (np.floating, float)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        # [Fix] numpy bool 타입 처리 추가
        if isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        # Enum 타입 처리 추가 (Blackboard에 Enum이 많아졌으므로 필수!)
        # [Mod] 더 안전한 Enum 처리
        if isinstance(obj, Enum):
            return obj.name
        if hasattr(obj, 'name'):  # Enum 외의 name 속성 가진 객체 대비 (Fallback)
            return obj.name
        
        return super().default(obj)

class FileSaver:
    """
    영상 저장(Video), 로그 저장(JSON), 동기화 테스트 로그(CSV)를 담당하는 클래스.
    """
    def __init__(self, output_dir: str, csv_filename: str = None):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)     # 메인 output 폴더 생성
        
        # 1. JSON Log Buffer Setup
        self.log_buffer = []
        self.BUFFER_THRESHOLD = 50  # 50프레임마다 저장 (약 3~4초 간격)
        self.log_path = os.path.join(output_dir, PATHS['log_json'])
        
        if RUNTIME_OPTIONS['save_log_json']:
            # 파일 초기화 (Overwrite)
            with open(self.log_path, 'w', encoding='utf-8') as f:
                pass
            print(f"[FileSaver] JSON 로그 파일 생성: {self.log_path}")

        # 2. CSV Log Setup (Sync Test)
        self.csv_path = None
        if csv_filename:
            self.csv_path = os.path.join(output_dir, csv_filename)
            try:
                with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "id", "ts_z", "ts_l", "ts_r",
                        "diff_zl", "diff_zr", "diff_lr", "diff_max"
                    ])
                print(f"[FileSaver] CSV 로그 파일 생성: {self.csv_path}")
            except Exception as e:
                print(f"[FileSaver] ❌ CSV 초기화 실패: {e}")
                self.csv_path = None
                
        # 3. Video Writer Setup
        self.writers = {}
        
        # [New] 스케일 값 로드 (기본값 1.0)
        self.video_scale = RUNTIME_OPTIONS.get('video_save_scale', 1.0)
        
        # 병합 영상용 타겟 높이 (초기화는 _init_video에서)
        self.combined_target_h = None
        
        if RUNTIME_OPTIONS.get('video_save', False):
            self._init_video()
        
    def _init_video(self):
        """비디오 저장용 VideoWriter 객체 초기화"""
        try:
            save_dir = os.path.join(self.output_dir, "save_videos")
            os.makedirs(save_dir, exist_ok=True)
            
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            fps = float(CAM_CONFIG['fps'])
            channels = RUNTIME_OPTIONS.get('video_channels', {}) # {'left': True, ...}

            print(f"[FileSaver] 비디오 녹화 시작 (@{fps}fps, Scale: {self.video_scale}) -> {save_dir}")
    
            # 1. 개별 카메라 녹화 초기화 (스케일이 적용된 해상도로 Writer 생성)
            self.w_cam = int(CAM_CONFIG['width'] * self.video_scale)
            self.h_cam = int(CAM_CONFIG['height'] * self.video_scale)
            
            self.w_zed = int((ZED_CONFIG['width'] // 2) * self.video_scale)
            self.h_zed = int(ZED_CONFIG['height'] * self.video_scale)
            
            # Arducam Left
            if channels.get('left'):
                path = os.path.join(save_dir, "video_left.mp4")
                self.writers['left'] = cv2.VideoWriter(path, fourcc, fps, (self.w_cam, self.h_cam))
                print("  > [LEFT] Recording...")

            # Arducam Right
            if channels.get('right'):
                path = os.path.join(save_dir, "video_right.mp4")
                self.writers['right'] = cv2.VideoWriter(path, fourcc, fps, (self.w_cam, self.h_cam))
                print("  > [RIGHT] Recording...")

            # ZED Left (Half Width)
            if channels.get('zed'):
                path = os.path.join(save_dir, "video_zed.mp4")
                self.writers['zed'] = cv2.VideoWriter(path, fourcc, fps, (self.w_zed, self.h_zed))
                print("  > [ZED] Recording...")
            
            # 2. Combined 녹화 초기화
            if channels.get('combined'):
                # (1) 가장 작은 높이를 기준으로 잡되, 스케일도 적용
                base_h = min(CAM_CONFIG['height'], ZED_CONFIG['height'])
                self.combined_target_h = int(base_h * self.video_scale)
                
                # (2) 스케일된 높이에 맞춰 너비 계산 (비율 유지)
                # Arducam
                scale_cam = self.combined_target_h / CAM_CONFIG['height']
                w_cam_final = int(CAM_CONFIG['width'] * scale_cam)
                
                # ZED
                scale_zed = self.combined_target_h / ZED_CONFIG['height']
                w_zed_final = int((ZED_CONFIG['width'] // 2) * scale_zed)
                
                # (3) 전체 너비
                total_w = w_cam_final + w_zed_final + w_cam_final
                
                path = os.path.join(save_dir, "video_combined.mp4")
                self.writers['combined'] = cv2.VideoWriter(path, fourcc, fps, (total_w, self.combined_target_h))
                
                print(f"  > [COMBINED] Size: {total_w}x{self.combined_target_h}")
        
        except Exception as e:
            print(f"[FileSaver] ❌ 비디오 초기화 실패: {e}")
            self.writers = {}

    # _resize_frame 함수 수정: 'target_size'가 없으면 저장해둔 크기 사용
    def _resize_frame(self, frame, target_size=None):
        """[Helper] 프레임 리사이즈 함수"""
        if frame is None: return None
        
        # 1. target_size가 명시되면 거기에 맞춤 (VideoWriter 크기)
        if target_size:
            return cv2.resize(frame, target_size)
        
        # 2. 개별 저장 시: 이미지 크기에 따라 미리 계산된 self.w_cam / self.w_zed 적용
        # (입력 프레임 크기로 Arducam인지 ZED인지 구분)
        h, w = frame.shape[:2]
        
        # Arducam (4:3 비율 가정)
        if w == CAM_CONFIG['width'] and h == CAM_CONFIG['height']:
            return cv2.resize(frame, (self.w_cam, self.h_cam))
            
        # ZED (Half Width 가정)
        if w == (ZED_CONFIG['width'] // 2):
            return cv2.resize(frame, (self.w_zed, self.h_zed))
        
        # 그 외(혹은 scale=1.0): 원본 리턴
        return frame

    def save_video_frame(self, result):
        """프레임 저장 (Annotated 우선, 없으면 Raw)"""
        if not self.writers: return

        # [Mod] annotated_right가 있으면 그것을, 없으면 원본을 사용하도록 수정
        img_l = result.annotated_left if result.annotated_left is not None else result.bundle.images.get('left')
        img_z = result.annotated_zed if result.annotated_zed is not None else result.bundle.images.get('zed_l')
        
        # [New] Right도 Annotated 확인 추가
        img_r = result.annotated_right if result.annotated_right is not None else result.bundle.images.get('right')
        
        # 1. 개별 저장 (Resize 적용)
        if 'left' in self.writers and img_l is not None: 
            self.writers['left'].write(self._resize_frame(img_l))
            
        if 'right' in self.writers and img_r is not None: 
            self.writers['right'].write(self._resize_frame(img_r))
            
        if 'zed' in self.writers and img_z is not None: 
            self.writers['zed'].write(self._resize_frame(img_z))
        
        # 2. 병합 저장
        if 'combined' in self.writers:
            # combined는 _make_combined_frame 내부에서 리사이즈를 수행함
            combined_frame = self._make_combined_frame(img_l, img_z, img_r)
            if combined_frame is not None:
                self.writers['combined'].write(combined_frame)
    
    def _make_combined_frame(self, img_l, img_z, img_r):
        """3개의 이미지를 combined_target_h에 맞춰 리사이징 후 병합"""
        # 안전장치: target_h가 설정되지 않았으면 실행 불가
        if self.combined_target_h is None: return None
        
        try:
            images_to_stack = []
            sources = [(img_l, "LEFT"), (img_z, "ZED"), (img_r, "RIGHT")]

            for img, label in sources:
                if img is None: return None
                
                h, w = img.shape[:2]
                
                # 타겟 높이(이미 스케일 적용됨)에 맞춰 리사이즈
                # 여기서 scale 변수는 '높이 맞추기용 비율'임
                scale = self.combined_target_h / h
                new_w = int(w * scale)
                resized = cv2.resize(img, (new_w, self.combined_target_h))
                
                # 텍스트 추가 (스케일이 작아졌으니 글자도 좀 작게 조정)
                font_scale = 0.7 if self.video_scale >= 0.8 else 0.5
                cv2.putText(resized, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 
                            font_scale, (0, 255, 255), 2)
                
                images_to_stack.append(resized)
            
            return cv2.hconcat(images_to_stack)

        except Exception as e:
            print(f"[FileSaver] 병합 실패: {e}")    # 너무 자주 뜨면 주석 처리
            return None


    def accumulate_log(self, data: VisionPerception):
        """
        Blackboard의 Vision 데이터(VisionPerception)를 버퍼에 쌓고 주기적으로 파일에 씀.
        dataclasses.asdict()를 이용해 딕셔너리로 변환하여 저장.
        """
        try:
            self.log_buffer.append(asdict(data))
            if len(self.log_buffer) >= self.BUFFER_THRESHOLD: 
                self.flush_logs()
        except Exception as e:
            # 변환 중 에러 방지 (Enum 직렬화 등)
            print(f"[FileSaver] 로그 데이터 버퍼링 오류: {e}")

    def flush_logs(self):
        """버퍼 -> 파일 쓰기"""
        if not self.log_buffer: return
        try:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                for entry in self.log_buffer:
                    # NumpyEncoder가 Enum 처리도 하도록 수정됨
                    f.write(json.dumps(entry, cls=NumpyEncoder) + '\n')
            self.log_buffer = []            
        except Exception as e:
            print(f"[FileSaver] 로그 저장 오류: {e}")

    def save_final_json(self):
        """종료 전 남은 로그 저장"""
        if self.log_buffer:
            print(f"[FileSaver] 잔여 로그 {len(self.log_buffer)}건 저장 중...")
            self.flush_logs()

    def close(self):
        """리소스 해제"""
        for w in self.writers.values(): w.release()
        self.save_final_json()
        print("[FileSaver] 모든 비디오 파일 저장 완료.")

    def append_csv_log(self, result):
        """동기화 테스트용 CSV 로그 추가"""
        if not self.csv_path: return

        try:
            ts = result.bundle.timestamps
            ts_z = ts.get('zed', 0.0)
            ts_l = ts.get('left', 0.0)
            ts_r = ts.get('right', 0.0)
            
            # 시차 계산
            diff_z_l = ts_z - ts_l
            diff_z_r = ts_z - ts_r
            diff_l_r = ts_l - ts_r
            
            # 최대 시차 (유효한 타임스탬프만 고려)
            valid_ts = [v for v in ts.values() if v > 0]
            diff_max = (max(valid_ts) - min(valid_ts)) if valid_ts else 0.0

            with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow([
                    result.bundle.sync_id,
                    f"{ts_z:.6f}", f"{ts_l:.6f}", f"{ts_r:.6f}",
                    f"{diff_z_l:.6f}", f"{diff_z_r:.6f}", f"{diff_l_r:.6f}",
                    f"{diff_max:.6f}"
                ])
        except Exception:
            pass    # CSV 에러 무시