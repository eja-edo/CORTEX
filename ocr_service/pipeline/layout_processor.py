import json
from pathlib import Path
from typing import Any

def reconstruct_layout(regions, y_tolerance=12, x_tolerance=45, char_px_width=15):
    """
    Hàm phục hồi layout cho 1 danh sách các regions (của 1 frame)
    - y_tolerance: Khoảng cách chênh lệch trục Y tối đa để gom vào cùng 1 dòng
    - x_tolerance: Khoảng cách chênh lệch trục X tối đa để bị coi là tách cột
    - char_px_width: Tỷ lệ quy đổi pixel ra khoảng trắng. (Khoảng 15-20 là đẹp cho màn Full HD).
    """
    if not regions:
        return ""

    # Bước 1: Tính toán tọa độ tâm Y (cy) cho từng box
    processed_regions = []
    for r in regions:
        x_min, y_min, x_max, y_max = r["bbox"]
        cy = (y_min + y_max) / 2  # Tâm trục Y
        processed_regions.append({
            "text": r["text"],
            "x_min": x_min,
            "x_max": x_max,
            "cy": cy
        })

    # Sắp xếp tất cả text từ trên xuống dưới (theo trục Y)
    processed_regions.sort(key=lambda item: item["cy"])

    # Bước 2: Gom dòng (Line clustering)
    lines = []
    current_line = []

    for region in processed_regions:
        if not current_line:
            current_line.append(region)
        else:
            avg_cy = sum(r["cy"] for r in current_line) / len(current_line)
            if abs(region["cy"] - avg_cy) <= y_tolerance:
                current_line.append(region)
            else:
                lines.append(current_line)
                current_line = [region]
    if current_line:
        lines.append(current_line)

    # Bước 3: Sắp xếp theo X và dùng "Khoảng Trắng Tuyệt Đối" để giữ đúng CỘT
    formatted_text = []
    for line in lines:
        line.sort(key=lambda item: item["x_min"]) # Sắp xếp theo X
        
        line_str = ""
        current_x = 0
        
        for region in line:
            text = region["text"].strip()
            x_min = region["x_min"]
            x_max = region["x_max"]
            
            # Tính khoảng cách pixel từ chữ trước đó (hoặc lề trái màn hình) đến chữ hiện tại
            gap = x_min - current_x
            
            if gap > x_tolerance:
                # Chuyển khoảng cách Pixel thành số lượng khoảng trắng (Space)
                num_spaces = int(gap / char_px_width)
                
                if line_str == "":
                    # NẾU LÀ CHỮ ĐẦU TIÊN TRONG DÒNG
                    # Nếu nó nằm thụt sâu vào trong (ví dụ x_min > 200px), ta phải đẩy nó vào bằng Space 
                    # và chèn thêm | để nhận diện nó thuộc cột khác
                    if x_min > 200:
                        pad_spaces = max(0, num_spaces - 2)
                        line_str += (" " * pad_spaces) + "| " + text
                    else:
                        # Nằm sát lề trái thì chỉ cần thụt lề nhẹ, không cần |
                        line_str += (" " * num_spaces) + text
                else:
                    # NẾU LÀ CHỮ THỨ 2, 3.. TRONG DÒNG
                    # Cách xa chữ trước -> Chèn Space tương ứng và dấu |
                    pad_spaces = max(1, num_spaces - 2)
                    line_str += (" " * pad_spaces) + "| " + text
            else:
                # Gần chữ trước đó (gap nhỏ) -> Nối thành cụm từ
                if line_str == "":
                    line_str = text
                else:
                    line_str += " " + text
            
            # Cập nhật vị trí X kết thúc của cụm từ vừa thêm vào
            current_x = x_max
            
        formatted_text.append(line_str)

    return "\n".join(formatted_text)


def process_metadata_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    y_tolerance: int = 12,
    x_tolerance: int = 45,
    char_px_width: int = 15,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    input_path = Path(input_path)
    if verbose:
        print(f"Đang đọc dữ liệu từ: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    processed_data = []

    for frame in raw_data:
        frame_id = frame.get("frame_id")
        timestamp = frame.get("timestamp")
        regions = frame.get("regions", [])
        
        # Tiền xử lý layout
        clean_text = reconstruct_layout(
            regions,
            y_tolerance=y_tolerance,
            x_tolerance=x_tolerance,
            char_px_width=char_px_width,
        )
        if verbose:
            print(f"--- Frame ID: {frame_id}, Timestamp: {timestamp} ---")
            print(f"{clean_text}\n\n\n")
        
        processed_data.append({
            "frame_id": frame_id,
            "timestamp": timestamp,
            "processed_text": clean_text
        })

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if verbose:
            print(f"Đang lưu dữ liệu đã xử lý ra: {output_path}")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=4)

    if verbose:
        print(f"Hoàn thành! Đã xử lý {len(processed_data)} frames.")

    return processed_data