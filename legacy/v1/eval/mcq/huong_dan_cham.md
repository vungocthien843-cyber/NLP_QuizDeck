# Hướng dẫn chấm câu hỏi

Dành cho người chấm. Bạn đánh giá câu hỏi trắc nghiệm do hệ thống sinh ra từ slide bài giảng. Trong phiếu có cả câu tốt lẫn câu có lỗi, nên hãy chấm theo đúng những gì bạn thấy.

## Nguyên tắc

- Chấm độc lập. Không trao đổi và không xem phiếu của người kia cho đến khi chấm xong.
- Không mở file `khoa_mau.csv`.
- Chỉ dựa vào cột `noi_dung_slide` để xác định đúng sai về kiến thức. Nếu slide không đủ căn cứ, cho 0 ở tiêu chí liên quan.
- Mở file bằng Excel, bật Wrap Text để đọc. Khi lưu, giữ đúng tên file và định dạng CSV.
- Không sửa nội dung các cột có sẵn. Chỉ điền các cột điểm và `ghi_chu`.

## Tiêu chí đạt/lỗi: điền 1 (đạt) hoặc 0 (lỗi)

Câu chỉ được tính là đạt khi cả 4 tiêu chí đều bằng 1.

| Cột | Cho 1 khi | Cho 0 khi |
| --- | --- | --- |
| `dung_kien_thuc` | Câu hỏi và đáp án đúng khớp với slide | Đáp án đã đánh dấu sai, hoặc câu hỏi nói điều slide không có |
| `mot_dap_an_dung` | Chỉ một phương án đúng; 3 phương án còn lại sai rõ ràng theo slide | Có từ 2 phương án đúng, hoặc có phương án "đúng một phần" |
| `evidence_chung_minh` | Câu trong cột `evidence` thật sự chứng minh đáp án đúng | Câu trích không liên quan, hoặc chưa đủ để kết luận đáp án |
| `tu_dung_duoc` | Người không thấy slide vẫn hiểu câu hỏi đang hỏi gì | Câu hỏi viết "theo đoạn trên", hoặc thiếu thông tin nên không hiểu được |

## Tiêu chí thang điểm: điền từ 1 đến 5

| Cột | 1 | 3 | 5 |
| --- | --- | --- | --- |
| `ro_rang` | Khó hiểu, có thể hiểu theo nhiều cách | Hiểu được nhưng câu chữ còn gượng | Rõ ràng, tự nhiên, hỏi đúng một ý |
| `phuong_an_sai_hop_ly` | Phương án sai vô lý, loại ngay được | Có 1–2 phương án gây phân vân | Cả 3 đều dễ nhầm với người chưa nắm bài |
| `dung_muc_bloom` | Khác hẳn mức ở cột `muc_bloom` | Gần đúng | Đúng hoàn toàn với mức ở cột `muc_bloom` |

**Các mức Bloom**

- `remember`: nhớ lại điều slide nêu trực tiếp, như định nghĩa, thành phần, mục đích.
- `understand`: phải hiểu bản chất, như giải thích vì sao, phân biệt hai khái niệm, nhận ra ví dụ đúng.
- `apply`: vận dụng vào tình huống mới, như tính toán hoặc chọn phương pháp cho một bài toán cụ thể.

## Ví dụ

Slide viết: *"IDF đo mức độ hiếm của một từ trong tập văn bản: từ xuất hiện trong càng nhiều văn bản thì IDF càng nhỏ."*

**Ví dụ 1: câu đạt**

> Vì sao các từ phổ biến như "là", "của" thường có trọng số TF-IDF thấp?
> Đáp án đúng: Vì chúng xuất hiện trong hầu hết văn bản của tập dữ liệu.

Cả 4 tiêu chí bằng 1. `muc_bloom` là `understand` thì `dung_muc_bloom` được 5.

**Ví dụ 2: sai kiến thức**

> Khi một từ xuất hiện trong nhiều văn bản hơn, IDF thay đổi thế nào?
> Đáp án được đánh dấu đúng: IDF tăng lên.

`dung_kien_thuc` = 0, vì slide nói ngược lại.

**Ví dụ 3: có hai đáp án đúng**

> IDF cho biết điều gì về một từ?
> A. Mức độ hiếm của từ trong tập văn bản (được đánh dấu đúng)
> B. Từ đó xuất hiện trong nhiều hay ít văn bản

`mot_dap_an_dung` = 0, vì B cũng đúng theo slide.

**Ví dụ 4: evidence không chứng minh**

> Đáp án nói về IDF, nhưng cột `evidence` là câu định nghĩa TF.

`evidence_chung_minh` = 0, dù đáp án có thể đúng.

**Ví dụ 5: không tự đứng được**

> Theo đoạn trên, phương pháp này có ưu điểm gì?

`tu_dung_duoc` = 0, vì không biết "phương pháp này" là gì.

## Khi phân vân

- Chọn mức thấp hơn và ghi lý do vào `ghi_chu`.
- Lỗi ở kiến thức trong chính slide (slide viết sai) cũng ghi vào `ghi_chu`, nhưng vẫn chấm theo slide.
- Sau khi chấm độc lập, hai người thảo luận các câu khác nhau và điền kết luận vào `phieu_chot.csv`.
