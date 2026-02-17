# utils/config.py

import cv2
from pathlib import Path

# 프로젝트 루트 경로 (현재 파일 기준: utils/config.py -> mcvs_for_chamdog/)
BASE_DIR = Path(__file__).resolve().parent.parent

# ==========================================
# 1. 파일 및 경로 설정 (Path Settings)
# ==========================================
PATHS = {
    "output": str(BASE_DIR / "output"),
    "weights": str(BASE_DIR / "weights"),
    "log_json": "all_results.jsonl",      # 전체 로그 파일명
    "sync_log": "sync_test_log.csv"       # 동기화 테스트용 CSV
}

# ==========================================
# 2. 하드웨어 설정 (Hardware Settings)
# ==========================================
# 카메라 디바이스 경로 (Symbolic Link 권장)
CAM_SYMBOL = {
    "left_cam": "/dev/arducam_left",
    "right_cam": "/dev/arducam_right",
    "zed_cam": "/dev/zed"
}

# Arducam (Left/Right) 공통 설정
CAM_CONFIG = {
    "width": 800, 
    "height": 600, 
    "fps": 15,
    "fourcc": cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')
}

# ZED Camera 설정 (Side-by-Side 이미지)
ZED_CONFIG = {
    "width": 2560,  # 1280 * 2
    "height": 720, 
    "fps": 15
}

# ==========================================
# 3. 알고리즘 튜닝 (Algorithm Tuning)
# ==========================================
# YOLO 모델 신뢰도 임계값
MODEL_CONF = 0.6

# YOLO 추론을 수행할 카메라 목록 (Multi-Source 지원)
# 예시: ['left'], ['right'], ['left', 'right'], [] (안 함)
DETECTION_TARGETS = ['left']  # 기본값

# ==========================================
# 4. 런타임 옵션 (Runtime Options)
# ==========================================
RUNTIME_OPTIONS = {
    "save_log_json": False,  # JSONL 로그 저장 여부
    "run_sync_test": True, # 동기화 테스트용 CSV 저장 여부
    
    # 웹 스트리밍 서버 활성화 여부 (포트 50020)
    "enable_stream_server": True, 
    "stream_display_height": 480,   # 스트리밍 시청 해상도 높이 (작을수록 빠름)
    
    # 비디오 녹화 설정
    "video_save": False,
    "video_save_scale": 1.0,    # 비디오 저장 스케일: 용량 절약을 위해 0.5 ~ 0.7 수준 권장

    "video_channels": {
        "left": False,   # YOLO 결과 포함됨
        "right": False, # 필요 시 True로 변경
        "zed": False,     # Pipe 결과 포함됨
        "combined": True    # 3분할 병합 영상
    }
}

# ==========================================
# 5. 시스템 고급 설정 (System Advanced)
# ==========================================
_BASE_FPS = CAM_CONFIG['fps']
SYNC_TOLERANCE_FRAMES = 2 / 3 # 동기화 허용 오차 (프레임 수 기준):
    # NOTE 현재 허용오차 값인 "(2/3) * T_frame"는 수학적 증명으로 얻은 최적값임
WARMUP_TIME_SEC = 2.0       # 카메라 워밍업 시간 (초)

SYSTEM_SETTINGS = {
    "camera_buffer": 2,     # 각 카메라 스레드 버퍼 크기: [Optimal] 최소한의 완충 (Double Buffering)
    "inference_buffer": 2,  # 추론 대기 큐 크기: [Optimal] 대기열 1개 + 처리중 1개 = 끊김 없는 처리
    "save_buffer": 10,      # 저장 대기 큐 크기: [Safety] I/O 지연 대비 넉넉하게
    
    # 계산된 값들
    "sync_threshold": SYNC_TOLERANCE_FRAMES / _BASE_FPS, # 초 단위 허용 오차
    "warmup_frames": int(WARMUP_TIME_SEC * _BASE_FPS)
}