# common/bt_main.py

import time
import sys
import threading
import py_trees
from pathlib import Path

# =========================================================
# [Fix] 프로젝트 루트 경로 강제 추가
# =========================================================
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent

if str(project_root) not in sys.path:
    sys.path.append(str(project_root))
# =========================================================

try:
    from common.ipc_manager import get_shared_blackboard
    from common.mission_behavior import create_chamdog_tree
    from common.blackboard import SystemState, UserResponse, MissionMode # [Mod] MissionMode 추가
except ImportError as e:
    try:
        from ipc_manager import get_shared_blackboard
        from mission_behavior import create_chamdog_tree
        from blackboard import SystemState, UserResponse, MissionMode
    except ImportError:
        raise e

# =========================================================
# [Mod] 사용자 입력을 처리하는 리스너 (Q키 기능 추가)
# =========================================================
def input_listener(blackboard):
    """
    키보드 입력을 감시합니다.
    - 'q': 즉시 STANDBY 모드로 강제 전환 (Emergency Intercept)
    - 'y/n': BT의 질문에 대한 응답
    """
    print(f"[Input Listener] 키보드 입력 대기 중... (명령어: Y/n)")
    print(f"                 🚨 언제든 'q'를 누르면 [STANDBY]로 비상 전환됩니다.")
    
    while True:
        try:
            # 1. 사용자 입력 대기 (Blocking)
            user_input = input().strip().lower()
            
            # 2. 종료 명령 체크
            if user_input in ['exit', 'quit']:
                print("[Input] 종료 명령 수신.")
                break
            
            # 3. [NEW] 강제 상태 변경 (Q -> STANDBY)
            # 질문 대기 여부와 상관없이 무조건 최우선으로 처리합니다.
            if user_input == 'q':
                mis = blackboard.get_mission()
                
                # 강제 모드 변경
                prev_mode = mis.active_mission.name
                mis.active_mission = MissionMode.STANDBY
                
                # 혹시 질문 대기 중이었다면 취소 처리 (Clean up)
                if mis.user.is_waiting_for_input:
                    mis.user.is_waiting_for_input = False
                    mis.user.response = UserResponse.NONE
                    print(f" >>> [시스템] 입력 대기 취소됨.")
                
                blackboard.update_mission(mis)
                print(f" >>> [🚨 긴급] 모드 강제 전환! ({prev_mode} -> STANDBY)")
                continue # 루프 처음으로 (아래 로직 건너뜀)

            # 4. 일반 응답 처리 (질문 대기 중일 때만)
            mis = blackboard.get_mission()
            
            if mis.user.is_waiting_for_input:
                if user_input in ['Y', 'y', 'yes', 'start', 'go', 'ok']:
                    mis.user.response = UserResponse.APPROVE
                    print(f" >>> [입력 전달] 승인 (APPROVE)")
                    
                elif user_input in ['n', 'no', 'stop', 'reject']:
                    mis.user.response = UserResponse.REJECT
                    print(f" >>> [입력 전달] 거절 (REJECT)")
                else:
                    print(f" >>> [알림] 알 수 없는 명령어입니다: {user_input} (y/n 또는 q)")
                    continue

                blackboard.update_mission(mis)
                
            else:
                # 질문도 없는데 이상한 키를 누른 경우
                print(f"[Input] 무시됨 (질문 대기 중 아님). 비상 전환은 'q'를 누르세요.")

        except EOFError:
            break
        except Exception as e:
            print(f"[Input Listener] 에러: {e}")
            time.sleep(1)


def main():
    print("=== [BT] ChamDog Behavior Tree 프로세스 시작 ===")

    try:
        blackboard = get_shared_blackboard()
        print("✅ IPC Blackboard 연결 성공!")
    except Exception as e:
        print(f"❌ IPC 연결 실패: {e}")
        print("   -> 'python common/ipc_manager.py'를 먼저 실행했나요?")
        return

    root = create_chamdog_tree(blackboard)
    behaviour_tree = py_trees.trees.BehaviourTree(root)

    t_input = threading.Thread(target=input_listener, args=(blackboard,), daemon=True)
    t_input.start()

    print("[BT] 논리 루프(Tick) 시작...")
    
    try:
        while True:
            behaviour_tree.tick()
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n[BT] 프로세스 종료 요청.")
        
    except Exception as e:
        print(f"\n[BT] ❌ 에러 발생: {e}")
        try:
            sys_data = blackboard.get_system()
            sys_data.state = SystemState.ERROR
            blackboard.update_system(sys_data)
        except:
            pass

if __name__ == "__main__":
    main()