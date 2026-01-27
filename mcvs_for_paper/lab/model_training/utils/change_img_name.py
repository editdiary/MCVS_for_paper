"""
roboflow로 데이터셋 설정을 하면 확장자가 이상하게 많이 붙는다.
이 파일은 그걸 없애주는 코드이다.
참고로 굉장히 무식하게 for문으로 작성을 하긴 했으나, 동작은 빠르게 잘 하니까 그냥 만족하고 써도 될 거 같다.
"""
import os

# 데이터셋이 담겨 있는 상위 경로만 맞춰주자
data_path = "/home/leedh/바탕화면/MCT_for_ChamDog/detection/dataset"

folders = ["train", "valid", "test"]
for folder in folders:
    folder_path = os.path.join(data_path, folder)
    extensions = [".jpg", ".jpeg", ".png", '.txt']

    for sub_folder in ["images", "labels"]:
        sub_folder_path = os.path.join(folder_path, sub_folder)
        files = [f for f in os.listdir(sub_folder_path) if f.lower().endswith(tuple(extensions)) and os.path.isfile(os.path.join(sub_folder_path, f))]
        files_sorted = sorted(files)  # 파일명 기준 정렬
        len(files_sorted)

        # 순차적으로 이름 변경
        for idx, filename in enumerate(files_sorted):
            origin_name = filename.split('.')[0][:-4]
            ext = filename.split('.')[-1]

            new_name = f"{origin_name}.{ext}"

            src = os.path.join(sub_folder_path, filename)
            dst = os.path.join(sub_folder_path, new_name)
            # print(src, dst)   # 디버깅용
            os.rename(src, dst)

print("이미지 이름 변경 완료!")