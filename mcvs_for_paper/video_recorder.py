# mcvs/main.py

import sys
import os
import threading
import time
import cv2
import signal  # 추가
from pathlib import Path
from queue import Queue, Full, Empty
import numpy as np
from multiprocessing import Pool

# 현재 파일(mcvs_recorder.py)의 부모 폴더(최상위 루트)를 검색 경로에 추가
# 이렇게 하면 파이썬이 mcvs 폴더를 인식할 수 있게 됩니다.
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

# Import Custom Modules
from mcvs.utils.config import *
from mcvs.core.data_types import FrameBundle, ProcessingResult, PipeResult
from mcvs.core.camera_manager import CameraManager
from mcvs.core.synchronizer import FrameSynchronizer
from mcvs.utils.file_io import FileSaver
from mcvs.utils.stats_collector import StatsCollector, start_stats_logging_thread
from mcvs.utils.stream_server import StreamingServer

# 전역 종료 이벤트
SHUTDOWN_EVENT = threading.Event()

# 1. 실제 파일 쓰기를 담당하는 독립된 함수 (다른 프로세스에서 실행됨)
def _write_image_task(args):
    file_path, img, quality = args
    cv2.imwrite(file_path, img, [cv2.IMWRITE_PNG_COMPRESSION, quality])

def save_worker(input_queue: Queue, file_saver: FileSaver,
                stats: StatsCollector, save_mode: str, streamer: StreamingServer):
    """
    [Consumer] save_mode에 따라 이미지, 동영상 저장 또는 로그만 기록합니다.
    """
    # [수정] output_path 대신 file_saver.output_dir를 사용합니다.
    output_path = file_saver.output_dir
    print(f"[Save] 💾 저장 워커 시작 (Mode: {save_mode})")

    # [개선] CPU 코어 수에 맞춰 프로세스 풀 생성 (예: 4개 코어 활용)
    # JPEG 인코딩 부하를 여러 코어로 분산합니다.
    # [수정] 자식 프로세스들이 Ctrl+C(SIGINT)를 무시하도록 초기화 설정
    pool = Pool(
        processes=4, 
        initializer=signal.signal, 
        initargs=(signal.SIGINT, signal.SIG_IGN)
    )

    # 1. 이미지 모드일 때만 폴더 미리 생성
    if save_mode == "IMAGE":
        save_targets = ['left', 'right', 'zed_l', 'zed_r']
        for cam in save_targets:
            os.makedirs(os.path.join(output_path, cam), exist_ok=True)

    while not SHUTDOWN_EVENT.is_set() or not input_queue.empty():
        try:
            bundle: FrameBundle = input_queue.get(timeout=1.0)

            # FileSaver 호환성을 위해 ProcessingResult 생성
            temp_result = ProcessingResult(
                bundle=bundle, 
                yolo_detections={}, 
                pipe_result=PipeResult()
            )

            # 2. 미디어(이미지/동영상) 저장 분기
            if save_mode == "IMAGE":
                tasks = []
                for cam_name, img in bundle.images.items():
                    if img is None: continue
                    file_name = f"{bundle.sync_id}_{cam_name}.png"
                    save_file = os.path.join(output_path, cam_name, file_name)

                    # 작업을 동기적으로 실행하지 않고 튜플로 묶어 풀에 던집니다.
                    tasks.append((save_file, img, 3))
                
                # 비동기적으로 여러 코어에서 동시 인코딩 및 저장
                pool.map_async(_write_image_task, tasks)

            elif save_mode == "VIDEO":
                file_saver.save_video_frame(temp_result)

            # 3. [공통] 동기화 분석 로그(CSV) 기록
            # 이 부분은 save_mode가 "NONE"이어도 항상 실행됩니다.
            file_saver.append_csv_log(temp_result)
            stats.log_sync_event(True)

            # [Add] 웹 스트리밍 뷰어 업데이트
            if streamer:
                streamer.update_frames(
                    img_left=bundle.images.get('left'),
                    img_zed=bundle.images.get('zed_l'),
                    img_right=bundle.images.get('right')
                )

        except Empty:
            continue
        except Exception as e:
            print(f"[Save] ❌ 이미지 저장 에러: {e}")
    
    # 종료 시 풀 정리
    pool.close()
    pool.join()

def main():
    # ==========================================
    # [설정 항목]
    # "IMAGE" : 이미지 개별 저장
    # "VIDEO" : 동영상(.mp4) 저장
    # "NONE"  : 미디어 저장 안 함 (CSV 로그만 기록)
    # ==========================================
    SAVE_MODE = "IMAGE"  
    SAVE_INTERVAL = 2.0
    last_save_time = 0.0  # [추가] 초기값 설정 필요

    # CSV 로그가 파일에 기록되도록 설정 확인
    RUNTIME_OPTIONS['run_sync_test'] = True

    # 동영상 모드일 경우 필요한 설정
    if SAVE_MODE == "VIDEO":
        RUNTIME_OPTIONS['video_save'] = True
        RUNTIME_OPTIONS['video_channels'] = {'left': True, 'right': True, 'zed': True, 'combined': True}
    else:
        RUNTIME_OPTIONS['video_save'] = False

    # 1. 큐 초기화 (저장량이 많으므로 버퍼를 충분히 확보)
    save_queue = Queue(maxsize=100)
    stats = StatsCollector()
    SYSTEM_READY_EVENT = threading.Event() # [추가] 로거용 이벤트

    # 2. 로거 스레드 시작 (10초 주기로 stats 출력)
    # [추가] SHUTDOWN_EVENT를 공유하여 종료 시 함께 멈추도록 설정
    start_stats_logging_thread(stats, 10.0, SHUTDOWN_EVENT, SYSTEM_READY_EVENT)
    
    print("\n===== [MCVS] 데이터 수집 모드 (Photo Mode) 시작 =====")
    
    try:
        # 1. 모듈 초기화 (추론기 제외)
        camera_manager = CameraManager(buffer_size=SYSTEM_SETTINGS['camera_buffer'])
        # 3대 카메라 동기화 설정
        synchronizer = FrameSynchronizer(['zed', 'left', 'right'], max_diff_sec=SYSTEM_SETTINGS['sync_threshold'])

        # 출력 경로 설정 (timestamp를 붙여 폴더 중복 방지)
        session_name = f"record_{time.strftime('%Y%m%d_%H%M%S')}"
        output_path = os.path.join(PATHS['output'], session_name)
        file_saver = FileSaver(
            output_path, 
            csv_filename=f"sync_quality_{session_name}.csv" if RUNTIME_OPTIONS['run_sync_test'] else None
        )

        camera_manager.print_settings()

        # [Add] 제거했던 스트리밍 서버(뷰파인더) 기능 복구
        streamer = None
        if RUNTIME_OPTIONS.get('enable_stream_server', True):
            try:
                streamer = StreamingServer(host='0.0.0.0', port=50020)
                streamer.start()
                print("[Main] 📺 실시간 웹 뷰어 실행 완료! (포트: 50020)")
            except Exception as e:
                print(f"[Main] ⚠️ 스트리밍 서버 시작 실패: {e}")

    except Exception as e:
        print(f"\n[Init] ❌ 초기화 치명적 실패: {e}")
        return

    # 2. 저장 워커 스레드 시작
    t_save = threading.Thread(
        target=save_worker, 
        args=(save_queue, file_saver, stats, SAVE_MODE, streamer), 
        daemon=True
    )
    t_save.start()
    
    # 3. 카메라 시작 및 워밍업
    camera_manager.start_all(stats)

    print("[Main] 카메라 안정화 대기 중...")
    warmup_frames = CAM_CONFIG['fps'] * 2
    if not camera_manager.warmup(frames=warmup_frames):
        print("[Init] ❌ 카메라 워밍업 실패. 종료합니다.")
        SHUTDOWN_EVENT.set()
        return

    SYSTEM_READY_EVENT.set()
    print(f"\n[Main] 🔴 녹화 시작! (설정 저장 간격: {SAVE_INTERVAL}s)")
    print("[Main] 종료하려면 'Ctrl+C'를 누르세요.")
    
    try:
        while not SHUTDOWN_EVENT.is_set():
            # A. 모든 카메라에서 최신 프레임 획득 (Non-blocking)
            for name in ['zed', 'left', 'right']:
                if data := camera_manager.pop_frame(name):
                    synchronizer.add_frame(name, data[0], data[1])
            
            # B. 동기화된 번들 확인
            if bundle := synchronizer.get_synced_bundle():
                current_time = time.time()

                # C. 저장 모드에 따른 분기 처리
                if SAVE_MODE == "VIDEO" or SAVE_MODE == "NONE":
                    # [Mod] 동영상은 15FPS가 유지되어야 하므로 들어오는 모든 프레임을 저장
                    try:
                        save_queue.put(bundle, block=False)
                    except Full:
                        pass    # 큐가 꽉 차면 Drop (최신성 유지)
                
                elif SAVE_MODE == "IMAGE":
                    # [Mod] 이미지 모드는 설정한 주기(SAVE_INTERVAL)마다 한 번씩만 통과시킴
                    if current_time - last_save_time >= SAVE_INTERVAL:
                        try:
                            # 저장 큐로 전달
                            save_queue.put(bundle, block=False)
                            last_save_time = current_time   # 저장 시점 업데이트
                        except Full: 
                            pass    # 저장 속도가 느릴 경우 프레임 드랍 (최신성 유지)
            else:
                # 데이터가 없을 때는 살짝 대기하여 CPU 과점유 방지
                time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n[Main] 사용자에 의해 촬영이 중단되었습니다.")
    finally:
        print("\n=== [MCVS] 시스템 종료 절차 시작 ===")
        SHUTDOWN_EVENT.set()    # 종료 이벤트 전파
        
        try:
            print("[Shutdown] 카메라 정지 중...")
            # 카메라가 이미 죽어있을 때 여기서 오래 걸릴 수 있음
            camera_manager.stop_all()
            
            print("[Shutdown] 파일 저장 마무리 중...")
            file_saver.close()
            print("[Main] 모든 데이터가 안전하게 저장되었습니다.")
        
        except Exception as e:
            print(f"[Shutdown] ⚠️ 정리 작업 중 에러 발생: {e}")

        print("[Shutdown] 모든 작업 완료. 프로세스를 종료합니다.")
        os._exit(0)

if __name__ == "__main__":
    main()