# mcvs/main.py

import sys
import os
import threading
import time
from typing import Tuple
from pathlib import Path
from queue import Queue, Full, Empty
from concurrent.futures import ThreadPoolExecutor

# Project Root Setup (상위 폴더 import 가능하게 설정)
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.append(str(project_root))

# Import Custom Modules
from utils.config import *
from core.data_types import FrameBundle, ProcessingResult, PipeResult
from core.camera_manager import CameraManager
from core.synchronizer import FrameSynchronizer
from modules.detector import YoloDetector, HarvestAnalyzer
from modules.pipe_tracker import PipeTracker
#from modules.bridge_server import BridgeServer  # [New] 추가
from utils.file_io import FileSaver
from utils.visualizer import Visualizer
from utils.stats_collector import StatsCollector, start_stats_logging_thread
#from utils.ipc_server import DashboardServer # [New] 추가
from utils.stream_server import StreamingServer


# [New] IPC 매니저 가져오기 (파일이 없다면 try-except로 방어 가능)
try:
    from common.ipc_manager import get_shared_blackboard
    IPC_AVAILABLE = True
except ImportError:
    IPC_AVAILABLE = False

# Blackboard Imports
from common.blackboard import (
    Blackboard, VisionPerception, 
    TotalObject, ObjectObservation, ObjectLogic, ObjectSource,
    VisionCommand, SystemState, MissionMode, PipePosition
)

# 전역 종료 이벤트
SHUTDOWN_EVENT = threading.Event()

def inference_worker(input_queue: Queue, output_queue: Queue, 
                     detector: YoloDetector, pipe_tracker: PipeTracker,
                     blackboard: Blackboard):   # [New] Blackboard 접근 권한 추가
    """
    [Consumer 1] 동기화된 프레임 번들을 받아 비동기 병렬 추론을 수행합니다.
    - CPU: Pipe Tracking (opencv)
    - GPU: Object Detection (tensorrt)
    - VisionCommand에 따라 'STREAMING(추론 수행)' 또는 'STANDBY(추론 생략)' 결정
    """
    print("[Inference] 추론 스레드 시작 (Ready)")
    executor = ThreadPoolExecutor(max_workers=1)
    analyzer = HarvestAnalyzer(HARVEST_ANALYZE_CONFIG)  # [New] 분석기 인스턴스 생성
    
    while not SHUTDOWN_EVENT.is_set():
        try:
            bundle: FrameBundle = input_queue.get(timeout=1.0)
            
            # [Step 1] Blackboard에서 현재 명령 확인
            # (이제 BridgeServer가 아니라 IPC에서 직접 읽음)
            # [TODO] Vision 모드에 따라 return 로직 바뀌도록 변경 필요
            try:
                current_cmd = blackboard.get_mission().vision_command
            except:
                current_cmd = VisionCommand.SCANNING # 기본값

            # # [Optimization] 명령이 OFF면 추론 스킵 (CPU/GPU 절약)
            # if current_cmd == VisionCommand.OFF:
            #     # 아무것도 안 하고 큐만 비움 (혹은 프레임 드랍)
            #     continue
            
            # 결과 컨테이너 초기화
            pipe_result = PipeResult()
            
            # [Mod] 딕셔너리로 초기화
            yolo_results_dict = {}

            # 1. Pipe Tracking (CPU) - 비동기
            # [Mod] Config에 따라 파이프 탐지 대상 이미지 선택
            pipe_source_img = None
            if PIPE_TRACKING_SOURCE == 'right': pipe_source_img = bundle.images.get('right')
            elif PIPE_TRACKING_SOURCE == 'left': pipe_source_img = bundle.images.get('left')
            else: pipe_source_img = bundle.images.get('zed_l')
            
            # [Mod] 선택된 이미지(pipe_source_img) 전달
            pipe_future = executor.submit(pipe_tracker.process, pipe_source_img)
            
            # =========================================================
            # [Mod] 2. Object Detection (GPU) - Batch Inference 적용
            # =========================================================

            # (1) 배치 구성을 위한 리스트 준비
            batch_images = []
            batch_keys = [] # 나중에 결과를 딕셔너리에 매핑하기 위한 키 저장

            for cam_name in DETECTION_TARGETS:
                # 안전하게 이미지 가져오기
                img = bundle.images.get(cam_name)

                # 이미지가 존재하고, 유효한 경우에만 배치에 추가
                if img is not None and img.size > 0:
                    batch_images.append(img)
                    batch_keys.append(cam_name)
                
            # (2) 배치 추론 수행
            if batch_images:
                try:
                    # [Batch Inference] 한 번에 리스트 전달
                    # model.track([img1, img2]) 형태로 호출됨
                    # (단, 모델이 dynamic=True 혹은 해당 배치사이즈로 빌드되어 있어야 함)
                    batch_results = detector.track(batch_images)

                    # (3) 결과를 다시 딕셔너리로 분배 (Analyze 포함)
                    # batch_results 리스트의 순서는 batch_images의 순서와 동일함
                    for i, dets in enumerate(batch_results):
                        cam_key = batch_keys[i]
                        source_img = batch_images[i]
                        
                        # 분석기(HarvestAnalyzer) 실행 (CPU 작업이라 여기서 루프 돔)
                        for res in dets:
                            analysis_res = analyzer.analyze(source_img, res.bbox)
                            res.analysis = analysis_res
                        
                        # 최종 저장
                        yolo_results_dict[cam_key] = dets

                except Exception as e:
                    print(f"[Inference] ⚠️ 배치 추론 에러: {e}")
                    # 에러 발생 시 빈 딕셔너리로 넘어감 (시스템 죽지 않게)

            # 3. Pipe 결과 대기
            try:
                pipe_result = pipe_future.result(timeout=0.5)
            except Exception as e:
                print(f"[Inference] Pipe 연산 지연/에러: {e}")
        
            # [Step 3] 결과 패키징
            result = ProcessingResult(
                bundle=bundle,
                yolo_detections=yolo_results_dict,
                pipe_result=pipe_result
            )
            
            # 저장 큐로 전송 (Full이면 Drop -> 최신성 유지)
            try: output_queue.put(result, block=False)
            except Full: pass

        except Empty: continue
        except Exception as e: 
            print(f"[Inference] ❌ 스레드 에러: {e}")
            if SHUTDOWN_EVENT.is_set(): break

    executor.shutdown(wait=False)
    print("[Inference] 스레드 종료.")

# _bridge_to_blackboard 수정 (Data Mapping)
def _bridge_to_blackboard(result: ProcessingResult) -> Tuple[VisionPerception, bool]:
    """
    [Adapter] 내부 처리 결과(ProcessingResult) -> Blackboard 표준 포맷(VisionPerception) 변환
    """
    perception = VisionPerception()
    
    # 1. 상태 동기화 (임시: SCANNING) - [TODO] 실제 로직에 맞게 추후 연결 필요
    perception.current_state = VisionCommand.SCANNING
    
    # 2. Resolution Info (메타데이터 복구)
    perception.resolution = {
        'arducam': (CAM_CONFIG['width'], CAM_CONFIG['height']),
        'zed': (ZED_CONFIG['width'] // 2, ZED_CONFIG['height'])
    }
    
    # 3. Pipe Logic
    if result.pipe_result.track_point_ratio is not None:
        perception.is_pipe_detected = True

        # [New] 상세 정보 할당
        # 1. 앵글 값 할당
        perception.pipe_angle = result.pipe_result.angle

        # 좌표 정규화 (Normalization)
        # 파이프 탐지는 ROI 영역 내에서 이뤄지지만, Global 좌표로 변환되어 넘어옴
        # 따라서 전체 해상도(img_w, img_h)로 나누면 됨
        # 현재 파이프 탐지 소스에 따른 해상도 결정
        if PIPE_TRACKING_SOURCE == 'zed':
            pw, ph = ZED_CONFIG['width']//2, ZED_CONFIG['height']
        else: # left / right
            pw, ph = CAM_CONFIG['width'], CAM_CONFIG['height']

        # [Fix] 2. 튜플 형태로 안전하게 할당 (값이 있을 때만)
        if result.pipe_result.start_point:
            sx, sy = result.pipe_result.start_point
            perception.pipe_start_point = (float(sx) / pw, float(sy) / ph)

        if result.pipe_result.end_point:
            ex, ey = result.pipe_result.end_point
            perception.pipe_end_point = (float(ex) / pw, float(ey) / ph)

        # Raw Ratio (0.0 ~ 1.0)
        ratio = result.pipe_result.track_point_ratio
        
        # (1) Lateral Error 계산: 0.0(L) ~ 1.0(R) -> -1.0(L) ~ 1.0(R)
        # 이 값은 PID 제어 등 정밀 제어에 사용됩니다.
        perception.pipe_lateral_error = (ratio - 0.5) * 2.0
        
        sr = STEERING_RATIOS # utils.config에서 import 됨
        
        if ratio < sr['left_forbidden']:       # < 0.15
            perception.pipe_position = PipePosition.HARD_LEFT
            
        elif ratio < sr['left_steer']:         # 0.15 ~ 0.35
            perception.pipe_position = PipePosition.SLIGHT_LEFT
            
        elif ratio > sr['right_forbidden']:    # > 0.85
            perception.pipe_position = PipePosition.HARD_RIGHT
            
        elif ratio > sr['right_steer']:        # 0.65 ~ 0.85
            perception.pipe_position = PipePosition.SLIGHT_RIGHT
            
        else:                                  # 0.35 ~ 0.65
            perception.pipe_position = PipePosition.CENTER
            
    else:
        # 파이프 놓침 (Lost)
        perception.is_pipe_detected = False
        perception.pipe_angle = 0.0
        perception.pipe_lateral_error = 0.0
        perception.pipe_position = PipePosition.NONE
        perception.pipe_start_point = (0.0, 0.0)
        perception.pipe_end_point = (0.0, 0.0)

    # 4. Object Logic (TotalObject 변환)
    # [New] 문자열(config) -> Enum(Blackboard) 매핑 테이블
    # config.py의 DETECTION_TARGETS에 적힌 문자열을 Enum으로 바꿈
    SOURCE_MAP = {
        'left': ObjectSource.VISION_LEFT,
        'right': ObjectSource.VISION_RIGHT,
        'zed': ObjectSource.VISION_ZED,
        'zed_l': ObjectSource.VISION_ZED  # zed_l도 ZED로 취급
    }
    
    # [Mod] Multi-Source 통합. 모든 카메라에서 탐지된 객체를 하나의 리스트로 합침
    trigger_activated = False

    # 딕셔너리 순회: {'left': [...], 'right': [...]}
    for cam_name, detections in result.yolo_detections.items():

        # 해상도 정보 가져오기 (정규화를 위해)
        # bundle에 있는 이미지 크기를 쓰거나 Config를 쓸 수 있음
        # 여기선 안전하게 Config 참조 (cam_name에 따라 분기)
        if 'zed' in cam_name: 
            img_w, img_h = ZED_CONFIG['width']//2, ZED_CONFIG['height']
        else:
            img_w, img_h = CAM_CONFIG['width'], CAM_CONFIG['height']

        for d in detections:
            # (1) 관측 정보(Obs) 생성
            x1, y1, x2, y2 = d.bbox
            w, h = (x2 - x1), (y2 - y1)
            cx, cy = x1 + (w / 2.0), y1 + (h / 2.0)

            # [Mod] 매핑 테이블을 이용해 Enum 할당
            # 매핑에 없는 이름이 오면 UNKNOWN 처리 (안정성)
            enum_source = SOURCE_MAP.get(cam_name, ObjectSource.UNKNOWN)

            obs_data = ObjectObservation(
                source=enum_source,
                track_id=f"{cam_name}_{d.track_id}" if d.track_id else "N/A", # [Tip] ID 충돌 방지
                confidence=float(d.conf),
                center_x=cx / img_w,        # Normalize
                center_y=cy / img_h,        # Normalize
                width=w / img_w,            # Normalize
                height=h / img_h,           # Normalize
                area_ratio=(w * h) / (img_w * img_h)
            )
        
            # (2) 논리 정보(Logic) 생성
            analysis = d.analysis if d.analysis else {}
            logic_data = ObjectLogic(
                is_candidate=analysis.get('is_candidate', False),
                is_in_trigger_zone=analysis.get('is_trigger', False),
                is_in_harvest_zone=analysis.get('in_harvest_zone', False) # Detector에서 추가한 필드 사용
            )
        
            if logic_data.is_in_trigger_zone:
                trigger_activated = True

            # (3) 통합 객체 생성 및 리스트 추가
            # [중요] visible_chamoes -> visible_objects 로 이름 변경됨
            perception.visible_objects.append(TotalObject(obs=obs_data, logic=logic_data))
        
    # [중요] 카운트 업데이트
    perception.total_object_count = len(perception.visible_objects)

    return perception, trigger_activated
    

def save_worker(input_queue: Queue, file_saver: FileSaver, visualizer: Visualizer, 
                stats: StatsCollector, blackboard: Blackboard, streamer: StreamingServer):
    """
    [Consumer 2] Blackboard 갱신, 로그 저장, 시각화
    - 순수하게 데이터 갱신 및 저장 역할만 수행
    """
    print("[Save] 저장 스레드 시작 (Ready)")
    
    while not SHUTDOWN_EVENT.is_set():
        try:
            result: ProcessingResult = input_queue.get(timeout=1.0)
            
            # === [수정 1] Heartbeat 갱신 (Timestamp -> SystemStatus.Connection) ===
            # Vision은 'System'의 일부는 아니지만, 편의상 Connection 정보 공유를 위해 SystemStatus를 잠시 빌려 씁니다.
            # (IPC 환경에서는 전체 객체를 가져와서 수정 후 덮어써야 함)
            
            # 1. Heartbeat 갱신 (IPC 방식)
            try:
                current_sys = blackboard.get_system()          # 1. 가져오기
                current_sys.connection.vision_last_beat = time.time() # 2. 수정하기
                blackboard.update_system(current_sys)          # 3. 반영하기
            except Exception:
                pass # 일시적인 통신 에러 무시
            # ====================================================================
            
            # 2. 통계 업데이트 (모든 카메라의 탐지 개수 합산)
            total_dets = sum(len(dets) for dets in result.yolo_detections.values())
            if total_dets > 0:
                stats.log_yolo_detection(total_dets)
            
            # 3. Vision 데이터 갱신
            # _bridge_to_blackboard가 이미 Analyzer 결과를 반영한 perception을 줍니다.
            new_perception, is_triggered_now = _bridge_to_blackboard(result)
            
            # [Refactor] Vision 상태 보고
            # 현재는 명령 처리 로직이 없으므로 항상 'SCANNING' 상태라고 보고하거나,
            # 추후 구현될 실제 Inference Worker의 상태를 가져와야 함.
            # 지금은 우선 기본값(SCANNING)으로 둡니다.
            new_perception.current_state = VisionCommand.SCANNING
            
            blackboard.update_vision(new_perception)
            
            # 3. 시각화 및 스트리밍
            need_vis = (RUNTIME_OPTIONS['video_save'] or 
                        RUNTIME_OPTIONS.get('enable_stream_server', False))
            
            if need_vis:
                try:
                    current_bt_mode = blackboard.get_mission().active_mission
                except Exception:
                    current_bt_mode = MissionMode.IDLE # 에러 시 기본값
                
                is_harvest_active = (current_bt_mode in [MissionMode.READY_TO_HARVEST, MissionMode.HARVESTING])
                
                # 1. [Mod] YOLO 결과 그리기 (동적 처리)
                # result.yolo_detections 딕셔너리에 있는 것만 그림
                for cam_name, detections in result.yolo_detections.items():

                    # 원본 이미지 가져오기
                    raw_img = result.bundle.images.get(cam_name) # zed_l 처리는 아래에서
                    if cam_name == 'zed': raw_img = result.bundle.images.get('zed_l') # 예외처리

                    # 그리기
                    annotated = visualizer.draw_yolo(
                        raw_img, 
                        detections, 
                        harvest_mode=is_harvest_active 
                    )

                    # 결과 저장 (ProcessingResult 필드에 매핑)
                    if cam_name == 'left': result.annotated_left = annotated
                    elif cam_name == 'right': result.annotated_right = annotated
                    elif 'zed' in cam_name: result.annotated_zed = annotated

                # =========================================================
                # [Fix] 2. Pipe 결과 그리기 (Overlay Logic 적용)
                # =========================================================

                if PIPE_TRACKING_SOURCE == 'right':
                    # 1. YOLO가 이미 그려놓은게 있는지 확인
                    base_img = result.annotated_right if result.annotated_right is not None else result.bundle.images.get('right')
                    
                    # 2. 그 위에 Pipe 그리기 (base_img가 None이면 visualizer 내부에서 처리)
                    result.annotated_right = visualizer.draw_pipe(base_img, result.pipe_result)

                elif PIPE_TRACKING_SOURCE == 'left':
                    base_img = result.annotated_left if result.annotated_left is not None else result.bundle.images.get('left')
                    result.annotated_left = visualizer.draw_pipe(base_img, result.pipe_result)

                else: # 'zed'
                    base_img = result.annotated_zed if result.annotated_zed is not None else result.bundle.images.get('zed_l')
                    result.annotated_zed = visualizer.draw_pipe(base_img, result.pipe_result)

                # 3. 스트리밍 서버 업데이트
                if streamer:
                    streamer.update_frames(
                        img_left=result.annotated_left,
                        img_zed=result.annotated_zed if result.annotated_zed is not None else result.bundle.images.get('zed_l'),
                        img_right=result.annotated_right if result.annotated_right is not None else result.bundle.images.get('right')
                    )
                 
            # 5. 로그 저장
            if RUNTIME_OPTIONS['save_log_json']:
                file_saver.accumulate_log(blackboard.get_vision())
            
            if RUNTIME_OPTIONS['video_save']:
                file_saver.save_video_frame(result)
                
            file_saver.append_csv_log(result)

        except Empty:
            # === [수정 2] 대기 중 Heartbeat 갱신 ===
            # 데이터가 안 들어와도 "나 살아있어!" 신호는 보내야 함
            try:
                current_sys = blackboard.get_system()
                current_sys.connection.vision_last_beat = time.time()
                blackboard.update_system(current_sys)
            except Exception:
                pass # 종료 과정 등에서 에러 무시
            continue
        
        except Exception as e:
            print(f"[Save] ❌ 저장 중 에러: {e}")
            if SHUTDOWN_EVENT.is_set(): break

    # 종료 시 잔여 버퍼 비우기
    if RUNTIME_OPTIONS['save_log_json']: 
        file_saver.save_final_json()
    print("[Save] 스레드 종료.")


def main():
    """MCVS 메인 실행 진입점"""
    
    # 1. 큐 및 공유 객체(Blackboard) 생성
    inference_queue = Queue(maxsize=SYSTEM_SETTINGS['inference_buffer'])
    save_queue = Queue(maxsize=SYSTEM_SETTINGS['save_buffer'])
    
    # ==========================================================================
    # [Smart Blackboard Initialization]
    # 서버가 켜져 있으면 '공유 Blackboard'를 가져오고,
    # 서버가 꺼져 있거나 연결 실패하면 '로컬 Blackboard'를 생성합니다.
    # ==========================================================================
    shared_blackboard = None
    
    if IPC_AVAILABLE:
        try:
            print("[Main] IPC 서버 연결 시도...", end=' ')
            shared_blackboard = get_shared_blackboard()
            print("✅ 성공! (공유 모드)")
        except Exception as e:
            print(f"❌ 실패 ({e})")
            print("[Main] ⚠️ IPC 서버를 찾을 수 없습니다. 독립 실행(Standalone) 모드로 시작합니다.")
            shared_blackboard = Blackboard() # 로컬 생성
    else:
        print("[Main] IPC 모듈 없음. 독립 실행(Standalone) 모드로 시작합니다.")
        shared_blackboard = Blackboard() # 로컬 생성
    # ==========================================================================

    stats = StatsCollector()
    
    print("\n=== [MCVS] Multi-Camera Vision System 초기화 ===")
    
    # 2. 모듈 초기화
    try:
        camera_manager = CameraManager(buffer_size=SYSTEM_SETTINGS['camera_buffer'])
        synchronizer = FrameSynchronizer(['zed', 'left', 'right'], max_diff_sec=SYSTEM_SETTINGS['sync_threshold'])
        
        print(f"[Init] 모델 로드 중: {PATHS['weights']}")
        detector = YoloDetector(os.path.join(PATHS['weights'], "best.engine"), MODEL_CONF)
        pipe_tracker = PipeTracker(PIPE_ROI_COORS)
        
        file_saver = FileSaver(PATHS['output'], csv_filename=PATHS['sync_log'] if RUNTIME_OPTIONS['run_sync_test'] else None)
        visualizer = Visualizer(steering_ratios=STEERING_RATIOS, harvest_config=HARVEST_ANALYZE_CONFIG)

    except Exception as e:
        print(f"\n[Init] ❌ 초기화 치명적 실패: {e}")
        return

    # -------------------------------------------------------------
    # [Mod] 스트리밍 서버 시작 (Web View) (옵션 제어)
    # -------------------------------------------------------------
    streamer = None
    if RUNTIME_OPTIONS.get('enable_stream_server', False):
        try:
            # 보안을 위해 127.0.0.1 사용 (SSH 포트포워딩 필요)
            # 내부 네트워크를 사용하는 사람들이 모두 볼 수 있도록 하고 싶다면 0.0.0.0으로 설정
            streamer = StreamingServer(host='0.0.0.0', port=50020)
            streamer.start()
        except Exception as e:
            print(f"[Main] ⚠️ 스트리밍 서버 시작 실패: {e}")
    # -------------------------------------------------------------

    # 3. 워커 스레드 시작
    # [New] inference_worker에 blackboard 전달
    t_inference = threading.Thread(
        target=inference_worker, 
        args=(inference_queue, save_queue, detector, pipe_tracker, shared_blackboard), 
        daemon=True
    )
    t_save = threading.Thread(
        target=save_worker, 
        args=(save_queue, file_saver, visualizer, stats, shared_blackboard, streamer), 
        daemon=True
    )
    
    t_inference.start()
    t_save.start()
    
    # 4. 로거 스레드 및 카메라 시작
    SYSTEM_READY_EVENT = threading.Event()
    start_stats_logging_thread(stats, 10.0, SHUTDOWN_EVENT, SYSTEM_READY_EVENT)
    
    camera_manager.print_settings()
    camera_manager.start_all(stats)

    # 5. 카메라 워밍업
    if not camera_manager.warmup(frames=CAM_CONFIG['fps']):
        print("[Init] ❌ 카메라 워밍업 실패. 종료합니다.")
        SHUTDOWN_EVENT.set()
        return

    # 6. 추론 엔진 워밍업 (첫 실행 딜레이 방지)
    print("[Init] 추론 엔진 워밍업 중...")
    time.sleep(0.5)
    
    if wd := camera_manager.pop_frame('left'):
        detector.detect(wd[1]) # [Detect 모드 사용]
        print("[Init] 추론 엔진 워밍업 완료.")
    else:
        print("[Init] ⚠️ 워밍업 프레임 획득 실패 (무시하고 진행)")
    
    # 1. 현재 시스템 상태 가져오기
    current_sys = shared_blackboard.get_system() # 혹은 shared_blackboard.system
    # 2. 상태값 변경
    current_sys.state = SystemState.READY 
    # 3. (IPC 사용 시) 업데이트 반영
    shared_blackboard.update_system(current_sys)
    
    stats.reset_all()
    SYSTEM_READY_EVENT.set()
    print("\n=== [MCVS] 메인 루프 시작 (Ctrl+C로 종료) ===")
    
    try:
        while not SHUTDOWN_EVENT.is_set():
            # A. 모든 카메라에서 최신 프레임 획득 (Non-blocking)
            for name in ['zed', 'left', 'right']:
                if data := camera_manager.pop_frame(name):
                    synchronizer.add_frame(name, data[0], data[1])
            
            # B. 동기화된 번들 확인
            if bundle := synchronizer.get_synced_bundle():
                stats.log_sync_event(True)
                try: 
                    inference_queue.put(bundle, block=False)
                except Full: 
                    pass    # 큐가 꽉 차면 Drop (Real-time성 우선)ㄴ
            else:
                # 데이터가 없을 때는 살짝 대기하여 CPU 과점유 방지
                time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n[Main] 사용자 종료 요청 (KeyboardInterrupt)")
    except Exception as e:
        print(f"\n[Main] ❌ 메인 루프 실행 중 에러: {e}")
        shared_blackboard.system.state = SystemState.ERROR
    finally:
        print("\n=== [MCVS] 시스템 종료 절차 시작 ===")
        SHUTDOWN_EVENT.set()    # 종료 이벤트 전파
        
        try:
            print("[Shutdown] 카메라 정지 중...")
            # 카메라가 이미 죽어있을 때 여기서 오래 걸릴 수 있음
            camera_manager.stop_all()
            
            print("[Shutdown] 워커 스레드 대기 중...")
            t_inference.join(timeout=2.0)
            t_save.join(timeout=2.0)
            
            print("[Shutdown] 파일 저장 마무리 중...")
            file_saver.close()
        
        except Exception as e:
            print(f"[Shutdown] ⚠️ 정리 작업 중 에러 발생: {e}")

        print("[Shutdown] 모든 작업 완료. 프로세스를 종료합니다.")

        # [핵심] 좀비 프로세스 방지를 위한 강제 종료
        # V4L2 드라이버가 꼬여서 메인 스레드가 안 죽는 경우를 대비해 os._exit 호출
        # 0: 정상 종료, 1: 에러 종료
        os._exit(0)

if __name__ == "__main__":
    main()