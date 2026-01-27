import os
from pathlib import Path
from PIL import Image

# HEIC 파일 지원 (pillow-heif가 설치되어 있으면 사용)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False


def rename_images(folder_path, prefix="image", start_number=0, padding=4, 
                  output_format=None, keep_original=False):
    """
    특정 폴더의 이미지 파일 이름을 일괄 변경하고, 필요시 다른 형식으로 변환합니다.
    
    Args:
        folder_path (str): 이미지가 있는 폴더 경로
        prefix (str): 새 파일명의 접두사 (기본값: "image")
        start_number (int): 시작 번호 (기본값: 0)
        padding (int): 번호 앞에 붙일 0의 개수 (기본값: 4, 예: 0001, 0002)
        output_format (str): 출력 형식 (예: "png", "jpg", "jpeg"). None이면 원본 형식 유지
        keep_original (bool): True면 원본 파일 유지, False면 원본 파일 삭제 (기본값: False)
    """
    # 폴더 경로 확인
    folder = Path(folder_path)
    if not folder.exists():
        print(f"오류: 폴더를 찾을 수 없습니다: {folder_path}")
        return
    
    # 지원하는 이미지 확장자
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.heic'}
    
    # 폴더 내의 모든 이미지 파일 찾기
    image_files = []
    for file in folder.iterdir():
        if file.is_file() and file.suffix.lower() in image_extensions:
            image_files.append(file)
    
    if not image_files:
        print("이미지 파일을 찾을 수 없습니다.")
        return
    
    # 파일명으로 정렬 (일관된 순서 보장)
    image_files.sort(key=lambda x: x.name)
    
    print(f"총 {len(image_files)}개의 이미지 파일을 찾았습니다.")
    print("변경을 시작합니다...\n")
    
    # 파일 이름 변경
    current_number = start_number
    renamed_count = 0
    
    for old_file in image_files:
        # 출력 형식 결정
        if output_format:
            extension = f".{output_format.lower()}"
        else:
            extension = old_file.suffix.lower()
        
        # 새 파일명 생성
        new_name = f"{prefix}_{current_number:0{padding}d}{extension}"
        new_file = folder / new_name
        
        # 중복 확인
        if new_file.exists() and new_file != old_file:
            print(f"경고: {new_name} 파일이 이미 존재합니다. 건너뜁니다.")
            current_number += 1
            continue
        
        # 파일 처리 (형식 변환 또는 이름만 변경)
        try:
            if output_format and old_file.suffix.lower() != extension:
                # HEIC 파일 처리 확인
                if old_file.suffix.lower() == '.heic' and not HEIC_SUPPORTED:
                    print(f"✗ HEIC 파일 처리 불가 ({old_file.name}): pillow-heif 라이브러리가 필요합니다. 'pip install pillow-heif'로 설치하세요.")
                    continue
                
                # 이미지를 다른 형식으로 변환
                img = Image.open(old_file)
                
                # RGBA 모드는 PNG로, RGB 모드는 JPG로 저장 (형식에 따라 자동 처리)
                if output_format.lower() == 'jpg' or output_format.lower() == 'jpeg':
                    # JPG는 RGB 모드만 지원 (알파 채널 제거)
                    if img.mode in ('RGBA', 'LA', 'P'):
                        rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                        img = rgb_img
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                
                # 이미지 저장
                img.save(new_file, format=output_format.upper())
                print(f"✓ {old_file.name} → {new_name} (형식 변환: {old_file.suffix} → {extension})")
                
                # 원본 파일 삭제 (keep_original이 False일 때)
                if not keep_original:
                    old_file.unlink()
            else:
                # 형식 변환이 필요 없으면 이름만 변경
                old_file.rename(new_file)
                print(f"✓ {old_file.name} → {new_name}")
            
            renamed_count += 1
            current_number += 1
        except Exception as e:
            print(f"✗ 오류 발생 ({old_file.name}): {e}")
    
    print(f"\n완료: {renamed_count}개의 파일이 변경되었습니다.")


if __name__ == "__main__":
    # 사용 예시
    # 폴더 경로를 여기에 입력하세요
    target_folder = "./20250612"  # 변경할 이미지 폴더 경로
    
    # 파일명 형식 설정
    # prefix: 파일명 접두사 (예: "image", "photo", "data" 등)
    # start_number: 시작 번호
    # padding: 번호 자릿수 (4이면 0001, 0002, ... 9999까지)
    # output_format: 출력 형식 (None이면 원본 형식 유지, "png", "jpg" 등 지정 가능)
    # keep_original: True면 원본 파일 유지, False면 원본 파일 삭제
    
    rename_images(
        folder_path=target_folder,
        prefix="250612_img",
        start_number=0,
        padding=3,
        output_format="png",  # 모든 이미지를 PNG로 변환 (None이면 원본 형식 유지)
        keep_original=False   # 원본 파일 삭제 (True면 원본 유지)
    )