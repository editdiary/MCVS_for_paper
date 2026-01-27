from datetime import datetime, timezone, timedelta

def convert_timestamp_to_kst(timestamp):
    # 1. Unix Timestamp를 UTC 기준의 datetime 객체로 변환
    dt_utc = datetime.fromtimestamp(timestamp, timezone.utc)
    
    # 2. 한국 시간(KST) 설정: UTC보다 9시간 빠름
    kst_timezone = timezone(timedelta(hours=9))
    
    # 3. UTC -> KST로 변환
    dt_kst = dt_utc.astimezone(kst_timezone)
    
    # 4. 보기 좋게 포맷팅 (년-월-일 시:분:초.밀리초)
    return dt_kst.strftime('%Y-%m-%d %H:%M:%S.%f')

# 로그에 있던 예시 타임스탬프
example_ts = 1763645916.0113769

print(f"Timestamp: {example_ts}")
print(f"한국 시간: {convert_timestamp_to_kst(example_ts)}")