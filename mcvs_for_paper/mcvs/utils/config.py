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
    # [removed] "debug_img": str(BASE_DIR / "output" / "debug_live"),   # 실시간 디버그 이미지 저장 경로
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

# [Mod] 파이프 탐지 소스 카메라 선택 (Single-Source) - ('left', 'right', 'zed')
PIPE_TRACKING_SOURCE = 'right'

# [Mod] YOLO 추론을 수행할 카메라 목록 (Multi-Source 지원)
# 예시: ['left'], ['right'], ['left', 'right'], [] (안 함)
# 단, 현재 코드 상으로는 이미지 크기가 동일한 것만 가능. 즉, zed는 불가
DETECTION_TARGETS = ['left']  # 기본값

# ==========================================================================
# [👷 테스트용 설정 가이드] 파이프 탐지 ROI (관심 영역) 수정 위치
# --------------------------------------------------------------------------
# 파이프 인식 범위를 조절하려면 아래 숫자들을 변경해주세요.
# ※ 주의: 붉은색 박스(ROI)가 화면 밖으로 나가지 않도록 해상도를 확인해주세요.
#
#   (0,0) ---------------------> X축 (너비)
#     |      [x, y] 점 (시작점)
#     |        ↓
#     |        ┌──────────────┐
#     |        │   관심 영역   │  h (높이)
#     |        │    (ROI)     │
#     ↓        └──────────────┘
#   Y축 (높이)         w (너비)
# --------------------------------------------------------------------------

# [Mod] 파이프라인 탐지 ROI (카메라 종류에 따라 구분)
if PIPE_TRACKING_SOURCE == 'zed':
    # 기존 ZED(1280x720)용
    PIPE_ROI_COORS = {'x': 540, 'y': 530, 'w': 220, 'h': 300}
else:
    # Arducam (800x600)용
    PIPE_ROI_COORS = {'x': 250, 'y': 350, 'w': 300, 'h': 250}

# 조향 로직 임계값 (이미지 가로 비율 0.0 ~ 1.0 기준)
# PipeTracker가 계산한 ratio가 이 구간에 들어오면 해당 flag 반환
STEERING_RATIOS = {
    'left_forbidden': 0.15,  # 0.0 ~ 0.15: Hard Left
    'left_steer': 0.35,      # 0.15 ~ 0.35: Slight Left
    'right_steer': 0.65,     # 0.65 ~ 0.85: Slight Right
    'right_forbidden': 0.85  # 0.85 ~ 1.0: Hard Right
}

# ==========================================================================
# [👷 테스트용 설정 가이드] 수확 영역 판단 (Harvest & Trigger Zone)
# --------------------------------------------------------------------------
# 로봇이 "어느 영역에 있는 참외"에 반응할지 설정해주세요.
# 값은 이미지 전체 크기에 대한 '비율(0.0 ~ 1.0)'입니다.
#
#   (0,0) ----------------------> X (1.0)
#     |       [Trigger Zone]
#     |      (가장 좁은 중앙)
#     |
#     |     [Harvest Zone]
#     |    (작업 가능 범위)
#     |
#     ↓ Y (1.0)
# --------------------------------------------------------------------------

# [New] 수확 판단 상세 조건 (detector.HarvestAnalyzer용)
# Vision System 내부에서 1차 필터링을 위한 기준
HARVEST_ANALYZE_CONFIG = {
    # 1. Harvest Zone (작업 가능 영역) (0.0~1.0 비율)
    # : 이 안에 들어와야 'Candidate(후보)'가 되고, 수확 시도를 합니다.
    "zone_x_min": 0.15, "zone_x_max": 0.85,
    "zone_y_min": 0.10, "zone_y_max": 0.90,

    # 2. Trigger Zone (정지 유도 영역)
    # : 이 좁은 영역에 참외 중심이 들어오면 로봇이 '정지'합니다.
    "trigger_x_min": 0.45, "trigger_x_max": 0.55,
    "trigger_y_min": 0.30, "trigger_y_max": 0.70,

    # 3. 품질 조건
    "min_area_ratio": 0.005,
    "min_confidence": 0.6      # YOLO 인식률 최소값 ###### 이거 위에 MODEL_CONF랑 겹치는 거 아닌가?
    # "ripeness_threshold": 0.4, # Color 조건은 추후 도입 여부 고민
}

# ==========================================
# 4. 런타임 옵션 (Runtime Options)
# ==========================================
RUNTIME_OPTIONS = {
    "save_log_json": True,  # JSONL 로그 저장 여부
    "run_sync_test": False, # 동기화 테스트용 CSV 저장 여부
    
    # [New] 웹 스트리밍 서버 활성화 여부 (포트 50020)
    "enable_stream_server": True, 
    "stream_display_height": 480,   # [New] 스트리밍 시청 해상도 높이 (작을수록 빠름, 기본 480px 추천)
    
    # 비디오 녹화 설정
    "video_save": False,
    "video_save_scale": 0.5,    # [New] 비디오 저장 스케일: 용량 절약을 위해 0.5 ~ 0.7 수준 권장

    "video_channels": {
        "left": False,   # YOLO 결과 포함됨
        "right": False, # 필요 시 True로 변경
        "zed": False,     # Pipe 결과 포함됨
        "combined": True    # 3분할 병합 영상
    },
    
    # [TODO] 이제 이 변수는 필요 없다고 판단 (근데 아직 실제로 지워서 오류가 안 생기는지는 확인을 못함)
    # [New] 실시간 대시보드 서버(IPC) 활성화 여부
    # True: 모니터링 가능 (Port 50005) / False: 서버 안 띄움 (리소스 절약)
    "enable_dashboard_server": False
}

# ==========================================
# 5. 시스템 고급 설정 (System Advanced)
# ==========================================
_BASE_FPS = CAM_CONFIG['fps']
SYNC_TOLERANCE_FRAMES = 2 / 3 # 동기화 허용 오차 (프레임 수 기준):
    # [참고] 현재 허용오차 값인 "(2/3) * T_frame"는 수학적 증명으로 얻은 최적값임
WARMUP_TIME_SEC = 2.0       # 카메라 워밍업 시간 (초)

SYSTEM_SETTINGS = {
    "camera_buffer": 2,     # 각 카메라 스레드 버퍼 크기: [Optimal] 최소한의 완충 (Double Buffering)
    "inference_buffer": 2,  # 추론 대기 큐 크기: [Optimal] 대기열 1개 + 처리중 1개 = 끊김 없는 처리
    "save_buffer": 10,      # 저장 대기 큐 크기: [Safety] I/O 지연 대비 넉넉하게
    
    # 계산된 값들
    "sync_threshold": SYNC_TOLERANCE_FRAMES / _BASE_FPS, # 초 단위 허용 오차
    "warmup_frames": int(WARMUP_TIME_SEC * _BASE_FPS)
}