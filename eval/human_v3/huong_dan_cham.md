# Hướng dẫn chấm: câu hỏi trắc nghiệm và phương án sai (đánh giá người, v3)

Tài liệu dành cho **2 người chấm**, chấm độc lập với nhau. Mỗi người nhận **một file Excel** mang tên mình (`Phieu_cham_<Họ_tên>.xlsx`). File gồm các trang:

| Trang | Nội dung | Số dòng | Thời gian ước tính |
|---|---|---|---|
| `0. Hướng dẫn` | Tóm tắt hướng dẫn và bảng **tiến độ** (tự cập nhật khi bạn điền) | | |
| `1. Chấm thử` | Chấm chung để thống nhất tiêu chí, **không tính** vào kết quả | 8 | ~10 phút |
| `2. Câu hỏi` | Mỗi dòng là một câu hỏi | 80 | ~60–80 phút |
| `3. Phương án sai` | Mỗi dòng là một phương án sai của các câu ở trang 2 | 240 | ~60 phút |
| `4. Gán nhãn` | Gán loại hiểu nhầm cho từng phương án sai | 60 | ~40 phút |
| `Bảng loại hiểu nhầm` | Định nghĩa, dấu hiệu và ví dụ của 7 loại hiểu nhầm (cộng `khong_ro`) | | |

**Ô cần điền** có nền **vàng** và tiêu đề cột màu **nâu**. Bấm vào ô rồi chọn giá trị từ mũi tên ▼; ô chỉ nhận đúng các giá trị hợp lệ. Mọi ô khác chỉ để đọc.

Trước khi chấm thật, hai người cùng làm trang `1. Chấm thử`, rồi so kết quả và thống nhất cách hiểu tiêu chí.

## Nguyên tắc

- **Chấm độc lập.** Không trao đổi với người kia và không xem phiếu của họ cho đến khi cả hai chấm xong.
- Các câu trong phiếu đến từ nhiều phiên bản hệ thống khác nhau, xếp theo thứ tự ngẫu nhiên. Đừng đoán phiên bản, chỉ chấm đúng câu đang thấy.
- Mọi đánh giá đúng/sai về kiến thức đều dựa trên cột **Nội dung slide**; cột **Câu trích làm căn cứ** cho biết câu trong slide mà hệ thống đã dùng.
- Khi lưu, giữ nguyên tên file và định dạng **.xlsx**. Không xoá, không sắp xếp lại dòng.
- Chỉ điền các ô vàng (cột điểm và cột Ghi chú).
- Khi phân vân giữa hai mức, chọn mức **thấp hơn** và ghi lý do vào cột Ghi chú.

## Trang 2. Câu hỏi: chấm từng câu hỏi

Ba tiêu chí sau điền **1** (đạt) hoặc **0** (lỗi):

| Cột | Cho 1 khi | Cho 0 khi |
|---|---|---|
| `dung_kien_thuc` | Câu hỏi và đáp án ở cột `dap_an` khớp với slide | Đáp án được đánh dấu là sai, hoặc câu hỏi nói điều slide không có |
| `mot_dap_an_dung` | Chỉ đúng một phương án là đúng; ba phương án còn lại sai rõ theo slide | Có từ hai phương án đúng trở lên, hoặc có phương án "đúng một phần" |
| `tu_dung_duoc` | Người không xem slide vẫn hiểu câu hỏi đang hỏi gì | Câu hỏi có cụm như "theo đoạn trên", "phương pháp này"… mà không nói rõ là gì |

Hai tiêu chí sau điền **từ 1 đến 5**:

| Cột | 1 | 3 | 5 |
|---|---|---|---|
| `ro_rang` | Khó hiểu, đọc được theo nhiều nghĩa | Hiểu được nhưng câu chữ còn gượng | Rõ ràng, tự nhiên, hỏi đúng một ý |
| `phuong_an_sai_hop_ly` | Các phương án sai vô lý, loại được ngay | Có 1–2 phương án gây phân vân | Cả ba phương án sai đều dễ chọn nhầm với người chưa nắm bài |

## Trang 3. Phương án sai: chấm từng phương án sai

Mỗi dòng là **một** phương án sai, kèm câu hỏi và đáp án đúng để đối chiếu.

| Cột | Giá trị | Ý nghĩa |
|---|---|---|
| `chac_chan_sai` | 1 / 0 | Cho **1** nếu phương án này chắc chắn **không** phải câu trả lời đúng cho câu hỏi. Một phương án tự nó đúng nhưng lệch khỏi điều câu hỏi hỏi vẫn được tính là sai. Cho **0** nếu có thể cãi rằng nó cũng đúng. |
| `hop_ly` | 1–5 | Một sinh viên **chưa nắm chắc bài** có dễ chọn phương án này không. 1 = loại được ngay (sai hiển nhiên, lạc đề, sai ngữ pháp, dài/ngắn khác hẳn). 3 = có thể phân vân. 5 = rất dễ chọn nhầm. |
| `the_hien_hieu_nham` | 1 / 0 | Cho **1** nếu phương án này phản ánh **một kiểu hiểu sai cụ thể và gọi tên được** (xem bảng loại hiểu nhầm bên dưới). Cho **0** nếu nó chỉ sai ngẫu nhiên, không cho thấy người chọn đã hiểu nhầm điều gì. |

Ví dụ minh hoạ. Câu hỏi: *"Perplexity của mô hình ngôn ngữ trên tập thử càng thấp thì sao?"*, đáp án đúng: *"Mô hình dự đoán tập thử càng tốt"*.
- Phương án "Mô hình dự đoán tập thử càng kém": `chac_chan_sai`=1, `hop_ly`=4, `the_hien_hieu_nham`=1 (sai một chi tiết then chốt: đảo tốt↔kém).
- Phương án "Mô hình có càng nhiều tham số": `chac_chan_sai`=1, `hop_ly`=2, `the_hien_hieu_nham`=0 (sai nhưng không cho thấy hiểu nhầm cụ thể nào).

## Trang 4. Gán nhãn: chọn loại hiểu nhầm

Với mỗi phương án sai, chọn ở cột **Loại hiểu nhầm** **đúng một mã** trong bảng dưới. Hãy chọn loại giải thích tốt nhất *vì sao một sinh viên lại chọn phương án này*.

| Mã | Tên | Dấu hiệu nhận biết | Ví dụ |
|---|---|---|---|
| `nham_khai_niem_lan_can` | Nhầm với khái niệm lân cận | Phương án mô tả đúng một khái niệm **khác** có thật trong bài | Hỏi định nghĩa TF-IDF nhưng chọn mô tả của BM25 |
| `khai_quat_qua_muc` | Khái quát quá mức | Lấy một ý chỉ đúng trong một số trường hợp rồi nói như đúng cho mọi trường hợp | "Làm mịn Laplace giúp mọi mô hình ngôn ngữ chính xác hơn" |
| `dao_nhan_qua` | Đảo nhân quả | Giữ đúng hai thành phần nhưng đảo chiều quan hệ giữa chúng | "Perplexity thấp làm cho xác suất gán cho câu thử cao" |
| `sai_thu_tu_buoc` | Sai thứ tự các bước | Có đủ các bước đúng nhưng sắp sai trình tự | "Tính IDF trước, rồi mới tách từ văn bản" |
| `gan_nham_thuoc_tinh` | Gán nhầm thuộc tính | Nói về đúng khái niệm được hỏi nhưng gán cho nó đặc điểm của khái niệm khác | "RNN xử lý song song toàn bộ chuỗi trong một bước" |
| `dung_nhung_khong_tra_loi` | Đúng nhưng không trả lời câu hỏi | Tự nó đúng theo bài nhưng lệch trọng tâm câu hỏi | Hỏi mục đích của làm mịn, chọn "n-gram dựa trên phép đếm" |
| `sai_mot_chi_tiet` | Sai một chi tiết then chốt | Gần trùng đáp án đúng, chỉ khác một từ hoặc con số quyết định nghĩa | "Perplexity càng cao thì mô hình càng tốt" |
| `khong_ro` | Không rõ | Không loại nào ở trên phù hợp, hoặc phương án sai một cách ngẫu nhiên | — |

Một số cặp loại dễ nhầm:
- **`nham_khai_niem_lan_can` và `gan_nham_thuoc_tinh`.** Nếu phương án nói về khái niệm **khác** thì chọn loại thứ nhất. Nếu phương án nói về **đúng** khái niệm được hỏi nhưng gán đặc điểm sai thì chọn loại thứ hai.
- **`sai_mot_chi_tiet` và `dao_nhan_qua`.** Nếu chiều quan hệ nguyên nhân–kết quả bị đảo thì chọn `dao_nhan_qua`. Nếu chỉ một từ hoặc một con số bị đổi thì chọn `sai_mot_chi_tiet`.
- Phương án có thể khớp với hai loại thì chọn loại **nổi bật hơn** và ghi loại còn lại vào `ghi_chu`.

## Sau khi chấm xong

Lưu file (giữ nguyên tên) và gửi lại cho người phụ trách. Người phụ trách chạy `scripts\6_phan_tich_phieu_nguoi.bat` để tính độ đồng thuận giữa hai người chấm (kappa). Với các câu hai người cho điểm khác nhau, hai người không cần thống nhất lại: kết quả chính dùng **trung bình** điểm của hai người, và độ đồng thuận được báo cáo riêng.
