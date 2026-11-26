# Kịch bản thử nghiệm với sinh viên (Mốc 3, G4 và G5)

## Mục tiêu

| Mã | Câu hỏi nghiên cứu | Cách đo |
|---|---|---|
| G4 | Câu hỏi V3 có phân biệt được người nắm bài và người chưa nắm bài tốt hơn V1 không? Phương án sai có "hoạt động" không? Mức khó ước lượng có khớp với thực tế không? Chẩn đoán hiểu nhầm có đúng với suy nghĩ của sinh viên không? | Phân tích câu hỏi trên bài làm thật (p, D, r_pb, tỉ lệ chọn từng phương án sai); khảo sát ngay trong giao diện |
| G5 | Luyện theo điểm yếu có giúp sửa hiểu nhầm tốt hơn luyện đề thường không? | So sánh nhóm A (luyện điểm yếu) và nhóm B (luyện đề thường) ở Đề 2: điểm tiến bộ, tỉ lệ sửa được các slide đã sai, tỉ lệ lặp lại đúng loại hiểu nhầm cũ |

## Thiết kế

- **Hai đề cố định, mỗi đề 15 câu, phủ cùng 15 slide.** Mỗi slide có một câu V1 và một câu V3, đặt ở hai đề khác nhau. Với một nửa số slide, câu V1 nằm ở Đề 1 và câu V3 nằm ở Đề 2; nửa còn lại thì ngược lại. Nhờ vậy mỗi đề có 50% câu V1 và 50% câu V3, và việc câu nằm ở đề trước hay đề sau không trùng với phiên bản (thiết kế đối trọng).
- **Chia nhóm ngẫu nhiên, cân bằng.** Lúc chuẩn bị, mỗi mã được gán ngẫu nhiên vào nhóm A hoặc nhóm B. Ở bước luyện tập, cả hai nhóm làm cùng số câu, cùng phạm vi bài; chỉ khác cách chọn câu. Nhóm B là nhóm đối chứng tích cực: vẫn được luyện, chỉ không nhắm vào điểm yếu. **Sinh viên không biết mình thuộc nhóm nào.**
- Câu thử nghiệm được lưu với trạng thái `experiment`, nên không bao giờ lọt vào đề luyện tập hoặc đề tự tạo. Nhờ vậy đề luyện tập không làm lộ câu của Đề 2.
- **Ba bước, khoảng 60 phút**, làm ngay trong giao diện hệ thống. Cột "Trắc nghiệm" tự hiện khung "🧪 Thử nghiệm" khi sinh viên nhập mã có trong danh sách.

## Chuẩn bị (người tổ chức, khoảng 30 phút, làm trước buổi thử nghiệm)

1. **G1 và `scripts\_da_chay\2_chon_lai_v3.bat` phải xong trước**, vì câu hỏi thử nghiệm được lấy từ kết quả G1 (sau khi chọn lại).
2. **Nếu sinh viên dùng máy riêng** (không phải máy chạy hệ thống):
   - Mở cmd, gõ `ipconfig`, ghi lại địa chỉ IPv4 của máy chủ, ví dụ `192.168.1.20`.
   - Thêm dòng `PUBLIC_API_URL=http://192.168.1.20:8000` vào file `.env`. Nếu bỏ bước này, ảnh slide sẽ không hiện trên máy sinh viên.
   - Cho phép cổng 8000 và 8501 qua Windows Firewall. Lần đầu Windows hỏi thì chọn *Allow*.
   - Sinh viên mở `http://192.168.1.20:8501`. Máy chủ và máy sinh viên phải cùng mạng Wi-Fi/LAN.
3. **Muốn dùng mã sinh viên thật:** tạo file `D:\Project_NLP\eval\student\ma_lop.txt`, mỗi dòng một mã. Nếu không có file này, hệ thống tự tạo 20 mã `sv01` … `sv20`.
4. **Nhấp đúp `scripts\7_thu_nghiem_sv_chuan_bi.bat`.** File lần lượt: sao lưu DB; chạy migration 004; build lại; nhập 30 câu; tạo 2 đề; chia nhóm; mở thử nghiệm.
5. **In hoặc phát `eval\student\data\phat_ma_sinh_vien.csv`** (mỗi sinh viên một mã). **Giữ riêng** `danh_sach_ma.csv` (file có cột nhóm) và `de_thu_nghiem.csv`; không đưa cho sinh viên.
6. **Tự thử trước** bằng một mã trong danh sách, đi hết 3 bước để chắc mọi thứ chạy được. Lưu ý: mã đã thử sẽ có dữ liệu, nên dùng một mã dư và đừng phát mã đó cho sinh viên.

## Trong buổi thử nghiệm (khoảng 60 phút)

| Thời gian | Việc | Ghi chú cho người tổ chức |
|---|---|---|
| 5' | Giới thiệu, phát mã, sinh viên mở hệ thống → cột phải chọn **Trắc nghiệm** → mục **Theo dõi tiến bộ** → nhập mã | Nói rõ: đây là thử nghiệm phần mềm, **không tính điểm**, dữ liệu ẩn danh theo mã; ai không muốn tham gia có thể dừng bất cứ lúc nào |
| 15' | **Bước 1: Đề 1** (15 câu, đồng hồ 15 phút) | **Không xem slide, không dùng trợ lý AI, không trao đổi.** Đề cố định nên mọi người làm cùng một đề |
| 10' | Xem lại câu sai. Ở mỗi câu sai có phần "Có thể bạn đang nhầm", trả lời **Đúng / Một phần / Không đúng**. Sau đó trả lời **2 câu khảo sát** | Nhắc sinh viên đọc kỹ chẩn đoán trước khi chọn. Không trả lời khảo sát thì hệ thống chưa cho sang bước 2 |
| 10' | **Bước 2: Luyện tập** (10 câu) → xem lại → 1 câu khảo sát | Mỗi người nhận một đề khác nhau. Được xem slide khi xem lại kết quả |
| 15' | **Bước 3: Đề 2** (15 câu) | Như Đề 1: không xem slide, không dùng trợ lý AI |
| 3' | Góp ý tự do (không bắt buộc) → khung thử nghiệm báo "đã hoàn thành" | |

**Một số sự cố thường gặp**
- **Lỡ đóng trang hoặc tải lại trang:** nhập lại mã, khung thử nghiệm sẽ tiếp tục đúng bước đang làm. Đề luyện tập làm dở vẫn được giữ.
- **Lỡ làm Đề 1 hai lần:** khi phân tích chỉ lấy lần làm đầu tiên.
- **Không thấy khung 🧪:** kiểm tra mã có đúng không (hệ thống không phân biệt chữ hoa, chữ thường) và mã có trong `danh_sach_ma.csv` không.

## Sau buổi thử nghiệm

1. **Nhấp đúp `scripts\8_thu_nghiem_sv_phan_tich.bat`** để có báo cáo `eval\student\results\bao_cao_sinh_vien.md`, cùng hai file:
   - `phan_tich_cau.csv`: mỗi câu một dòng, gồm p, D, r_pb, tỉ lệ chọn từng phương án sai, loại hiểu nhầm của từng phương án.
   - `theo_sinh_vien.csv`: mỗi sinh viên một dòng, gồm nhóm, điểm hai đề, tỉ lệ sửa được, góp ý.
2. Kết thúc hẳn thì nhấp đúp `scripts\9_thu_nghiem_sv_dong.bat`. Khung 🧪 sẽ biến mất; dữ liệu vẫn giữ và vẫn phân tích lại được.

## Đọc kết quả

- **G4.** Có đủ khoảng 15 sinh viên thì D và r_pb mới tương đối ổn định. Với ít người, chỉ nên nói "có xu hướng".
  - Kết quả mong muốn: D của V3 ≥ D của V1, và V3 có ít phương án sai không hoạt động hơn.
  - Spearman giữa mức khó ước lượng và tỉ lệ đúng âm thì ước lượng mức khó đi đúng chiều.
- **Chẩn đoán.** Tỉ lệ "Đúng" cộng "Một phần" là bằng chứng trực tiếp rằng chẩn đoán hiểu nhầm có ý nghĩa với người học.
- **G5.** Mỗi nhóm chỉ khoảng 10 người, nên **chỉ báo cáo mô tả kèm khoảng tin cậy**, không kết luận nhân quả. Cả hai nhóm đều được xem lại Đề 1 kèm giải thích, nên chênh lệch giữa hai nhóm (nếu có) sẽ nhỏ. Kết quả âm hoặc bằng nhau vẫn là kết quả trung thực và nên đưa vào báo cáo.
- **Câu V1 cũng có chẩn đoán.** Nhãn hiểu nhầm của câu V1 được gắn sau, bằng cùng bước gắn nhãn của V3 (một lần gọi LLM mỗi câu), nên so sánh chẩn đoán giữa hai phiên bản là tương đối công bằng. Khác biệt chính giữa hai phiên bản nằm ở chỗ V3 **chủ động sinh** phương án sai theo hiểu nhầm.
