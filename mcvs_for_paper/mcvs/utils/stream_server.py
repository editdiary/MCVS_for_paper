# utils/stream_server.py

import threading
import time
import cv2
import socketserver
from http.server import BaseHTTPRequestHandler, HTTPServer
from utils.config import RUNTIME_OPTIONS # 리사이즈 설정값 로드

# 전역 변수로 최신 프레임 공유
output_frame = None
frame_lock = threading.Lock()

class StreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global output_frame, frame_lock
        
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><head><title>MCVS Multi-View</title></head>')
            self.wfile.write(b'<body style="background:black; color:white; text-align:center;">')
            self.wfile.write(b'<h1>ChamDog Live Vision</h1>')
            self.wfile.write(b'<img src="/video_feed" style="max-width:100%;">')
            self.wfile.write(b'</body></html>')
            
        elif self.path == '/video_feed':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            
            try:
                while True:
                    with frame_lock:
                        if output_frame is None:
                            time.sleep(0.01)
                            continue
                        
                        # JPEG 인코딩 (압축률 80% 정도로 설정하여 속도 확보)
                        ret, buffer = cv2.imencode('.jpg', output_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                        frame_bytes = buffer.tobytes()

                    self.wfile.write(b'--frame\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.end_headers()
                    self.wfile.write(frame_bytes)
                    self.wfile.write(b'\r\n')
                    
                    time.sleep(0.1) # 약 20FPS
                    
            except Exception:
                pass 

class StreamingServer(threading.Thread):
    def __init__(self, host='127.0.0.1', port=50020):
        super().__init__()
        self.host = host
        self.port = port
        self.daemon = True
        self.server = None
        self.target_height = RUNTIME_OPTIONS.get('stream_display_height', 480)

    def run(self):
        print(f"[StreamServer] 멀티뷰 스트리밍 시작: http://{self.host}:{self.port}")
        try:
            # Address Reuse 옵션 추가 (재실행 시 포트 점유 에러 방지)
            socketserver.TCPServer.allow_reuse_address = True
            self.server = HTTPServer((self.host, self.port), StreamHandler)
            self.server.serve_forever()
        except Exception as e:
            print(f"[StreamServer] ❌ 서버 시작 실패: {e}")

    def update_frames(self, img_left, img_zed, img_right=None):
        """
        여러 카메라 이미지를 받아 하나로 합쳐서 송출
        (Left | ZED | Right) 순서로 가로 연결
        """
        global output_frame, frame_lock
        
        images_to_stack = []
        
        # 1. 이미지 수집 및 리사이징 (높이 통일)
        for img, label in [(img_left, "LEFT (YOLO)"), (img_zed, "ZED (PIPE)"), (img_right, "RIGHT")]:
            if img is not None:
                # 높이를 target_height로 맞추고 비율 유지하며 너비 조절
                h, w = img.shape[:2]
                scale = self.target_height / h
                new_w = int(w * scale)
                resized = cv2.resize(img, (new_w, self.target_height))
                
                # 라벨 텍스트 추가 (어떤 카메라인지 구별)
                cv2.putText(resized, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 
                            0.7, (0, 255, 255), 2)
                
                images_to_stack.append(resized)

        if not images_to_stack:
            return

        # 2. 이미지 병합 (Horizontal Concat)
        try:
            combined = cv2.hconcat(images_to_stack)
            
            with frame_lock:
                output_frame = combined
        except Exception as e:
            print(f"[StreamServer] 이미지 병합 실패: {e}")