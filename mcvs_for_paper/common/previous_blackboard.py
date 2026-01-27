# common/blackboard.py

import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum, auto

# ==============================================================================
# 1. ENUMS (상태 및 명령 정의)
# ==============================================================================

class SystemStatus(Enum):
    """전체 시스템 상태"""
    BOOTING = auto()
    READY = auto()
    ERROR = auto()
    EMERGENCY_STOP = auto()

class MissionMode(Enum):
    """
    로봇이 수행 중인 최상위 임무 상태 (BT State Machine)
    BT의 각 Branch 실행 조건으로 사용됩니다.
    """
    IDLE = auto()               # 0. 초기화 및 대기 (시스템 부팅 중 / 대기 상태)
    NAVIGATING = auto()         # 1. 주행 중 (파이프 추종) [BT Branch 3, 4: Navigating]
    READY_TO_HARVEST = auto()   # 2. 수확 준비 (정지 및 타겟 검증) [BT Branch 2, 3: Verify & Trigger]
    HARVESTING = auto()         # 3. 수확 중 (암 제어권 이양) [BT Branch 1: Harvesting]
    STANDBY = auto()            # 4. 대기 (길 잃음, 안전 정지) [BT Branch 5: Safety]
    EMERGENCY = auto()          # 5. 비상 상황 (하드웨어 오류 등)

class VisionCommand(Enum):
    """[BT -> Vision] 비전 시스템 제어 명령"""
    OFF = auto()            # 0. 카메라/추론 꺼짐 (시스템 종료/대기)
    SCANNING = auto()       # 1. 탐색 중 (Inference ON, 15FPS)
                            #    - 주행 중 파이프/참외 지속 탐지           
    STREAM_ONLY = auto()    # 2. 관망 중 (Inference OFF, Stream ON)
                            #    - 수확 중 리소스 절약
                            #    - 카메라는 켜져 있어 원격 관제 가능
    BURST_VERIFY = auto()   # 3. 정밀 검증 (Inference ON, N-Frames)
                            #    - 수확 여부 판단을 위해 일정 시간(예: 2초) 동안
                            #      추론 결과를 누적/평균내어 판단
    
class SteeringCommand(Enum):
    """로봇 조향 명령"""
    CENTER = 0          # 직진
    STEER_LEFT = 1      # 좌회전 (약)
    STEER_RIGHT = 2     # 우회전 (약)
    HARD_LEFT = 3       # 좌회전 (강)
    HARD_RIGHT = 4      # 우회전 (강)
    NONE = 9            # 라인 없음/정지

class TargetSource(Enum):
    """타겟 발견 출처"""
    GLOBAL_VISION = auto()      # 메인 카메라 (ZED, Arducam)
    ARM_CAMERA = auto()         # 로봇 팔 카메라 (Eye-in-Hand)

class HarvestStatus(Enum):
    """개별 타겟의 수확 진행 상태"""
    PENDING = auto()            # 대기 중
    IN_PROGRESS = auto()        # 수확 시도 중
    SUCCESS = auto()            # 성공
    FAILED = auto()             # 실패
    UNREACHABLE = auto()        # 팔이 닿지 않음
    
# [NEW] 사용자 응답 정의
class UserResponse(Enum):
    NONE = auto()       # 응답 대기 중
    APPROVE = auto()    # 승인 (Yes)
    REJECT = auto()     # 거절 (No)

# ==============================================================================
# 2. DATA CLASSES (데이터 구조)
# ==============================================================================

@dataclass
class Timestamp:
    """시스템 동기화 및 생존(Health) 확인"""
    # 1. Heartbeat: 프로세스/스레드 생존 신호 (매 루프 갱신)
    vision_heartbeat: float = 0.0
    robot_heartbeat: float = 0.0
    arm_heartbeat: float = 0.0
    
    # 2. Data Updated: 실제 데이터가 갱신된 시각 (통신/추론 시점)
    vision_data_captured: float = 0.0   # Sync ID 역할
    robot_updated: float = 0.0          # 하드웨어 데이터 수신 시각
    arm_updated: float = 0.0            # 매니퓰레이터 데이터 수신 시각

    def is_vision_alive(self, timeout: float = 3.0) -> bool:
        """비전 시스템 프로세스 응답 확인"""
        return (time.time() - self.vision_heartbeat) < timeout

@dataclass
class ChamoeObservation:
    """[Vision Update] 센서가 관측한 물리적 사실 (Raw Data)"""
    track_id: str = "N/A"          # 트래킹 ID
    source: TargetSource = TargetSource.GLOBAL_VISION # (보통 센서가 출처를 아는 것이 자연스러워 Vision에 배치)
    
    # 기하학적 정보 (0.0 ~ 1.0 정규화 좌표)
    center_x: float = 0.0          
    center_y: float = 0.0
    area_ratio: float = 0.0        # 화면 내 점유율 (크기)
    
    confidence: float = 0.0        # YOLO 인식 신뢰도

@dataclass
class ChamoeLogic:
    """[BT Update] Vision 데이터를 보고 내린 판단 (Context)"""
    # BT의 Condition Node가 판단하여 갱신
    is_candidate: bool = False     # "수확 시도해볼 만한가?" (ROI, 크기 등 1차 필터)
    priority: int = 999            # 수확 우선순위 (낮을수록 먼저 수확, 거리/위치 기반)
    
    # 위치 기반 논리 플래그
    is_in_trigger_zone: bool = False # 중앙 정지 유도 구역에 있는가?
    is_in_harvest_zone: bool = False # 작업 가능 구역(Workspce)에 있는가?

@dataclass
class ChamoeAction:
    """[Arm Update] 실제 수확 작업 진행 상황 (State)"""
    status: HarvestStatus = HarvestStatus.PENDING
    retry_count: int = 0
    
    # 수확 중 실시간 좌표 보정 (Visual Servoing용)
    tracking_error_x: float = 0.0
    tracking_error_y: float = 0.0
    last_action_time: float = 0.0

@dataclass
class HarvestTarget:
    """
    [Integrated Object] 개별 참외 객체에 대한 통합 정보
    데이터의 갱신 주체별로 dataclass를 중첩하여 관리합니다.
    """
    # 3단 분리 구조
    obs: ChamoeObservation = field(default_factory=ChamoeObservation)  # by Vision
    logic: ChamoeLogic = field(default_factory=ChamoeLogic)            # by BT
    action: ChamoeAction = field(default_factory=ChamoeAction)         # by Arm
    
# ------------------------------------------------------------------------------

@dataclass
class VisionPerception:
    """[Vision -> Blackboard] 시각 인식 결과"""
    # Vision 상태
    current_state: VisionCommand = VisionCommand.OFF
    
    # 메타데이터: 픽셀 좌표 복원을 위한 해상도 정보
    resolution: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    
    # 1. Pipe (Navigation)
    is_pipe_detected: bool = False
    pipe_lateral_error: float = 0.0     # -1.0(L) ~ 0.0(C) ~ 1.0(R)
    
    # 2. Objects (Raw List)
    # 통계 (Raw Count)
    total_chamoe_count: int = 0  # 화면에 보이는 모든 박스 개수
    # Vision은 판단하지 않고, 보이는 모든 것을 여기에 담아둡니다.
    visible_chamoes: List[HarvestTarget] = field(default_factory=list)

@dataclass
class MissionStatus:
    """[BT -> Blackboard] 상황 판단 및 작업 관리"""
    # 로봇의 현재 모드 (지휘관의 명령)
    current_mode: MissionMode = MissionMode.IDLE
    
    # 전체 수확 성과 (통계용으로 유지)
    total_harvested: int = 0
    total_failed: int = 0

@dataclass
class RobotStatus:
    """[Robot Base -> Blackboard] 하드웨어 상태"""
    battery_voltage: float = 0.0
    is_moving: bool = False
    current_steering: SteeringCommand = SteeringCommand.NONE
    
    # 안전 관련
    recovery_required: bool = False     # 자율 탈출 필요 여부
    error_code: int = 0
    
    # 통신 상태
    connection_arm: bool = False
    connection_gripper: bool = False

@dataclass
class ArmStatus:
    """[Manipulator -> Blackboard] 로봇 팔 상태 보고"""
    # 1. 현재 물리적 상태
    current_pose: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    is_busy: bool = False           # True면 로봇 팔이 움직이는 중
    
    # 2. [New] 수확 사이클 상태 신호
    # BT는 이 플래그가 True가 될 때까지 기다립니다.
    # Arm Controller는 작업을 다 마치면 이 값을 True로 설정해야 합니다.
    is_cycle_finished: bool = False
    
# [NEW] 사용자 인터랙션용 데이터 (User Interface)
@dataclass
class UserInteraction:
    """[BT <-> User] 사용자 승인/거절 요청 및 상태"""
    # BT가 설정하는 값 (요청)
    is_waiting_for_input: bool = False  # 현재 사용자 입력을 기다리는 중인가?
    request_type: str = "NONE"          # 요청 종류 (예: "START_HARVEST", "FINISH_HARVEST", "RETRY")
    message: str = ""                   # 사용자에게 보여줄 안내 메시지 (예: "3개 발견. 수확할까요?")
    
    # 사용자가 설정하는 값 (응답)
    response: UserResponse = UserResponse.NONE # 사용자의 결정

# ==============================================================================
# 3. INTEGRATED BLACKBOARD
# ==============================================================================

class Blackboard:
    """
    전체 시스템 공유 메모리 (Singleton)
    Vision, Robot, Arm, Mission 모듈이 데이터를 교환하는 허브입니다.
    """
    def __init__(self):
        self.system_status = SystemStatus.BOOTING
        self.timestamps = Timestamp()
        
        self.vision = VisionPerception()   # Sensor (Eye)
        self.mission = MissionStatus()     # Logic (Brain)
        self.robot = RobotStatus()         # Base (Legs)
        self.arm = ArmStatus()             # Manipulator (Hand)
        
        # [NEW] 사용자 인터랙션 추가
        self.user = UserInteraction()