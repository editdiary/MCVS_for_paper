> BT 코드(decision_node.py)를 바탕으로 Gemini가 시뮬레이션을 해준 내용입니다.

# 🔍 최종 시뮬레이션 점검 결과
1. 초기 진입 (IDLE -> STANDBY)
   - 시스템 부팅 시 IDLE.
   - Branch 0 진입 $\rightarrow$ 사용자에게 시작 질문 $\rightarrow$ 승인 시 STANDBY 전환.
   - (Pass) 완벽합니다.
2. 대기 및 분기 (STANDBY Logic)
   - STANDBY 상태에서 Option A (Trigger)가 발생하면 즉시 수확 준비 모드로 직행. (사용자 피로도 감소)
   - 파이프만 보이면 Option B에서 주행 제안. 거절하면 Option C로 넘어가 IDLE 제안.
   - 모두 거절하면 Branch 6에 의해 STANDBY 유지.
   - (Pass) 무한 루프 없이 유저의 의사결정에 따라 흐름이 제어됩니다.
3. 주행 및 발견 (NAVIGATING -> READY)
   - 주행 중 Trigger Zone 감지 시(Branch 3) 즉시 정지 모드 전환.
   - 파이프 놓치면 Branch 4 실패 $\rightarrow$ Branch 6(Safety)에 의해 STANDBY로 안전 정지.
   - (Pass) 예외 상황(길 잃음)까지 커버됩니다.
4. 수확 준비 (READY -> HARVEST)
   - 5초 검증 후 타겟 확정(confirmed_targets 등록).
   - 사용자가 START 승인 시 수확 모드 진입.
   - 거절 시(오탐지 판단) SetNavigationMode로 타겟 비우고 회피 주행.
   - (Pass) 오탐지 무한 정지 구간을 회피하는 로직이 잘 적용되었습니다.
5. 수확 및 종료 (HARVEST -> STANDBY)
   - 수확 후 검증(VerifyAfterHarvest) 성공 시 $\rightarrow$ STANDBY 복귀 (추가 작업/종료 선택 가능).
   - 잔여물 발견 시(RETRY) $\rightarrow$ 타겟 리스트 갱신 후 재질문.
   - 재수확 거절 시 $\rightarrow$ SetNavigationMode로 타겟 비우고 회피 주행.
   - (Pass) 수확 후 시나리오(성공/재시도/포기)가 완벽하게 분기됩니다.