# mcvs/main.py

import sys
import os
import threading
import time
from typing import Tuple
import csv
from pathlib import Path
from queue import Queue, Full, Empty

# Project Root Setup (상위 폴더 import 가능하게 설정)
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.append(str(project_root))

# Import Custom Modules
from mcvs.utils.config import *
from mcvs.core.data_types import FrameBundle, ProcessingResult
from mcvs.core.camera_manager import CameraManager
from mcvs.core.synchronizer import FrameSynchronizer
from mcvs.modules.detector import YoloDetector
from mcvs.utils.file_io import FileSaver
from mcvs.utils.visualizer import Visualizer
from mcvs.utils.stats_collector import StatsCollector, start_stats_logging_thread
from mcvs.utils.stream_server import StreamingServer

# Blackboard Imports
from common.blackboard import (
    VisionPerception, TotalObject, ObjectObservation, ObjectLogic, ObjectSource
)

# 전역 종료 이벤트
SHUTDOWN_EVENT = threading.Event()

def inference_worker(input_queue: Queue, output_queue: Queue, 
                     detector: YoloDetector):
    """
    [Consumer 1] 동기화된 프레임 번들을 받아 비동기 병렬 추론을 수행합니다.
    - GPU: Object Detection (tensorrt)
    """
    print("[Inference] 추론 스레드 시작 (Ready)")

    # [Add] DLA 실험 데이터를 모아둘 리스트 생성
    latency_log = []
    frame_count = 0

    while not SHUTDOWN_EVENT.is_set():
        try:
            bundle: FrameBundle = input_queue.get(timeout=1.0)
            yolo_results_dict = {}

            # =========================================================
            # [수정] Batch Inference 대신 '개별 추론'으로 변경
            # (Tracker ID 꼬임 방지 및 len() 에러 해결)
            # =========================================================
            for cam_name in DETECTION_TARGETS:
                img = bundle.images.get(cam_name)
                if img is not None and img.size > 0:
                    try:
                        # [Add] 정밀한 추론 시간 측정 시작
                        start_time = time.perf_counter()

                        # 이미지를 하나씩 넣어서 리스트 형태(List[YoloResult])로 정확히 반환받음
                        dets = detector.track(img)

                        # [Add] 추론 시간 측정 종료 및 출력 (밀리초 단위)
                        end_time = time.perf_counter()
                        infer_time_ms = (end_time - start_time) * 1000
                        # 리스트에 (프레임 번호, 카메라 이름, 추론 시간) 저장
                        latency_log.append((frame_count, cam_name, round(infer_time_ms, 3)))

                        yolo_results_dict[cam_name] = dets
                    except Exception as e:
                        print(f"[Inference] ⚠️ 추론 에러 ({cam_name}): {e}")
            
            frame_count += 1

            result = ProcessingResult(
                bundle=bundle,
                yolo_detections=yolo_results_dict
            )
            
            try: output_queue.put(result, block=False)
            except Full: pass

        except Empty: continue
        except Exception as e: 
            print(f"[Inference] ❌ 스레드 에러: {e}")
            if SHUTDOWN_EVENT.is_set(): break

    #print("[Inference] 스레드 종료.")

    # 스레드 종료 시점에 모아둔 데이터를 CSV 파일로 한 번에 저장
    print("[Inference] 스레드 종료. 실험 데이터(추론 시간)를 저장합니다...")
    try:
        # 엔진 이름이나 시간에 따라 파일명을 다르게 주면 비교하기 좋습니다.
        log_filename = f"inference_latency_log_{int(time.time())}.csv" 
        
        with open(log_filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['frame_index', 'camera_name', 'latency_ms']) # 헤더 작성
            writer.writerows(latency_log) # 데이터 한 번에 쓰기
            
        print(f"[Inference] ✅ 추론 시간 로그 저장 완료: {log_filename}")
    except Exception as e:
        print(f"[Inference] ❌ 로그 저장 실패: {e}")

def _create_perception_data(result: ProcessingResult) -> Tuple[VisionPerception, bool]:
    """
    [Adapter] 내부 처리 결과(ProcessingResult) -> 로그 저장용 포맷(VisionPerception) 변환
    """
    perception = VisionPerception()
    perception.resolution = {
        'arducam': (CAM_CONFIG['width'], CAM_CONFIG['height']),
        'zed': (ZED_CONFIG['width'] // 2, ZED_CONFIG['height'])
    }
    
    SOURCE_MAP = {
        'left': ObjectSource.VISION_LEFT,
        'right': ObjectSource.VISION_RIGHT,
        'zed': ObjectSource.VISION_ZED,
        'zed_l': ObjectSource.VISION_ZED
    }
    
    for cam_name, detections in result.yolo_detections.items():
        if 'zed' in cam_name: 
            img_w, img_h = ZED_CONFIG['width']//2, ZED_CONFIG['height']
        else:
            img_w, img_h = CAM_CONFIG['width'], CAM_CONFIG['height']

        for d in detections:
            x1, y1, x2, y2 = d.bbox
            w, h = (x2 - x1), (y2 - y1)
            cx, cy = x1 + (w / 2.0), y1 + (h / 2.0)

            enum_source = SOURCE_MAP.get(cam_name, ObjectSource.UNKNOWN)

            obs_data = ObjectObservation(
                source=enum_source,
                track_id=f"{cam_name}_{d.track_id}" if d.track_id else "N/A", 
                confidence=float(d.conf),
                center_x=cx / img_w,        
                center_y=cy / img_h,        
                width=w / img_w,            
                height=h / img_h,           
                area_ratio=(w * h) / (img_w * img_h)
            )
        
            logic_data = ObjectLogic(
                is_candidate=False,
                is_in_trigger_zone=False,
                is_in_harvest_zone=False
            )

            perception.visible_objects.append(TotalObject(obs=obs_data, logic=logic_data))
        
    perception.total_object_count = len(perception.visible_objects)

    return perception, False

def save_worker(input_queue: Queue, file_saver: FileSaver, visualizer: Visualizer, 
                stats: StatsCollector, streamer: StreamingServer):
    """
    [Consumer 2] 로그 저장, 시각화
    - 순수하게 데이터 갱신 및 저장 역할만 수행
    """
    print("[Save] 저장 스레드 시작 (Ready)")
    
    while not SHUTDOWN_EVENT.is_set():
        try:
            result: ProcessingResult = input_queue.get(timeout=1.0)
            
            # 통계 업데이트 (모든 카메라의 탐지 개수 합산)
            total_dets = sum(len(dets) for dets in result.yolo_detections.values())
            if total_dets > 0:
                stats.log_yolo_detection(total_dets)

            # 데이터 구조화 (로그용)
            new_perception, is_triggered_now = _create_perception_data(result)
            
            # 시각화 및 스트리밍
            need_vis = (RUNTIME_OPTIONS['video_save'] or 
                        RUNTIME_OPTIONS.get('enable_stream_server', False))
            
            if need_vis:
                # YOLO 결과 그리기 (동적 처리)
                for cam_name, detections in result.yolo_detections.items():
                    raw_img = result.bundle.images.get(cam_name)
                    if cam_name == 'zed': raw_img = result.bundle.images.get('zed_l')

                    # 그리기
                    annotated = visualizer.draw_yolo(raw_img, detections)

                    if cam_name == 'left': result.annotated_left = annotated
                    elif cam_name == 'right': result.annotated_right = annotated
                    elif 'zed' in cam_name: result.annotated_zed = annotated

                # 스트리밍 서버 업데이트
                if streamer:
                    streamer.update_frames(
                        img_left=result.annotated_left if result.annotated_left is not None else result.bundle.images.get('left'),
                        img_zed=result.annotated_zed if result.annotated_zed is not None else result.bundle.images.get('zed_l'),
                        img_right=result.annotated_right if result.annotated_right is not None else result.bundle.images.get('right')
                    )
                 
            # 로그 저장
            if RUNTIME_OPTIONS['save_log_json']:
                file_saver.accumulate_log(new_perception)
            
            if RUNTIME_OPTIONS['video_save']:
                file_saver.save_video_frame(result)
                
            file_saver.append_csv_log(result)

        except Empty:
            continue
        
        except Exception as e:
            print(f"[Save] ❌ 저장 중 에러: {e}")
            if SHUTDOWN_EVENT.is_set(): break

    # 종료 시 잔여 버퍼 비우기
    if RUNTIME_OPTIONS['save_log_json']: 
        file_saver.save_final_json()
    print("[Save] 스레드 종료.")


def main():
    """MCVS 메인 실행 진입점 (실험용 Standalone)"""
    
    # 큐 생성
    inference_queue = Queue(maxsize=SYSTEM_SETTINGS['inference_buffer'])
    save_queue = Queue(maxsize=SYSTEM_SETTINGS['save_buffer'])
    
    stats = StatsCollector()
    
    print("\n=== [MCVS] Multi-Camera Vision System 초기화 ===")
    
    # 모듈 초기화
    try:
        camera_manager = CameraManager(buffer_size=SYSTEM_SETTINGS['camera_buffer'])
        synchronizer = FrameSynchronizer(['zed', 'left', 'right'], max_diff_sec=SYSTEM_SETTINGS['sync_threshold'])
        
        print(f"[Init] 모델 로드 중: {PATHS['weights']}")
        detector = YoloDetector(os.path.join(PATHS['weights'], "best.engine"), MODEL_CONF)
        
        file_saver = FileSaver(PATHS['output'], csv_filename=PATHS['sync_log'] if RUNTIME_OPTIONS['run_sync_test'] else None)
        
        visualizer = Visualizer()

    except Exception as e:
        print(f"\n[Init] ❌ 초기화 치명적 실패: {e}")
        return

    # -------------------------------------------------------------
    # 스트리밍 서버 시작 (Web View) (옵션 제어)
    # -------------------------------------------------------------
    streamer = None
    if RUNTIME_OPTIONS.get('enable_stream_server', False):
        try:
            streamer = StreamingServer(host='0.0.0.0', port=50020)
            streamer.start()
        except Exception as e:
            print(f"[Main] ⚠️ 스트리밍 서버 시작 실패: {e}")
    # -------------------------------------------------------------

    # 워커 스레드 시작
    t_inference = threading.Thread(
        target=inference_worker, 
        args=(inference_queue, save_queue, detector), 
        daemon=True
    )
    t_save = threading.Thread(
        target=save_worker, 
        args=(save_queue, file_saver, visualizer, stats, streamer), 
        daemon=True
    )
    
    t_inference.start()
    t_save.start()
    
    # 로거 스레드 및 카메라 시작
    SYSTEM_READY_EVENT = threading.Event()
    start_stats_logging_thread(stats, 10.0, SHUTDOWN_EVENT, SYSTEM_READY_EVENT)
    
    camera_manager.print_settings()
    camera_manager.start_all(stats)

    # 카메라 워밍업
    if not camera_manager.warmup(frames=CAM_CONFIG['fps']):
        print("[Init] ❌ 카메라 워밍업 실패. 종료합니다.")
        SHUTDOWN_EVENT.set()
        return

    # 추론 엔진 워밍업 (첫 실행 딜레이 방지)
    print("[Init] 추론 엔진 워밍업 중...")
    time.sleep(0.5)
    
    if wd := camera_manager.pop_frame('left'):
        detector.detect(wd[1]) # [Detect 모드 사용]
        print("[Init] 추론 엔진 워밍업 완료.")
    else:
        print("[Init] ⚠️ 워밍업 프레임 획득 실패 (무시하고 진행)")
    
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