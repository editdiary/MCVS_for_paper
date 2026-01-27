# mcvs/modules/decision_node.py

import time
import py_trees
from py_trees.common import Status
from common.blackboard import MissionMode, VisionCommand, UserResponse, ChamoeObject, SystemState # Blackboard Enum 참조

# ==========================================
# 1. Custom Leaf Nodes (부품 만들기)
# ==========================================

class CheckMode(py_trees.behaviour.Behaviour):
    """(Condition) 현재 모드가 특정 상태인지 확인"""
    def __init__(self, target_mode, blackboard):
        super().__init__(name=f"Mode == {target_mode}?")
        self.target_mode = target_mode
        self.bb = blackboard

    def update(self):
        current_mission = self.bb.get_mission()
        if current_mission.active_mission == self.target_mode:
            return Status.SUCCESS
        return Status.FAILURE

class CheckZone(py_trees.behaviour.Behaviour):
    """(Condition) 특정 구역(Trigger/Harvest)에 참외가 있는지 확인"""
    def __init__(self, zone_type, blackboard):
        super().__init__(name=f"In {zone_type} Zone?")
        self.zone_type = zone_type # 'Trigger' or 'Harvest'
        self.bb = blackboard
        
    def update(self):
        targets = self.bb.get_vision().visible_objects
        
        is_exist = False
        if self.zone_type == 'Trigger':
            # Vision Logic: is_in_trigger_zone 확인
            is_exist = any(t.logic.is_in_trigger_zone for t in targets)
        else:
            # Vision Logic: is_in_harvest_zone 확인
            is_exist = any(t.logic.is_in_harvest_zone for t in targets)
            
        return Status.SUCCESS if is_exist else Status.FAILURE

class SetMode(py_trees.behaviour.Behaviour):
    """(Action) Blackboard의 MissionMode 변경"""
    def __init__(self, new_mode, blackboard):
        super().__init__(name=f"Set {new_mode.name}")
        self.new_mode = new_mode
        self.bb = blackboard

    def update(self):
        # [수정] get -> modify -> update 패턴 사용
        mis = self.bb.get_mission()
        mis.active_mission = self.new_mode
        self.bb.update_mission(mis)
        return Status.SUCCESS

class SetVisionCommand(py_trees.behaviour.Behaviour):
    """(Action) Vision Command만 단독으로 변경 (모드 변경 없음)"""
    def __init__(self, command, blackboard):
        super().__init__(name=f"Vision -> {command.name}")
        self.command = command
        self.bb = blackboard

    def update(self):
        mis = self.bb.get_mission()
        if mis.vision_command != self.command:
            mis.vision_command = self.command
            self.bb.update_mission(mis)
        return Status.SUCCESS
    
class IsPipeDetected(py_trees.behaviour.Behaviour):
    """(Condition) 파이프가 탐지되고 있는가?"""
    def __init__(self, blackboard):
        super().__init__(name="Pipe Detected?")
        self.bb = blackboard

    def update(self):
        # [수정] get_vision() 사용
        if self.bb.get_vision().is_pipe_detected:
            return Status.SUCCESS
        else:
            return Status.FAILURE   

class EnsureRobotStopped(py_trees.behaviour.Behaviour):
    """(Action/Wait) 로봇이 물리적으로 완전히 정지할 때까지 대기"""
    def __init__(self, blackboard):
        super().__init__(name="Wait For Stop")
        self.bb = blackboard
        self.last_log_time = 0.0 # [New]

    def update(self):
        # 보행 프로세스가 'is_moving=False'를 보고할 때까지 대기
        if not self.bb.get_system().base.is_moving:
            return Status.SUCCESS  # "정지 확인됨. 다음 단계로 가세요."
        
        # =========================================================
        # [New] 정지 대기 중 로그 (Throttle: 1초마다)
        # =========================================================
        current_time = time.time()
        if current_time - self.last_log_time > 1.0:
            print(f"[BT] 🛑 정지 신호 전송됨. 로봇 감속 대기 중...")
            self.last_log_time = current_time
        # =========================================================
        
        return Status.RUNNING      # "아직 감속 중입니다. 기다리세요."

class SetNavigationMode(py_trees.behaviour.Behaviour):
    """
    [Branch 4 Action] 주행 모드 활성화
    - 실제 조향(Steering)은 보행 프로세스가 수행하도록 위임
    - Vision을 SCANNING 모드로 전환하여 지속적인 탐색 보장
    - [Mod] 주행 모드 전환 시, 이전의 고정 타겟(Confirmed Targets) 정보는 폐기(초기화)함
    """
    def __init__(self, blackboard):
        super().__init__(name="Set NAVIGATING & SCANNING")
        self.bb = blackboard
        self.last_log_time = time.time()

    def update(self):
        mis = self.bb.get_mission()
        
        # [Logic] 모드가 바뀌는 순간인지 확인 (더블 프린트 방지용)
        is_switching = (mis.active_mission != MissionMode.NAVIGATING)
        
        # 1. Vision에게 탐색 명령 (눈 떠!)
        # [Mod] mission.vision_command로 명령을 내림 (Vision이 이걸 보고 current_state를 바꿈)
        mis.vision_command = VisionCommand.SCANNING

        # 2. 보행 프로세스에게 주행 명령 (출발!)
        mis.active_mission = MissionMode.NAVIGATING
        
        # 2. 타겟 초기화 (진입 시에만 로그 출력)
        if is_switching:
            mis.confirmed_targets.clear()
            mis.total_chamoe_count = 0
            print(f"[BT] 🚜 주행 모드로 전환합니다! (Vision: SCANNING)")
        
        self.bb.update_mission(mis)
        
        # 4. 안전 감시 (옵션)
        # 만약 시스템 에러가 있다면 FAILURE 리턴 -> Safety 모드 진입
        if self.bb.get_system().state == SystemState.ERROR:
            return Status.FAILURE
        
        # 3. 생존 신고 (Throttle: 3초)
        # 이미 주행 중일 때만 주기적으로 출력
        if not is_switching:
            current_time = time.time()
            if current_time - self.last_log_time > 5.0:
                # [New] Q키 안내 추가
                print(f"[BT] 🚜 주행 중... (제어권: Base / Vision 탐색 중) - (q: 비상대기)")
                self.last_log_time = current_time

        return Status.SUCCESS
    
class WaitForHarvestCompletion(py_trees.behaviour.Behaviour):
    """
    [Branch 1 Action] 수확 완료 대기
    - 역할: Arm Controller가 수확 사이클을 마칠 때까지 RUNNING 상태 유지
    - 조건: bb.arm.is_cycle_finished가 True가 되면 SUCCESS 반환
    """
    def __init__(self, blackboard):
        super().__init__(name="Wait For Arm Finish")
        self.bb = blackboard
        self.last_log_time = 0.0 # [New]

    def initialise(self):
        print("[BT] 수확 모드 진입. Arm 작업 완료를 대기합니다...")
        self.last_log_time = time.time()

    def update(self):
        # 1. 비상 탈출: 모드가 바뀌면 즉시 종료
        if self.bb.get_mission().active_mission != MissionMode.HARVESTING:
            return Status.FAILURE

        # 2. 완료 신호 확인
        if self.bb.get_system().arm.is_cycle_finished:
            print("[BT] ✅ Arm 작업 완료 신호 수신! 사후 검증 단계로 진입합니다.")
            return Status.SUCCESS
        
        # =========================================================
        # [New] 생존 신고 (Throttle: 2초마다 출력)
        # =========================================================
        current_time = time.time()
        if current_time - self.last_log_time > 5.0:
            print(f"[BT] 🦾 수확 진행 중... (완료 대기) - (q: 비상대기)")
            self.last_log_time = current_time
        # =========================================================
        
        # 3. 아직 작업 중
        return Status.RUNNING
    
# [Mod] 5초간 정밀 검증하여 수확 여부를 결정하고, 타겟을 확정(Registration)하는 노드 (사전 검증용)
class VerifyHarvestAvailability(py_trees.behaviour.Behaviour):
    """
    [Branch 2 Action] 수확 전 정밀 검증
    - 5초간 정밀 검증(BURST_VERIFY) 수행
    - 유효 타겟이 있으면 'ChamoeObject'로 변환하여 Mission Blackboard에 등록
    """
    def __init__(self, name, blackboard):
        super().__init__(name)
        self.bb = blackboard
        self.start_time = 0.0

    def initialise(self):
        # 노드 진입 시 시간 기록 및 비전 모드 변경
        self.start_time = time.time()
        
        mis = self.bb.get_mission()
        mis.vision_command = VisionCommand.BURST_VERIFY
        # 기존 타겟 리스트 초기화 (이전 작업 데이터 삭제)
        mis.confirmed_targets.clear()
        mis.total_chamoe_count = 0
        self.bb.update_mission(mis)
        print("[BT] 수확 전 정밀 판단 중 (5초)...")

    def update(self):
        # 1. 5초 대기 (데이터 수집)
        if time.time() - self.start_time < 5.0:
            return Status.RUNNING

        # 2. 5초 경과 후 리소스 절약 모드 전환
        mis = self.bb.get_mission()
        mis.vision_command = VisionCommand.STREAM_ONLY

        # =====[판단 로직]: Vision이 5초 간 준 데이터로 정밀 판단 ========================
        ## [TODO] 지금은 단순히 수확 영역에 포함되는지 여부로 우선 구현해두었지만,
        ##        향후에는 통계적인 검증 방법이나 색상 비교 등의 로직을 함께 포함하여 심층 판단 추가
        ##        이 부분은 VisionCommand에 따라 동작 구현이 완성되면 수정해볼 수 있을 것 같음
        
        # 3. Vision 데이터 필터링 (Logic: Candidate + In Zone)
        valid_raw_objects = [
            obj for obj in self.bb.get_vision().visible_objects
            if obj.logic.is_candidate and obj.logic.is_in_harvest_zone
        ]
        # ===========================================================================

        if valid_raw_objects:
            # 4. [NEW] 데이터 변환 및 등록 (Vision -> Mission)
            self._register_targets(mis, valid_raw_objects) 
            self.bb.update_mission(mis)
            
            count = len(mis.confirmed_targets)
            print(f"[BT] 판단 완료: 수확 대상 {count}개 확정 및 등록 완료.")
            return Status.SUCCESS   # -> 뒤이어 SetMode(HARVESTING) 실행됨
        else:
            print("[BT] 판단 완료: 유효 타겟 없음 (오탐지). 무시하고 주행합니다.")
            return Status.FAILURE   # -> 뒤이어 SetMode(NAVIGATING) 실행됨

    def _register_targets(self, mission_data, raw_objects):
        """TotalObject(Vision) -> ChamoeObject(Mission) 변환 및 정렬"""
        confirmed_list = []
        
        for raw in raw_objects:
            # Score 계산: [TODO] Score 계산 로직 좀 더 고도화 시킬 수 있을 것
            score = raw.obs.confidence  # 여기서는 우선 단순하게 Confidence를 점수로 사용
            
            target = ChamoeObject(
                score=score,
                confidence=raw.obs.confidence,
                center_x=raw.obs.center_x,
                center_y=raw.obs.center_y,
                width=raw.obs.width,
                height=raw.obs.height,
                priority=0  # 아래에서 재조정
            )
            confirmed_list.append(target)
            
        # [Sorting Logic] 무엇을 먼저 딸 것인가?: Score가 높은 순서대로 정렬 (내림차순)
        confirmed_list.sort(key=lambda x: x.score, reverse=True)
        
        # 우선순위 번호 부여 (0번이 1순위)
        for idx, target in enumerate(confirmed_list):
            target.priority = idx
            
        # Blackboard에 최종 등록
        mission_data.confirmed_targets = confirmed_list
        mission_data.total_chamoe_count = len(confirmed_list)

# 수확 후 잔여물 검증 노드 (사후 검증용)
## [TODO] 지금 '수확 전'과 '수확 후'에 5초 간의 검증 프로세스가 동일하게 진행되는데 두 개로 나눠져 있음
##        명시적으로 하려면 두 개로 나누는 게 나은 거 같은데, class 하나로 통합할 수 없을까 모르겠다.
class VerifyAfterHarvest(py_trees.behaviour.Behaviour):
    """
    [Branch 1 Action] 수확 후 정밀 검증 (Post-Harvest Verify)
    - 역할: 5초간 잔여물 확인.
    - [Mod] 잔여물이 발견되면 이를 'confirmed_targets'로 갱신하여 재수확(Retry) 준비를 마침.
    """
    def __init__(self, name, blackboard):
        super().__init__(name)
        self.bb = blackboard
        self.start_time = 0.0

    def initialise(self):
        self.start_time = time.time()
        
        mis = self.bb.get_mission()
        mis.vision_command = VisionCommand.BURST_VERIFY
        # 기존 확정 리스트 초기화 (재검증을 위해 비움)
        mis.confirmed_targets.clear()
        mis.total_chamoe_count = 0
        self.bb.update_mission(mis)
        print("[BT] 수확 후 잔여물 검증 시작 (5초)...")

    def update(self):
        # 5초간 대기
        if time.time() - self.start_time < 5.0:
            return Status.RUNNING

        mis = self.bb.get_mission()
        mis.vision_command = VisionCommand.STREAM_ONLY
        
        # =====[판단 로직]: Vision이 5초 간 준 데이터로 정밀 판단 ========================
        ## [TODO] 여기 판단 로직이 사실상 수확 전 판단과 완전 똑같은데, 통일할 수 없으려나..?
        
        # 3. 잔여물(Candidate & In Zone) 확인 (Raw Data)
        remaining_raw_objects = [
            obj for obj in self.bb.get_vision().visible_objects
            if obj.logic.is_candidate and obj.logic.is_in_harvest_zone
        ]
        # ===========================================================================

        if not remaining_raw_objects:
            print("[BT] 검증 완료: 잔여물 없음 (Clean). 수확 종료.")
            self.bb.update_mission(mis)
            return Status.SUCCESS # -> FINISH 질문으로 이동
        else:
            # [NEW] 잔여물이 있다면, 이를 차기 수확 타겟(confirmed_targets)으로 등록
            self._register_residues(mis, remaining_raw_objects)
            self.bb.update_mission(mis)
            
            count = len(mis.confirmed_targets)
            print(f"[BT] 검증 경고: 잔여물 {count}개 발견. 재작업 리스트 등록 완료.")
            return Status.FAILURE # -> RETRY 질문으로 이동
        
    def _register_residues(self, mission_data, raw_objects):
        """잔여물(TotalObject) -> 확정타겟(ChamoeObject) 변환"""
        ## [TODO] 이것도 수확 전 검증 단계의 _register_targets와 동일한 로직임
        ##        별도 유틸 함수로 빼거나 통합할 것(우선은 명시적으로 작성함)
        confirmed_list = []
        
        for raw in raw_objects:
            # 잔여물은 무조건 다시 따야 하므로 높은 우선순위를 가질 수 있음
            target = ChamoeObject(
                score=raw.obs.confidence,
                confidence=raw.obs.confidence,
                center_x=raw.obs.center_x,
                center_y=raw.obs.center_y,
                width=raw.obs.width,
                height=raw.obs.height,
                priority=0
            )
            confirmed_list.append(target)
            
        # 정렬 (Score순)
        confirmed_list.sort(key=lambda x: x.score, reverse=True)
        
        # 우선순위 재할당
        for idx, target in enumerate(confirmed_list):
            target.priority = idx
            
        # Blackboard 갱신
        mission_data.confirmed_targets = confirmed_list
        mission_data.total_chamoe_count = len(confirmed_list)

# Arm 상태 리셋 노드 (재시도용)
class ResetArmCycle(py_trees.behaviour.Behaviour):
    """
    [Branch 1 Action] Arm 상태 리셋 (재시도용)
    - 역할: is_cycle_finished를 False로 돌려서 Arm이 다시 작업하게 만듦
    """
    def __init__(self, blackboard):
        super().__init__(name="Reset Arm Status")
        self.bb = blackboard

    def update(self):
        print("[BT] Arm에게 재작업 신호 전송 (Reset Cycle Flag)")
        sys_data = self.bb.get_system()
        sys_data.arm.is_cycle_finished = False
        self.bb.update_system(sys_data)
        return Status.SUCCESS
    
# 사용자 승인 대기 노드
class WaitForUserConfirmation(py_trees.behaviour.Behaviour):
    """
    [Action/Wait] 사용자 승인 대기
    - 역할: Blackboard에 요청 메시지를 띄우고, 사용자가 승인(APPROVE)할 때까지 대기
    - 승인 시 SUCCESS, 거절 시 FAILURE 반환
    """
    def __init__(self, request_type, blackboard):
        super().__init__(name=f"Ask User: {request_type}")
        self.request_type = request_type # "START", "FINISH", "RETRY"
        self.bb = blackboard

    def initialise(self):
        # 1. 메시지 생성 (Context Aware)
        msg = ""
        mis = self.bb.get_mission()
        
        # [Refactoring] 확정된 공통 타겟 데이터(Confirmed Targets) 참조 (START, RETRY 등 수확 관련 요청용)
        # request_type에 관계없이 접근해도 안전하며(빈 리스트일 뿐), 코드가 간결해짐
        targets = mis.confirmed_targets
        count = mis.total_chamoe_count
        
        # 좌표 문자열 미리 생성 (필요한 경우에만 쓰임)
        # 리스트 컴프리헨션 비용이 크지 않으므로 미리 만들어둬도 무방
        coords_str = [f"({t.center_x:.2f}, {t.center_y:.2f})" for t in targets]
        
        # -------------------------------------------------------
        # Case 1: 수확 관련 질문 (START / RETRY / FINISH)
        # -------------------------------------------------------
        # [Mod] 수확 시작 요청
        if self.request_type == "START":
            msg = f"[질문] 검증된 참외 {count}개 발견 {coords_str}. 수확을 시작할까요? (Y/n: 주행 모드로 복귀)"
            
        elif self.request_type == "RETRY":
            msg = f"[질문] 잔여물 {count}개 {coords_str} 발견. 다시 수확할까요? (Y/n: 주행 모드로 복귀)"
            
        elif self.request_type == "FINISH":
            msg = "[질문] 수확이 완료되었습니다(잔여물 없음). 대기 모드(STANDBY)로 전환할까요? (Y/n)"

        # -------------------------------------------------------
        # Case 2: 모드 전환 제안 (STANDBY / IDLE)
        # -------------------------------------------------------
        # [NEW] 시스템 시작 요청 케이스 추가
        elif self.request_type == "SYSTEM_START":
            msg = "[시스템] 시스템이 IDLE 상태입니다. 작동을 시작(STANDBY)하시겠습니까? (Y/n)"
            
        # [NEW] STANDBY 분기 질문
        # [Mod] 요청 타입 및 메시지 변경 (상황 구체화)
        elif self.request_type == "SUGGEST_NAV":
            msg = "[상태] 파이프는 보이지만 수확할 참외가 없습니다. 주행 모드(NAVIGATING)로 전환하여 탐색할까요? (Y/n)"
            
        elif self.request_type == "SUGGEST_IDLE":
            msg = "[상태] 대기 중입니다. (파이프 없음/주행 거절). IDLE 모드로 초기화(종료)할까요? (Y/n)"

        # 2. Blackboard User Interaction 게시
        mis.user.is_waiting_for_input = True
        mis.user.request_type = self.request_type
        mis.user.message = msg
        mis.user.response = UserResponse.NONE
        self.bb.update_mission(mis)
        
        print(f"\n >>> {msg} (Waiting for Input...)")

    def update(self):
        # 사용자의 응답 확인
        resp = self.bb.get_mission().user.response
        
        if resp == UserResponse.APPROVE:
            print(f"[BT] 사용자 승인 ({self.request_type}) -> 진행합니다.")
            self._cleanup()
            return Status.SUCCESS
            
        elif resp == UserResponse.REJECT:
            print(f"[BT] 사용자 거절 ({self.request_type}) -> 취소/우회합니다.")
            self._cleanup()
            return Status.FAILURE
            
        # 아직 응답 없음
        return Status.RUNNING

    def _cleanup(self):
        # 상태 초기화
        mis = self.bb.get_mission()
        mis.user.is_waiting_for_input = False
        mis.user.message = ""
        self.bb.update_mission(mis)

# ==========================================
# 2. Tree Construction (최종 조립)
# ==========================================

def create_chamdog_tree(blackboard):
    root = py_trees.composites.Selector(name="ChamDog Main Logic", memory=False)
    
    # [NEW] -----------------------------------------------------------
    # Branch 0: 시스템 시작 대기 (System Start Entry) (IDLE -> STANDBY)
    # -----------------------------------------------------------------
    # 초기 상태(IDLE)에서 사용자의 시작 승인을 기다림 -> 승인 시 STANDBY로 전환
    seq_idle = py_trees.composites.Sequence(name="0. System Start", memory=False)
    seq_idle.add_children([
        CheckMode(MissionMode.IDLE, blackboard),        # 1. 현재 IDLE 상태인가?
        WaitForUserConfirmation("SYSTEM_START", blackboard), # 2. 시작할까요? (Yes 대기)
        SetMode(MissionMode.STANDBY, blackboard)        # 3. STANDBY로 변경 (이제 루프 시작)
    ])
    
    # -----------------------------------------------------------------
    # Branch 1: 수확 진행 (Arm 위임)
    # -----------------------------------------------------------------
    # 구조: Harvesting Mode Check -> Wait Arm -> Verify(5s) -> [If Clean: Nav Mode] / [If Dirty: Reset Arm]
    
    seq_harvesting_loop = py_trees.composites.Sequence(name="1. Harvesting Loop", memory=False)
    
    # 1-1. 사후 검증 및 처리 (Selector)
    # 로직: [Clean?] -> (Fail) -> [Retry?] -> (Fail/No) -> [Force Finish]
    sel_post_verify = py_trees.composites.Selector(name="Post Harvest Logic", memory=True)
    
    # Case A: 깨끗함 -> 사용자 확인 -> 주행 모드
    seq_clean = py_trees.composites.Sequence(name="Clean -> Finish", memory=True)
    seq_clean.add_children([
        VerifyAfterHarvest(name="Post Verify", blackboard=blackboard),  # 잔여물 없으면 SUCCESS
        WaitForUserConfirmation("FINISH", blackboard),                  # "끝낼까요?"
        SetMode(MissionMode.STANDBY, blackboard)                        # [Change] 주행 대신 STANDBY로!
    ])
    
    # Case B: 더러움(잔여물) -> 사용자 확인(Yes) -> 재시도
    seq_retry = py_trees.composites.Sequence(name="Dirty -> Retry", memory=True)
    seq_retry.add_children([
        # VerifyAfterHarvest가 실패했으므로 일로 넘어옴
        #    - 사용자가 Yes하면 SUCCESS 반환 -> ResetArmCycle 실행
        #    - 사용자가 No하면 FAILURE 반환 -> Case C로 넘어감!
        WaitForUserConfirmation("RETRY", blackboard),                   # 1. 재수확 할 건지 물어봄           
        ResetArmCycle(blackboard)                                       # 2. Arm 리셋 (다시 Wait 단계로)
    ])
    
    # Case C: 더러움 & 사용자 재시도 거절 -> 강제 종료 (오탐지 무시)
    #   여기서는 잔여물을 무시하고 '회피'해야 하므로 주행(NAVIGATING)으로 전환
    #   STANDBY로 가면 잔여물 때문에 다시 Trigger Zone 로직이 돌아서 꼬일 수 있음
    seq_force_finish = py_trees.composites.Sequence(name="Dirty -> Force Finish", memory=False)
    seq_force_finish.add_children([
        # 별도 질문 없이 바로 주행모드로 변경 (혹은 안내 로그 출력용 노드 추가 가능)
        SetNavigationMode(blackboard) 
    ])
    
    # Post Logic (자식 노드) 조립
    sel_post_verify.add_children([seq_clean, seq_retry, seq_force_finish])
    
    # Branch 1 조립
    seq_harvesting_loop.add_children([
        CheckMode(MissionMode.HARVESTING, blackboard),
        WaitForHarvestCompletion(blackboard),
        sel_post_verify
    ])
    
    # -----------------------------------------------------------------
    # Branch 2: Branch 2: 수확 준비 및 정밀 검증
    # -----------------------------------------------------------------
    seq_ready = py_trees.composites.Sequence(name="2. Start Judgment", memory=False)
    sel_verify = py_trees.composites.Selector(name="Verify Selection", memory=False)
    
    # Case A: 진짜다 -> 수확 모드 전환
    seq_go = py_trees.composites.Sequence(name="Confirm & Go", memory=True)
    seq_go.add_children([
        VerifyHarvestAvailability(name="Burst Verify", blackboard=blackboard), # 1. Vision 검증 (2초)
        WaitForUserConfirmation("START", blackboard),                          # 2. 수확 시작할지 물어봄
        SetMode(MissionMode.HARVESTING, blackboard)                            # 3. 수확 모드 변경
    ])
    
    # Case B: 가짜다(혹은 사용자가 거절했다) -> 주행 복귀 (오탐지 회피)
    # 사용자가 "START"에서 No를 하면 seq_go가 실패하므로, 자연스럽게 이 action_pass가 실행됨
    ## [TODO] 이 지점에서 '강건한 오탐지'가 발생하면 무한루프에 빠질 수 있음
    ##        하지만 현재로써는 이런 상황은 매우매우 드물 것으로 판단됨
    ##        혹시나 무한루프 상황이 생기면 그때 해결할 것 (일정 시간 동안 Trigger Zone 결과를 무시하도록 한다거나)
    action_pass = SetNavigationMode(blackboard)
    sel_verify.add_children([seq_go, action_pass])
    
    seq_ready.add_children([
        CheckMode(MissionMode.READY_TO_HARVEST, blackboard),
        sel_verify
    ])

    # -----------------------------------------------------------------
    # Branch 3: 발견 시 정지 (Trigger)
    # -----------------------------------------------------------------
    seq_trigger = py_trees.composites.Sequence(name="3. Trigger Stop", memory=False)
    seq_trigger.add_children([
        CheckMode(MissionMode.NAVIGATING, blackboard),      # [Safety] 주행 중일 때만 발동
        CheckZone("Trigger", blackboard),                   # 1. 참외가 트리거 존에 들어왔는가?
        SetMode(MissionMode.READY_TO_HARVEST, blackboard),  # 2. 일단 멈춰! (모드 변경)
        EnsureRobotStopped(blackboard)                      # 3. 로봇이 완전히 멈췄는가? (Wait until stopped)
    ])
    
    # -----------------------------------------------------------------
    # Branch 4: 주행 (NAVIGATING)
    # -----------------------------------------------------------------
    seq_drive = py_trees.composites.Sequence(name="4. Navigation", memory=False)
    seq_drive.add_children([
        CheckMode(MissionMode.NAVIGATING, blackboard),  # [Important] 현재 모드가 주행이어야 함
        IsPipeDetected(blackboard),             # 1. 길이 보여야 감
        SetNavigationMode(blackboard)           # 2. 주행 모드 활성화 (제어권 위임)
    ])
    # 만약 주행 중인데 파이프 놓치면? -> 이 시퀀스 실패 -> Branch 6(Fallback)으로 떨어짐 -> STANDBY
    
    # -----------------------------------------------------------------
    # Branch 5: STANDBY 로직 (The Hub)
    # -----------------------------------------------------------------
    # STANDBY 상태에서 Vision을 켜고 파이프 유무에 따라 다음 상태를 제안함
    seq_standby_logic = py_trees.composites.Sequence(name="5. Standby Logic", memory=False)
    
    # 선택지: 주행 제안해보고 -> 싫다고 하면 -> IDLE 제안
    sel_standby_options = py_trees.composites.Selector(name="Standby Options", memory=True)
    
    # [NEW] Option A: Trigger Zone 감지 (최우선 순위)
    seq_suggest_trigger = py_trees.composites.Sequence(name="Suggest Trigger (Harvest)", memory=False)
    seq_suggest_trigger.add_children([
        CheckZone("Trigger", blackboard),                   # 1. 바로 앞에 참외가 있는가?
        SetMode(MissionMode.READY_TO_HARVEST, blackboard)   # 2. 즉시 수확 준비 모드로 변경
    ])
    
    ## [TODO] 혹시나 참외가 Trigger Zone은 아니지만 Harvest Zone에 포함되는 경우에는
    ##        '미세조정' 모드로 바뀔 수 있도록 한다면? 근데 이건 하려면 승운님이랑도 상의가 필요한 부분임
    
    # Option B: Trigger Zone에 참외 X, 파이프 O -> 주행 제안
    seq_suggest_nav = py_trees.composites.Sequence(name="Suggest Navigation", memory=True)
    seq_suggest_nav.add_children([
        IsPipeDetected(blackboard),                         # 1. 파이프가 있는가?
        WaitForUserConfirmation("SUGGEST_NAV", blackboard), # 2. 주행할까요?
        SetNavigationMode(blackboard)                       # 3. Yes -> 주행 모드 ON
    ])
    
    # Option C: IDLE 제안 (Fallback)
    # 참외는 없는 상태로 파이프가 없거나, 파이프가 탐지되어도 유저가 모드 전환을 거절했을 때
    seq_suggest_idle = py_trees.composites.Sequence(name="Suggest IDLE", memory=True)
    seq_suggest_idle.add_children([
        WaitForUserConfirmation("SUGGEST_IDLE", blackboard),
        SetMode(MissionMode.IDLE, blackboard)
    ])
    
    # 순서대로 등록 (A -> B -> C)
    sel_standby_options.add_children([seq_suggest_trigger, seq_suggest_nav, seq_suggest_idle])
    
    seq_standby_logic.add_children([
        CheckMode(MissionMode.STANDBY, blackboard),
        SetVisionCommand(VisionCommand.SCANNING, blackboard),
        sel_standby_options
    ])
    
    # -----------------------------------------------------------------
    # Branch 6: 안전 대기 (Fallback)
    # -----------------------------------------------------------------
    # 위 모든 조건이 안 맞을 때 (예: 주행 중 파이프 놓침, 이상 상태 등)
    # 무조건 STANDBY로 돌아옴 -> 다음 틱에서 Branch 5가 실행됨
    action_safety = py_trees.composites.Sequence(name="6. Safety Standby", memory=False)
    action_safety.add_children([
        SetMode(MissionMode.STANDBY, blackboard)
    ])
    
    # 루트 등록
    root.add_children([
        seq_idle,               # 0. Start Check
        seq_harvesting_loop,    # 1. Harvesting
        seq_ready,              # 2. Pre-Harvest
        seq_trigger,            # 3. Stop Trigger
        seq_drive,              # 4. Driving
        seq_standby_logic,      # 5. Standby Hub
        action_safety           # 6. Fallback
    ])

    return root


"""
========================================================================================
[DISCUSSION & TODO] 주행 안정성 및 예외 처리 관련 논의 사항
========================================================================================

작성자: 이도현
작성일: 2026-01-12

1. [Issue] 주행 중 파이프 탐지 실패(Pipe Lost) 시의 대처
   - 현재 상황: 
     Branch 4 (Navigation) 조건인 `IsPipeDetected`가 실패하면,
     Branch 6 (Safety Fallback)으로 떨어져 `STANDBY` 모드로 강제 전환됨(급정지).
   
   - 문제점:
     a) 파이프 인식이 일시적으로 불안정할 경우(깜빡임), 로봇이 가다 서다를 반복할 수 있음.
     b) 파이프가 끊긴 구간이나 완전히 안 보이는 구간에서는 수동 조작 외에는 방법이 없음.

2. [Proposal A] BT 레벨에서의 개선 (현재 구조 유지)
   - '파이프 소실 허용 시간(Grace Period)' 도입
   - 예: 파이프가 안 보여도 2~3초간은 직전 조향각을 유지하며 주행 지속 (Vision 노드 내부 처리 or 별도 데코레이터 사용).

3. [Proposal B] 제어권 완전 위임 (승운님과 논의 필요)
   - 방식: 로봇 팔(Arm) 제어 방식과 동일하게 변경.
   - BT 역할: `SetNavigationMode`만 수행하고 빠짐.
   - Base 역할: 알아서 주행하고, 목적지 도착이나 에러 상황에서만 `is_nav_finished` 같은 신호를 BT로 보냄.
   - 장점: 보행 제어기 쪽에서 관성 주행, 경로 계획 등 더 정교한 처리가 가능함.
   - 단점: BT가 로봇의 실시간 상태를 제어하기 어려워질 수 있음(비상 정지 등).

========================================================================================
"""