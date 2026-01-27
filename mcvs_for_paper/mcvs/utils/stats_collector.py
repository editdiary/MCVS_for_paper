# utils/stats_collector.py

import threading
import time
from typing import Dict

class StatsCollector:
    """
    시스템 성능(FPS, 동기화율 등)을 스레드 안전하게 수집하는 클래스.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.reset_all()    # 초기화 로직 통합
    
    def reset_all(self):
        """모든 카운터와 타이머를 리셋합니다."""
        with self.lock:
            self.start_time = time.time()
            self.cam_frames = {'zed': 0, 'left': 0, 'right': 0}
            self.sync_success = 0
            self.sync_fail = 0
            self.inference_received = 0
            self.objects_detected = 0

    def log_cam_frame(self, cam_name: str):
        with self.lock:
            if cam_name in self.cam_frames:
                self.cam_frames[cam_name] += 1

    def log_sync_event(self, success: bool = True):
        with self.lock:
            if success: self.sync_success += 1
            else: self.sync_fail += 1

    def log_inference_received(self):
        with self.lock:
            self.inference_received += 1
            
    def log_yolo_detection(self, object_count: int):
        with self.lock:
            self.objects_detected += object_count

    def get_and_reset_stats(self) -> Dict:
        """현재까지의 통계를 반환하고 카운터를 즉시 리셋합니다 (주기적 호출용)."""
        with self.lock:
            now = time.time()
            elapsed = now - self.start_time
            if elapsed < 0.001: elapsed = 0.001 # 0 나누기 방지
            
            stats = {
                "elapsed_sec": elapsed,
                "cam_frames": self.cam_frames.copy(),
                "sync_success": self.sync_success,
                "sync_fail": self.sync_fail,
                "inference_received": self.inference_received,
                "objects_detected": self.objects_detected,
            }
            
            # Reset Counters (start_time 갱신 포함)
            self.start_time = now
            self.cam_frames = {k: 0 for k in self.cam_frames}
            self.sync_success = 0
            self.sync_fail = 0
            self.inference_received = 0
            self.objects_detected = 0
            
            return stats

def start_stats_logging_thread(stats_collector: StatsCollector, 
                               interval_sec: float, 
                               shutdown_event: threading.Event, 
                               ready_event: threading.Event = None):
    """
    백그라운드에서 통계를 출력하는 스레드를 시작합니다.
    """
    def _loop():
        # 시스템 준비 대기
        if ready_event:
            ready_event.wait()

        print(f"[StatsLogger] 통계 수집 시작 (Interval: {interval_sec}s)")
        stats_collector.reset_all()
        
        while not shutdown_event.is_set():
            if shutdown_event.wait(timeout=interval_sec):
                break
            
            stats = stats_collector.get_and_reset_stats()
            elapsed = stats["elapsed_sec"]
            
            # Format Output
            cam_fps = [f"{k}:{v/elapsed:.1f}" for k, v in stats["cam_frames"].items()]
            sync_total = stats["sync_success"] + stats["sync_fail"]
            sync_rate = (stats["sync_success"] / sync_total * 100) if sync_total > 0 else 0.0
            infer_fps = stats["inference_received"] / elapsed
            
            print(f"[Stats] {elapsed:.1f}s | CamFPS: {cam_fps} | Sync: {sync_rate:.1f}% | Infer: {infer_fps:.1f}/s")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t