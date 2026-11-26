# Hướng dẫn chấm phiếu `phieu_cham.csv`

Bạn chấm 50 câu trắc nghiệm do hệ thống sinh ra từ slide môn Xử lý ngôn ngữ tự nhiên. Các câu đến từ hai phiên
bản khác nhau và đã bị trộn, ẩn nhãn. Hãy chấm từng câu theo đúng những gì bạn thấy, không đoán câu thuộc phiên
bản nào.

## Nguyên tắc

- Không mở `khoa.csv` cho đến khi chấm xong.
- Đúng sai về kiến thức chỉ dựa vào cột `noi_dung_slide`. Có thể dùng hiểu biết của mình để đánh giá độ hợp lý
  của phương án sai, nhưng không dùng để "cứu" một đáp án mà slide không chứng minh.
- Mở bằng Excel, bật Wrap Text. Khi lưu giữ đúng tên file và định dạng CSV (UTF-8).
- Chỉ điền các cột chấm và `ghi_chu`, không sửa cột có sẵn.
- Nên chấm thành 2–3 đợt, mỗi đợt khoảng 1 giờ, để không mệt rồi chấm dễ dãi dần.

## Thang 1–5 (R1–R6)

| Cột | Câu hỏi đặt ra | 1 | 3 | 5 |
|---|---|---|---|---|
| `R1_chinh_xac` | Nội dung câu hỏi và đáp án có đúng với slide? | Sai kiến thức hoặc đáp án sai | Đúng nhưng diễn đạt chưa chuẩn | Hoàn toàn chính xác |
| `R2_dung_duy_nhat` | Có đúng một đáp án đúng, không gây tranh cãi? | Có phương án khác cũng đúng | Có phương án "đúng một phần" gây phân vân | Duy nhất một đáp án đúng, rõ ràng |
| `R3_trong_tam` | Câu hỏi có hỏi kiến thức quan trọng của bài? | Chi tiết vụn vặt (tên người, số trang, bố cục slide) | Kiến thức phụ | Ý chính của bài |
| `R4_muc_nhan_thuc` | Có kiểm tra sự hiểu, không chỉ nhớ nguyên văn? | Chép nguyên câu slide, chỉ cần nhớ chữ | Cần hiểu một chút | Phải hiểu, giải thích, so sánh hoặc vận dụng |
| `R5_nhieu_hop_ly` | Phương án sai có đủ hợp lý với người chưa nắm bài? | Sai hiển nhiên, vô nghĩa hoặc lạc đề | 1–2 phương án gây phân vân | Cả 3 đều dễ nhầm với người chưa nắm bài |
| `R6_khong_lo_dap_an` | Có đoán được đáp án nhờ độ dài, từ ngữ, hình thức không? | Đoán được ngay không cần kiến thức | Có gợi ý nhẹ | Không thể đoán nhờ hình thức |

Điểm 2 và 4 dùng cho trường hợp nằm giữa các mức.

**Dấu hiệu lộ đáp án thường gặp (R6):** đáp án đúng dài và chi tiết hơn hẳn; đáp án đúng lặp lại từ trong câu
hỏi; phương án sai dùng từ tuyệt đối ("luôn", "mọi", "chỉ"); ba phương án sai đều là biến thể của đáp án đúng
(chọn phương án "ở giữa" là trúng); phương án sai khác loại với đáp án đúng.

## Quyết định (R7): điền đúng một trong ba giá trị

| Giá trị | Khi nào |
|---|---|
| `dung_ngay` | Đưa vào đề được ngay, không cần sửa |
| `sua_nhe` | Dùng được nếu sửa vài chữ hoặc thay một phương án sai |
| `loai` | Phải bỏ: sai kiến thức, nhiều đáp án đúng, hoặc cần viết lại phần lớn |

## Đúng/sai (J1, J2): điền 1 hoặc 0

Hai cột này dùng để kiểm tra độ tin cậy của AI chấm tự động sau này, nên chấm chặt.

| Cột | Điền 1 khi | Điền 0 khi |
|---|---|---|
| `J1_dap_an_co_can_cu` | Slide chứng minh được đáp án ở cột `dap_an` | Slide không nói, hoặc nói khác |
| `J2_mot_dap_an_dung` | Đáp án ở cột `dap_an` đúng và 3 phương án còn lại đều sai theo slide | Có phương án khác cũng đúng hoặc đúng một phần, hoặc đáp án sai |

Nếu `J2 = 0` vì có phương án khác cũng đúng, ghi chữ cái của phương án đó vào `phuong_an_cung_dung` (ví dụ `C`
hoặc `B,D`).

## Ví dụ

Slide: *"Mỗi trong V từ nhận thêm k lần giả nên mẫu số phải cộng k·V."*
Câu hỏi: *"Vì sao mẫu số trong add-k phải tăng theo số từ có thể đứng sau ngữ cảnh?"*

- A. Để mẫu số tính cả k lần giả được cộng cho từng từ trong V. *(đáp án)*
- B. Để tăng tổng xác suất cho từng từ trong V.
- C. Để tổng xác suất bằng 1, rồi mới cộng k lần giả cho từng từ trong V.
- D. Để mẫu số tính cả k lần giả được cộng cho mọi từ trong toàn bộ kho từ.

Chấm gợi ý: R1 = 5; R2 = 3 (C đúng một phần: tổng bằng 1 đúng là mục đích); R3 = 5; R4 = 4; R5 = 4; R6 = 4;
R7 = `sua_nhe`; J1 = 1; J2 = 0, `phuong_an_cung_dung` = C.

## Sau khi chấm

Lưu file, báo lại. Kết quả được tính bằng `python -m eval.quality.human_score`.
