# common/blackboardV2.py

import time
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from enum import Enum, auto

# ==============================================================================
# 1. ENUMS (상태 및 명령 정의)
# ==============================================================================

class SystemState(Enum):
    """전체 시스템의 생명주기 상태"""
    BOOTING = auto()        # 부팅 중
    READY = auto()          # 정상 작동 대기
    ERROR = auto()          # 에러 발생
    EMERGENCY_STOP = auto() # 비상 정지

class MissionMode(Enum):
    """[BT] 로봇의 최상위 행동 모드"""
    IDLE = auto()               # 0. 대기
    NAVIGATING = auto()         # 1. 주행 (파이프 추종)
    READY_TO_HARVEST = auto()   # 2. 수확 준비 (정지/검증)
    HARVESTING = auto()         # 3. 수확 중 (Arm 제어)
    STANDBY = auto()            # 4. 안전 정지
    EMERGENCY = auto()          # 5. 비상

class VisionCommand(Enum):
    """[BT -> Vision] 비전 시스템 제어 명령"""
    OFF = auto()            # 꺼짐
    SCANNING = auto()       # 탐색 (Inference ON, 15FPS)
    STREAM_ONLY = auto()    # 스트리밍만 (Inference OFF)
    BURST_VERIFY = auto()   # 정밀 검증 (데이터 누적)

class MotionState(Enum):
    """[Base] 4족 보행 로봇의 자세 모드"""
    SIT = auto()            # 앉기 (주행 불가)
    STAND = auto()          # 서기 (주행 가능)
    WALKING = auto()        # 걷기

# class ObjectSource(Enum):
#     """객체 탐지 출처 (혹시나 향후 확장성을 위함)"""
#     GLOBAL_VISION = auto()  # 메인 카메라 (ZED, Arducam)
#     ARM_CAMERA = auto()     # 핸드 카메라 (Eye-in-Hand)

class ObjectSource(Enum):
    """객체 탐지 출처 (구체화됨)"""
    # [Mod] 기존 GLOBAL_VISION 대신 구체적인 센서명 사용
    VISION_LEFT = auto()    # Arducam Left
    VISION_RIGHT = auto()   # Arducam Right
    VISION_ZED = auto()     # ZED Camera
    
    ARM_CAMERA = auto()     # 핸드 카메라 (Eye-in-Hand)
    UNKNOWN = auto()        # 예외 처리용

class UserResponse(Enum):
    """사용자 인터랙션 응답"""
    NONE = auto()       # 응답 대기 중
    APPROVE = auto()    # 승인 (Yes)
    REJECT = auto()     # 거절 (No)
    
class PipePosition(Enum):
    """로봇 조향 명령"""
    CENTER = auto()
    SLIGHT_LEFT = auto()    # 약간 왼쪽
    SLIGHT_RIGHT = auto()   # 우회전 (약)
    HARD_LEFT = auto()      # 좌회전 (강)
    HARD_RIGHT = auto()     # 우회전 (강)
    NONE = auto()           # 라인 없음/정지

# ==============================================================================
# 2. DATA CLASSES - VISION (탐지 영역)
# ==============================================================================

@dataclass
class ObjectObservation:
    """[Vision] 센서가 본 Raw Data"""
    source: ObjectSource = ObjectSource.UNKNOWN
    track_id: str = "N/A"       # 트래킹 ID
    confidence: float = 0.0     # YOLO 인식 신뢰도
    
    # 정규화된 좌표 (0.0 ~ 1.0)
    center_x: float = 0.0
    center_y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    area_ratio: float = 0.0     # 화면 내 점유율 (크기)

@dataclass
class ObjectLogic:
    """[Vision -> BT] Vision 단계에서 계산된 논리 플래그"""
    is_candidate: bool = False          # 1차 필터링 (크기, ROI 등) 통과 여부
    is_in_trigger_zone: bool = False    # 중앙 정지 유도 구역에 있는가?
    is_in_harvest_zone: bool = False    # 작업 가능 구역(Workspce)에 있는가?

@dataclass
class TotalObject:
    """
    [Vision Output] 화면에 탐지된 모든 객체 (오탐지 포함)
    Vision 프로세스는 이 리스트를 갱신합니다.
    """
    obs: ObjectObservation = field(default_factory=ObjectObservation)
    logic: ObjectLogic = field(default_factory=ObjectLogic)

@dataclass
class VisionPerception:
    """[Process: Vision] 비전 시스템의 산출물"""
    # [상태 피드백] Vision이 현재 실제로 수행 중인 상태 (Actual State)
    # BT가 내린 명령(VisionCommand)을 잘 수행하고 있는지 확인용
    current_state: VisionCommand = VisionCommand.OFF
    resolution: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    
    # 1. Pipe (Navigation)
    is_pipe_detected: bool = False
    pipe_lateral_error: float = 0.0     # -1.0(L) ~ 0.0(C) ~ 1.0(R)
    pipe_position: PipePosition = PipePosition.NONE     # 현재 파이프의 영역

    # [New] 정밀 제어를 위한 추가 정보 (승운님 요청)
    pipe_angle: float = 0.0     # 파이프 기울기 (단위: degree, 90도=수직, <90:좌기울임, >90:우기울임)
    
    # 파이프 벡터 (정규화 좌표: 0.0 ~ 1.0)
    # Start: 로봇과 가까운 점 (이미지 하단), End: 로봇과 먼 점 (이미지 상단)
    pipe_start_point: Tuple[float, float] = (0.0, 0.0) 
    pipe_end_point: Tuple[float, float] = (0.0, 0.0)
    
    # 2. Object (Raw List)
    total_object_count: int = 0
    visible_objects: List[TotalObject] = field(default_factory=list)

# ==============================================================================
# 3. DATA CLASSES - HARDWARE (제어 영역)
# ==============================================================================

@dataclass
class ConnectionStatus:
    """각 모듈의 통신 건전성(Health) 체크"""
    # 마지막으로 데이터를 수신한 시각 (time.time())
    vision_last_beat: float = 0.0
    arm_last_beat: float = 0.0
    base_last_beat: float = 0.0
    
    # 임계값 (초)
    TIMEOUT_LIMIT: float = 3.0

    @property
    def is_vision_alive(self) -> bool:
        return (time.time() - self.vision_last_beat) < self.TIMEOUT_LIMIT

    @property
    def is_arm_alive(self) -> bool:
        return (time.time() - self.arm_last_beat) < self.TIMEOUT_LIMIT
        
    @property
    def is_base_alive(self) -> bool:
        return (time.time() - self.base_last_beat) < self.TIMEOUT_LIMIT

@dataclass
class ArmStatus:
    """[Process: Arm] 매니퓰레이터 상태"""
    is_busy: bool = False   # 로봇암이 움직이는 중인가?
    
    # [중요] 수확 사이클 완료 신호 (Arm -> BT)
    # BT는 이 값이 True가 될 때까지 Wait 상태 유지
    is_cycle_finished: bool = False

@dataclass
class BaseStatus:
    """[Process: Base] 4족 보행 로봇 상태"""
    motion_state: MotionState = MotionState.STAND
    is_moving: bool = False                 # 실제 이동 중인가?
    
@dataclass
class SystemStatus:
    """[Hardware Integration] 하드웨어 및 통신 상태 통합"""
    state: SystemState = SystemState.BOOTING
    
    # 통신 상태
    connection: ConnectionStatus = field(default_factory=ConnectionStatus)
    
    # 하위 하드웨어 프로세스 상태
    arm: ArmStatus = field(default_factory=ArmStatus)
    base: BaseStatus = field(default_factory=BaseStatus)

# ==============================================================================
# 4. DATA CLASSES - MISSION (판단 영역)
# ==============================================================================

@dataclass
class ChamoeObject:
    """
    [Verified Target] BT가 검증하고 Arm에게 전달할 최종 타겟
    Vision의 TotalObject 중 '진짜'로 판별된 것만 이 형태로 변환되어 리스트에 담김.
    """
    priority: int = 0           # 수확 순서 (낮을수록 먼저)
    score: float = 0.0          # 종합 점수 (높을수록 좋음: Confidence + Centrality + Size)
    
    # Arm이 수확에 필요한 핵심 정보만 남김
    center_x: float = 0.0
    center_y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    confidence: float = 0.0     # 참고용

@dataclass
class UserInteraction:
    """[BT <-> User] 사용자 승인/거절 요청 및 상태"""
    is_waiting_for_input: bool = False  # 현재 사용자 입력을 기다리는 중인가?
    request_type: str = "NONE"          # 요청 종류 (예: "START_HARVEST", "FINISH_HARVEST", "RETRY")
    message: str = ""                   # 사용자에게 보여줄 안내 메시지 (예: "3개 발견. 수확할까요?")
    response: UserResponse = UserResponse.NONE  # 사용자의 결정

@dataclass
class MissionStatus:
    """[Process: Brain] BT의 판단 결과 및 작업 데이터"""
    # 1. 현재 수행중인 미션 (BT의 결정)
    active_mission: MissionMode = MissionMode.IDLE
    
    # 2. Vision에게 내리는 명령 (Desired State)
    vision_command: VisionCommand = VisionCommand.OFF
    
    # 3. 사용자 인터랙션
    user: UserInteraction = field(default_factory=UserInteraction)
    
    # 4. 검증된 수확 타겟 리스트 (Arm은 이것만 참조하면 됨)
    # 평소엔 비어있다가, Verify 단계가 끝나면 채워짐. 수확 끝나면 비워짐.
    total_chamoe_count: int = 0
    confirmed_targets: List[ChamoeObject] = field(default_factory=list)

# ==============================================================================
# 5. ROOT BLACKBOARD
# ==============================================================================

class Blackboard:
    """
    [Global Shared Memory]
    Vision(눈) | System(몸: Arm+Base) | Mission(뇌)
    세 가지 영역으로 깔끔하게 분리됨.
    """
    def __init__(self):
        # 1. Vision PC 영역 (VisionSystem이 갱신)
        self.vision = VisionPerception()
        
        # 2. Control PC 영역 (Arm/Base 프로세스가 갱신)
        self.system = SystemStatus()
        
        # 3. Brain 영역 (BT가 판단하고 갱신)
        self.mission = MissionStatus()

    # === [Setter Methods for IPC] ===
    def update_vision(self, data: VisionPerception):
        self.vision = data

    def update_mission(self, data: MissionStatus):
        self.mission = data
        
    def update_system(self, data: SystemStatus):
        self.system = data
        
    def get_vision(self) -> VisionPerception:
        return self.vision

    def get_mission(self) -> MissionStatus:
        return self.mission
        
    def get_system(self) -> SystemStatus:
        return self.system


# ==============================================================================
# [FUTURE WORK & EXTENSIONS]
# ==============================================================================
# 1. Logging Status
#   - 미션 수행 로그를 별도로 관리하는 클래스 도입 고려
#   - e.g., MissionLog(start_time, end_time, success_count, fail_reason)
#
# 2. Safety Monitoring
#   - 배터리 전압, 모터 온도, 에러 코드 등을 관리하는 SafetyStatus 클래스
# ==============================================================================