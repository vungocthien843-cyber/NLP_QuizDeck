"""Nội dung trang "0. Hướng dẫn" trong phiếu Excel (bản đầy đủ: huong_dan_cham.md)."""

GUIDE: list[tuple[str, str]] = [
    ("Mục đích", "Bạn đánh giá câu hỏi trắc nghiệm do hệ thống tự sinh từ slide bài giảng môn NLP / Thị giác máy tính. "
                 "Trong phiếu có cả câu tốt lẫn câu lỗi, đến từ nhiều phiên bản hệ thống trộn ngẫu nhiên. "
                 "Hãy chấm đúng những gì bạn thấy, đừng đoán phiên bản."),
    ("Nguyên tắc", "• Chấm ĐỘC LẬP: không trao đổi, không xem phiếu của người kia cho tới khi cả hai chấm xong.\n"
                   "• Đúng/sai về kiến thức chỉ dựa vào cột \"Nội dung slide\" (và \"Câu trích làm căn cứ\").\n"
                   "• Phân vân giữa hai mức → chọn mức THẤP hơn và ghi lý do vào cột Ghi chú.\n"
                   "• Chỉ điền ô vàng. Không sửa, không xoá, không sắp xếp lại dòng. Lưu đúng tên file, định dạng .xlsx."),
    ("Thứ tự làm", "1) Trang \"1. Chấm thử\" (8 câu, ~10 phút) → so kết quả với người kia để thống nhất cách hiểu tiêu chí. "
                   "Trang này KHÔNG tính vào kết quả.\n"
                   "2) Trang \"2. Câu hỏi\" (80 câu, ~60–80 phút).\n"
                   "3) Trang \"3. Phương án sai\" (240 dòng, ~60 phút).\n"
                   "4) Trang \"4. Gán nhãn\" (60 dòng, ~40 phút).\n"
                   "Có thể chia nhiều buổi; xem phần Tiến độ ở trên. Tổng ~2,5–3 giờ."),
    ("", ""),
    ("Trang 2. Câu hỏi", "▶ Mỗi dòng một câu hỏi. Ba tiêu chí 0/1 (1 = đạt, 0 = lỗi):"),
    ("  Đúng kiến thức", "1: câu hỏi và đáp án ở cột \"Đáp án đúng\" khớp với slide. 0: đáp án được đánh dấu là sai, "
                         "hoặc câu hỏi nói điều slide không có."),
    ("  Một đáp án đúng", "1: chỉ đúng một phương án đúng, ba phương án còn lại sai rõ theo slide. "
                          "0: có ≥ 2 phương án đúng, hoặc có phương án \"đúng một phần\"."),
    ("  Tự đứng được", "1: không xem slide vẫn hiểu câu hỏi đang hỏi gì. 0: có cụm \"theo đoạn trên\", \"phương pháp này\"… "
                       "mà không nói rõ là gì."),
    ("  Rõ ràng (1–5)", "1 = khó hiểu, đọc được nhiều nghĩa · 3 = hiểu được nhưng câu chữ gượng · 5 = rõ, tự nhiên, hỏi đúng một ý."),
    ("  PA sai hợp lý (1–5)", "1 = các phương án sai vô lý, loại ngay · 3 = có 1–2 phương án gây phân vân · "
                              "5 = cả ba đều dễ nhầm với người chưa nắm bài."),
    ("  Ví dụ một dòng", "Câu \"Vì sao từ phổ biến như 'là', 'của' có TF-IDF thấp?\", đáp án \"Vì chúng xuất hiện trong hầu hết "
                         "văn bản\" → Đúng kiến thức 1 · Một đáp án đúng 1 · Tự đứng được 1 · Rõ ràng 5 · PA sai hợp lý 4."),
    ("", ""),
    ("Trang 3. Phương án sai", "▶ Mỗi dòng MỘT phương án sai (kèm câu hỏi, đáp án đúng; mã câu để tra lại slide ở trang 2):"),
    ("  Chắc chắn sai (0/1)", "1: phương án này chắc chắn KHÔNG phải câu trả lời đúng cho câu hỏi (kể cả khi tự nó là một câu "
                              "đúng nhưng lệch câu hỏi). 0: có thể cãi rằng nó cũng đúng."),
    ("  Hợp lý (1–5)", "Sinh viên CHƯA nắm chắc bài có dễ chọn phương án này không? 1 = loại ngay (sai hiển nhiên, lạc đề, "
                       "dài/ngắn khác hẳn) · 3 = có thể phân vân · 5 = rất dễ chọn nhầm."),
    ("  Thể hiện hiểu nhầm (0/1)", "1: phương án phản ánh MỘT KIỂU HIỂU SAI cụ thể, gọi tên được (xem trang \"Bảng loại hiểu "
                                   "nhầm\"). 0: chỉ sai ngẫu nhiên, không cho thấy người chọn đã hiểu nhầm điều gì."),
    ("  Ví dụ", "Câu \"Perplexity trên tập thử càng thấp thì?\", đáp án \"Mô hình dự đoán tập thử càng tốt\". "
                "PA \"…càng kém\" → 1 · 4 · 1 (đảo một chi tiết then chốt). PA \"Mô hình có càng nhiều tham số\" → 1 · 2 · 0."),
    ("", ""),
    ("Trang 4. Gán nhãn", "▶ Với mỗi phương án sai, chọn ĐÚNG MỘT mã ở cột \"Loại hiểu nhầm\" (bấm ô → ▼). Chọn loại giải thích "
                          "tốt nhất VÌ SAO một sinh viên lại chọn phương án này. Định nghĩa + ví dụ: trang \"Bảng loại hiểu nhầm\"."),
    ("  Cặp dễ nhầm", "• nham_khai_niem_lan_can vs gan_nham_thuoc_tinh: phương án nói về khái niệm KHÁC → loại 1; nói về ĐÚNG khái "
                      "niệm được hỏi nhưng gán đặc điểm sai → loại 2.\n"
                      "• sai_mot_chi_tiet vs dao_nhan_qua: chiều nguyên nhân–kết quả bị đảo → dao_nhan_qua; chỉ đổi một từ/con số → "
                      "sai_mot_chi_tiet.\n"
                      "• Khớp hai loại → chọn loại nổi bật hơn, ghi loại còn lại vào Ghi chú. Không loại nào hợp → khong_ro."),
    ("", ""),
    ("Xong thì", "Lưu file (giữ nguyên tên) và gửi lại cho người phụ trách. Cảm ơn bạn!"),
]
