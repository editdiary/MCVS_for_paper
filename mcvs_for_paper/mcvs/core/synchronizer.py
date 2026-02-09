# core/synchronizer.py

import time
from collections import deque
from typing import Optional, Dict, Any, List
from mcvs.core.data_types import FrameBundle

class FrameSynchronizer:
    """
    여러 카메라의 프레임을 타임스탬프 기준으로 동기화하는 클래스.
    Head-of-Line Blocking 방식을 사용하여 가장 오래된 프레임을 기준으로 정렬합니다.
    """
    def __init__(self, camera_names: List[str], max_diff_sec: float = 0.07):
        self.camera_names = camera_names
        self.max_diff_sec = max_diff_sec
        self.queues: Dict[str, deque] = {name: deque() for name in camera_names}
        
        # 내부 디버깅용 카운터
        self.sync_success_count = 0
        self.sync_fail_count = 0

    def add_frame(self, cam_name: str, timestamp: float, frame_data: Any):
        """카메라 스레드에서 획득한 데이터를 대기 큐에 삽입"""
        if cam_name in self.queues:
            self.queues[cam_name].append((timestamp, frame_data))

    def get_synced_bundle(self) -> Optional[FrameBundle]:
        """
        동기화된 프레임 번들을 반환합니다.
        조건 불만족 시(데이터 부족 or 동기화 실패) None을 반환하고 내부적으로 오래된 프레임을 버립니다.
        """
        # 1. 데이터 준비 확인
        if not all(self.queues[name] for name in self.camera_names):
            return None

        # 2. 각 큐의 Head(가장 오래된) 타임스탬프 비교
        heads = {name: self.queues[name][0] for name in self.camera_names}
        ts_list = [h[0] for h in heads.values()]
        
        min_ts = min(ts_list)
        max_ts = max(ts_list)

        # 3. 동기화 판정 (최대 시차 이내인지 판단)
        if (max_ts - min_ts) <= self.max_diff_sec:
            self.sync_success_count += 1
            
            final_timestamps = {}
            final_images = {}
            
            # 큐에서 데이터 확정(Pop) 및 패키징ㄴ
            for name in self.camera_names:
                ts, data = self.queues[name].popleft()
                final_timestamps[name] = ts
                
                # ZED 스테레오 이미지 처리
                if name == 'zed': 
                    final_images['zed_l'], final_images['zed_r'] = data
                else:
                    final_images[name] = data

            return FrameBundle(
                sync_id=str(time.time_ns()),
                timestamps=final_timestamps,
                images=final_images
            )
        
        else:
            # 4. 동기화 실패: 가장 뒤처진(오래된) 프레임 폐기 (Catch-up)
            self.sync_fail_count += 1
            for name in self.camera_names:
                if heads[name][0] == min_ts:
                    self.queues[name].popleft()
                    break
            
            return None