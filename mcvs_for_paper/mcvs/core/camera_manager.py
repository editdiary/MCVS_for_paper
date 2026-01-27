# core/camera_manager.py

import cv2
import threading
import time
import numpy as np
from queue import Queue, Empty
from typing import Dict, Any, Tuple, Optional
from abc import ABC, abstractmethod

# 설정 파일 (Config)
from utils.config import CAM_CONFIG, ZED_CONFIG, CAM_SYMBOL

# ==========================================
# 1. Base Camera Node
# ==========================================
class _CameraNode(ABC):
    """
    개별 카메라 장치를 제어하는 스레드 노드.
    연결이 끊겨도 '검은 화면'을 지속적으로 송출하여 파이프라인 멈춤을 방지하고,
    백그라운드에서 재연결을 시도합니다.
    OpenCV VideoCapture를 관리하고 큐에 프레임을 적재합니다.
    """
    def __init__(self, name: str, path: str, config: dict, buf_size: int):
        self.name = name
        self.path = path
        self.config = config
        
        self.cap = None
        self.queue = Queue(maxsize=buf_size)
        self.thread = None
        self.shutdown_event = None
        self.stats = None

        # [New] 연결 상태 관리
        self.is_connected = False
        self.last_reconnect_time = 0.0
        self.RECONNECT_INTERVAL = 3.0  # 재연결 시도 간격 (초)

    def initialize(self):
        """초기 연결 시도 (실패해도 에러를 띄우지 않고 넘어감)"""
        print(f"[{self.name}] 초기화 시도: {self.path}")

        if self._connect_driver():
            print(f"[{self.name}] ✅ GStreamer 초기화 성공.")
        else:
            print(f"[{self.name}] ⚠️ 초기 연결 실패. (검은 화면 송출 및 재연결 대기)")
    
    def _connect_driver(self) -> bool:
        """실제 드라이버 연결 로직"""
        try:
            if self.cap:
                self.cap.release()
            
            # 서브클래스에서 정의한 파이프라인 가져오기
            gst_pipeline = self._get_pipeline()
            # CAP_GSTREAMER 백엔드 명시
            self.cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
        
            if self.cap.isOpened():
                self.is_connected = True
                return True
        except Exception as e:
            print(f"[{self.name}] 연결 에러: {e}")
        
        self.is_connected = False
        return False

    @abstractmethod
    def _get_pipeline(self) -> str:
        """카메라 타입별 맞춤형 파이프라인 반환"""
        pass

    @abstractmethod
    def _process_frame(self, frame: np.ndarray) -> Any:
        """Raw 프레임 후처리 (Crop, Split 등)"""
        pass

    @abstractmethod
    def _get_blank_frame(self) -> Any:
        """연결 끊김 시 전송할 검은 프레임(또는 튜플) 반환"""
        pass

    def start(self, shutdown_event: threading.Event, stats=None):
        self.shutdown_event = shutdown_event
        self.stats = stats
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def stop(self):
        # 스레드 종료 대기
        if self.thread and self.thread.is_alive(): self.thread.join(timeout=3.0)

        # 카메라 자원 해제 (Hang 방지)
        if self.cap and self.cap.isOpened():
            self.cap.release()
        print(f"[{self.name}] 연결 해제 완료.")

    def read(self, timeout: float = None) -> Any:
        """큐에서 데이터를 가져옵니다 (워밍업/테스트용)"""
        return self.queue.get(timeout=timeout)
    
    def clear_queue(self):
        with self.queue.mutex: self.queue.queue.clear()
    
    def pop_latest(self):
        """큐에서 가장 최신 데이터를 가져옴 (오래된 것 버림)"""
        while self.queue.qsize() > 1:
            try: self.queue.get_nowait()
            except Empty: break

    def _worker(self):
        """Robust Worker Loop"""
        fail_cnt = 0
        start_system_time = None
        max_fail = int(5.0 * self.config.get('fps', 15))    # 5초간 신호 없으면 에러
        frame_interval = 1.0 / self.config.get('fps', 15)

        while not self.shutdown_event.is_set():
            loop_start = time.time()

            # Case 1: 연결되어 있을 때
            if self.is_connected:
                # Grab: 하드웨어에 프레임 캡처 신호 전달
                if self.cap.grab():
                    fail_cnt = 0

                    # ============= [커널 타임스탬프 매핑] =============
                    # 1. 커널 타임스탬프(상대 시간) 가져오기
                    rel_ts_ms = self.cap.get(cv2.CAP_PROP_POS_MSEC)

                    # 2, 기준점이 없으면(첫 실행 or 재연결 직후) 현재 시스템 시간과 동기화
                    if start_system_time is None:
                        start_system_time = time.time() - (rel_ts_ms / 1000.0)

                    # 3. 절대 시각 계산 (커널 시간 기반)
                    ts = start_system_time + (rel_ts_ms / 1000.0)
                    # ===============================================

                    # Retrieve: 실제 이미지 데이터 가져오기
                    ret, raw = self.cap.retrieve()
                    if ret:
                        self._push_to_queue(ts, self._process_frame(raw))
                    else:
                        fail_cnt += 1
                else:
                    fail_cnt += 1
                    time.sleep(0.01)    # 재시도 대기 (CPU 과점유 방지)

                # 에러 누적 시 연결 끊김 판정
                if fail_cnt > max_fail:
                    print(f"[{self.name}] ❌ 신호 유실됨. 재연결 모드로 전환.")
                    self.is_connected = False

                    # [중요] 재연결 시 타임스탬프 기준점을 다시 잡기 위해 초기화
                    start_system_time = None

                    if self.cap: self.cap.release()
            
            # Case 2: 연결이 끊겨 있을 때 (Fallback Mode)
            else:
                # A. 검은 화면 송출 (시스템이 죽지 않도록)
                # 연결이 없으니 커널 시간이 없습니다. 그냥 현재 시스템 시간을 씁니다.
                # Synchronizer는 이 시간이 다른 정상 카메라 시간과 비슷하므로 통과시킵니다.
                self._push_to_queue(time.time(), self._get_blank_frame())
                
                # B. 주기적 재연결 시도
                if (time.time() - self.last_reconnect_time) > self.RECONNECT_INTERVAL:
                    self.last_reconnect_time = time.time()
                    if self._connect_driver():
                        print(f"[{self.name}] ✅ 재연결 성공!")
                        fail_cnt = 0
                        # 여기서도 명시적으로 초기화 (안전장치)
                        start_system_time = None
                
                # FPS 유지 (너무 빨리 루프 돌지 않도록)
                elapsed = time.time() - loop_start
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)
    
    def _push_to_queue(self, ts, data):
        """큐에 데이터 삽입 (Full이면 Oldest Drop)"""
        if self.queue.full():
            try: self.queue.get_nowait()
            except Empty: pass
        
        self.queue.put((ts, data))
        if self.stats: self.stats.log_cam_frame(self.name)

# ==========================================
# 2. Camera Implementations
# ==========================================
# [TODO] GSTREAMER에서 무슨 가속화 설정도 할 수 있다고 하지 않았나?
class _ArduCamNode(_CameraNode):
    def _get_pipeline(self):
        # ArduCam은 MJPG 지원하므로 jpegdec 사용
        return (
            f"v4l2src device={self.path} ! "
            f"image/jpeg, width={self.config['width']}, height={self.config['height']}, framerate={self.config['fps']}/1 ! "
            f"jpegdec ! videoconvert ! video/x-raw, format=BGR ! appsink drop=True max-buffers=1 sync=False"
        )

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        return frame
    
    def _get_blank_frame(self) -> np.ndarray:
        # ArduCam 해상도에 맞는 검은 화면 생성
        return np.zeros((self.config['height'], self.config['width'], 3), dtype=np.uint8)

class _ZedCamNode(_CameraNode):
    def _get_pipeline(self):
        # ZED는 YUYV만 지원하므로 video/x-raw 사용
        # [주의] width는 반드시 2560 (720p SBS 기준)이어야 함
        return (
            f"v4l2src device={self.path} ! "
            f"video/x-raw, width={self.config['width']}, height={self.config['height']}, framerate={self.config['fps']}/1 ! "
            f"videoconvert ! video/x-raw, format=BGR ! appsink drop=True max-buffers=1 sync=False"
        )

    def _process_frame(self, frame: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        # SBS 이미지를 반으로 갈라 Left/Right 추출
        half_w = frame.shape[1] // 2
        return (frame[:, :half_w].copy(), frame[:, half_w:].copy())
    
    def _get_blank_frame(self) -> Tuple[np.ndarray, np.ndarray]:
        # ZED는 (Left, Right) 튜플을 반환해야 함
        # config['width']는 2560이므로 반쪽은 1280
        h = self.config['height']
        w = self.config['width'] // 2
        blank = np.zeros((h, w, 3), dtype=np.uint8)
        return (blank, blank)

# ==========================================
# 3. Camera Manager
# ==========================================
class CameraManager:
    """
    모든 카메라 노드를 생성, 초기화 및 제어하는 매니저 클래스.
    """
    def __init__(self, buffer_size: int = 3):
        self.nodes = {}
        self.shutdown = threading.Event()
        
        # [Mod] 초기화 실패 시 raise 하지 않고 로그만 남김 (노드 내부에서 처리)
        try:
            # 노드 생성 (설정값 주입)
            self.nodes['left'] = _ArduCamNode('left', CAM_SYMBOL['left_cam'], CAM_CONFIG, buffer_size)
            self.nodes['right'] = _ArduCamNode('right', CAM_SYMBOL['right_cam'], CAM_CONFIG, buffer_size)
            self.nodes['zed'] = _ZedCamNode('zed', CAM_SYMBOL['zed_cam'], ZED_CONFIG, buffer_size)

            # 초기화 실행
            for node in self.nodes.values(): node.initialize()

        except Exception as e:
            print(f"[CameraManager] ⚠️ 매니저 초기화 중 예외 발생 (일부 카메라가 없을 수 있음): {e}")

    def start_all(self, stats=None):
        print("[CameraManager] 모든 카메라 스레드 시작")
        for node in self.nodes.values(): node.start(self.shutdown, stats)

    def stop_all(self):
        print("[CameraManager] 카메라 종료 요청...")
        self.shutdown.set()
        for node in self.nodes.values(): node.stop()
        
    def warmup(self, frames=30):
        """
        [수정됨] 카메라 센서 안정화 (Auto-Exposure 등)를 위해 실제 데이터를 소비합니다.
        - 연결된 카메라: 실제 이미지를 꺼내 버림으로써 하드웨어 버퍼를 비움.
        - 끊긴 카메라: 검은 화면(Fake)을 꺼내 버림.
        - 실패 시: 시스템을 끄지 않고 경고만 출력.
        """
        print(f"[CameraManager] 워밍업 및 센서 안정화 시작 ({frames} frames)...")
        timeout = 2.0
        
        # 1. 실제로 큐에서 데이터를 빼냄 (센서가 계속 찍게 유도)
        for i in range(frames):
            for name, node in self.nodes.items():
                try:
                    # 큐에서 데이터를 꺼냄 (Worker가 열심히 채우는 중)
                    node.read(timeout=timeout)
                except Empty:
                    # [Mod] 여기서 return False를 하지 않음
                    print(f"[CameraManager] ⚠️ 워밍업 지연: '{name}' 데이터 안 옴 (무시하고 진행)")
                except Exception as e:
                    print(f"[CameraManager] ⚠️ 워밍업 중 '{name}' 에러: {e}")
        
        # 2. 큐 초기화 (Clean Start)
        try:
            for node in self.nodes.values(): 
                node.clear_queue()
            print("[CameraManager] ✅ 워밍업 및 큐 초기화 완료.")
            return True # 무조건 성공으로 간주
        except Exception as e:
            print(f"[CameraManager] 큐 초기화 중 에러: {e}")
            return True # 에러가 나도 일단 진행

    def print_settings(self):
        """
        [수정됨] 연결된 카메라는 상세 정보를, 끊긴 카메라는 상태 메시지를 출력
        """
        print("\n=== Camera Settings ===")
        for name, node in self.nodes.items():
            # 1. 연결되어 있고, 캡처 객체가 살아있는 경우
            if node.is_connected and node.cap and node.cap.isOpened():
                w = int(node.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(node.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = int(node.cap.get(cv2.CAP_PROP_FPS))
                print(f"  > {name.upper()}: {w}x{h} @ {fps}fps (🟢 Active)")
            
            # 2. 연결이 끊겨서 재연결 시도 중인 경우
            else:
                print(f"  > {name.upper()}: 🔴 Disconnected (Auto-Retry Mode)")
        print("=======================\n")

    def pop_frame(self, name: str) -> Any:
        """Main Loop에서 사용하는 Non-blocking 데이터 획득 함수"""
        try:
            return self.nodes[name].queue.get_nowait()
        except (KeyError, Empty):
            return None