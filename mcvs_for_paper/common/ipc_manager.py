# common/ipc_manager.py

from multiprocessing.managers import BaseManager

from common.blackboard import Blackboard

# 1. 설정
SERVER_ADDRESS = ('127.0.0.1', 50000)
AUTH_KEY = b'chamdog_secret'

# ==============================================================================
# [핵심 수정] 전역 공유 인스턴스 생성 (Singleton)
# 서버 프로세스가 시작될 때 딱 한 번만 생성됩니다.
# ==============================================================================
_shared_blackboard_instance = None

def get_blackboard_instance():
    """
    요청이 올 때마다 매번 새로 만드는 게 아니라,
    미리 만들어둔 '그 놈(_shared_blackboard_instance)'을 반환합니다.
    """
    global _shared_blackboard_instance
    if _shared_blackboard_instance is None:
        _shared_blackboard_instance = Blackboard()
    return _shared_blackboard_instance

class BlackboardManager(BaseManager):
    pass

# [수정] 클래스(Blackboard) 대신 '인스턴스를 주는 함수'를 등록합니다.
BlackboardManager.register('blackboard', callable=get_blackboard_instance)

def run_server():
    """[Server Process]"""
    print(f"[IPC Manager] Blackboard 공유 서버 시작 {SERVER_ADDRESS}...")
    
    # 서버 실행 시점에 인스턴스 초기화
    global _shared_blackboard_instance
    _shared_blackboard_instance = Blackboard()
    
    manager = BlackboardManager(address=SERVER_ADDRESS, authkey=AUTH_KEY)
    server = manager.get_server()
    print("[IPC Manager] 서버 실행 중. (Ctrl+C로 종료)")
    print("   >>> 모든 프로세스가 '하나의 Blackboard'를 공유합니다.")
    server.serve_forever()

def get_shared_blackboard():
    """[Client Process]"""
    # print(f"[IPC Client] 서버 연결 시도 {SERVER_ADDRESS}...")
    manager = BlackboardManager(address=SERVER_ADDRESS, authkey=AUTH_KEY)
    try:
        manager.connect()
        # print("[IPC Client] ✅ 연결 성공!")
        return manager.blackboard() 
    except ConnectionRefusedError:
        # print("[IPC Client] ❌ 연결 실패!")
        raise

if __name__ == "__main__":
    run_server()