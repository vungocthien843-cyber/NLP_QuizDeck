# Đánh giá chất lượng câu hỏi (MCQ)

Thư mục này trả lời 3 câu hỏi cho báo cáo:

1. Câu hỏi hệ thống giữ lại có đúng và dùng được không? **Người chấm** là thước đo chính.
2. Bộ lọc bằng luật có loại oan hoặc bỏ sót nhiều không?
3. Ngoài mẫu người chấm, phần còn lại của ngân hàng có câu nào nghi sai đáp án không? **Judge** (`gpt-6-sol`) làm lại mọi câu để đánh dấu.

## Thứ tự thực hiện

| # | Việc | Ai làm | Tốn API? |
| --- | --- | --- | --- |
| 0 | Chuẩn bị dữ liệu | Bạn | Có (sinh câu hỏi) |
| 1 | Đóng băng dữ liệu | Chạy lệnh | Không |
| 2 | Thống kê tự động | Chạy lệnh | Không |
| 3 | Tạo phiếu chấm | Chạy lệnh | Không |
| 4 | Chấm phiếu, tính độ đồng thuận | 2 người chấm, rồi chạy lệnh | Không |
| 5 | Chạy judge | Chạy lệnh | Có, khoảng 0,1 USD cho 70 câu |
| 6 | Đánh giá chính judge | Chạy lệnh | Có, khoảng 0,1 USD |

Bước 2 và bước 5 có thể làm trước khi chấm xong. Bước 6 nên chạy sau khi đã chốt phiếu ở bước 4 để có phần so với người.

Mọi lệnh chạy từ thư mục gốc dự án, khi Docker đang chạy. Kết quả dùng cho báo cáo nằm ở `results/`.

## Bước 0: Chuẩn bị dữ liệu

- [ ] Có API key OpenAI còn hiệu lực trong `.env`.
- [ ] Nạp đủ các bài trong `slides/` qua giao diện, chờ tất cả về trạng thái `ready`. Hiện mới có Bài 1 và Bài 2 đang hoạt động.
- [ ] Không thay đổi prompt hoặc model sau bước này. Nếu đổi thì câu hỏi cũ không còn đại diện cho hệ thống, phải sinh lại và làm lại từ bước 1.

Nếu vừa cập nhật `docker-compose.yml` hoặc `config.yaml`, chạy `docker compose up -d api` một lần.

## Bước 1: Đóng băng dữ liệu

```
docker compose exec api python -m eval.mcq.step1_snapshot
```

Ghi các câu hỏi của tài liệu đang hoạt động vào `data/snapshot*.json*`. Câu của pipeline cũ bị loại tự động. Từ đây, mọi bước chỉ đọc snapshot, nên kết quả không đổi khi ngân hàng thay đổi.

## Bước 2: Thống kê tự động

```
docker compose exec api python -m eval.mcq.step2_stats
```

Kết quả: `results/thong_ke.csv`.

| Nhóm | Cách đọc |
| --- | --- |
| `ti_le_accepted` | Tỉ lệ câu qua được bộ lọc. Cao chưa chắc là tốt: có thể do luật quá lỏng, phải xem cùng kết quả người chấm. |
| `pheu_loai` | Luật nào loại nhiều nhất. Dùng để sửa prompt. |
| `dat_theo_lan_thu` | Sinh lại kèm lý do có giúp qua được không. |
| `dat_muc_tieu` | Số câu đạt so với số slide × 0,5. |
| `do_phu_slide` | Tỉ lệ chunk có câu hỏi. Mục tiêu là 0,5 câu mỗi slide, nên con số quanh 0,5 là bình thường. |
| `phan_bo_bloom` | So với cấu hình 40/40/20. |
| `vi_tri_dap_an` | p > 0,05 nghĩa là chưa thấy đáp án bị dồn vào vị trí nào. |
| `trung_lap` | Số cặp câu quá giống nhau. Kỳ vọng bằng 0 vì đã có bước chống trùng. |

## Bước 3: Tạo phiếu chấm

```
docker compose exec api python -m eval.mcq.step3_sample
```

Tạo trong `data/`:

| File | Dùng để |
| --- | --- |
| `phieu_cham_thu.csv` | 10 câu hai người chấm chung để thống nhất tiêu chí. Không tính vào kết quả. |
| `phieu_cham_nguoi1.csv`, `phieu_cham_nguoi2.csv` | Phiếu chính: tối đa 40 câu accepted và 20 câu rejected, trộn ngẫu nhiên. |
| `khoa_mau.csv` | Cho biết câu nào accepted hay rejected. **Người chấm không mở file này.** |

Lệnh từ chối ghi đè phiếu đã có, để tránh mất điểm đã chấm. Cùng seed thì luôn ra cùng một mẫu.

## Bước 4: Chấm phiếu và tính độ đồng thuận

1. Hai người đọc [huong_dan_cham.md](huong_dan_cham.md), chấm chung `phieu_cham_thu.csv`, thống nhất các chỗ hiểu khác nhau.
2. Mỗi người tự chấm phiếu của mình, không trao đổi và không xem phiếu của người kia.
3. Lưu lại đúng tên file, định dạng CSV, rồi chạy:
   ```
   docker compose exec api python -m eval.mcq.step4_agreement
   ```
   Lệnh báo rõ ô nào thiếu hoặc sai để sửa. Khi đủ điểm, lệnh ghi `results/dong_thuan.csv` và tạo `data/phieu_chot.csv`.
4. Trong `phieu_chot.csv`, câu hai người giống nhau đã điền sẵn. Hai người thảo luận và điền các ô trống.
5. Chạy lại lệnh trên. Kết quả: `results/chat_luong.csv`.

**Cách đọc kết quả**

| Chỉ số | Ý nghĩa |
| --- | --- |
| `ti_le_cau_accepted_dat` | **Con số quan trọng nhất**: tỉ lệ câu hệ thống giữ lại mà người chấm cho đạt, kèm khoảng tin cậy 95%. |
| `precision_bo_loc` | Trong câu bộ lọc giữ lại, bao nhiêu câu tốt. |
| `recall_bo_loc` | Trong các câu tốt, bộ lọc giữ được bao nhiêu. Đã quy về quy mô thật của từng nhóm, vì mẫu lấy dư câu rejected. |
| `ti_le_loai_oan` | Câu bị loại nhưng người chấm cho đạt. Nhóm này thường ít câu nên chỉ để tham khảo. |
| `kappa` | Độ đồng thuận ngoài yếu tố ngẫu nhiên. Thường đọc: trên 0,6 là khá, trên 0,8 là rất tốt. |

Khi gần như mọi câu đều đạt, kappa có thể rất thấp dù hai người gần như giống hệt nhau. Kappa cũng không xác định nếu cả hai cho cùng một điểm ở mọi câu. Vì vậy báo cáo nên ghi cả `ti_le_giong_nhau`.

## Bước 5: Chạy judge

Chạy thử 5 câu để xem output và chi phí:

```
docker compose exec api python -m eval.mcq.step5_judge --limit 5
```

Rồi chạy phần còn lại (câu đã có kết quả được bỏ qua):

```
docker compose exec api python -m eval.mcq.step5_judge
```

Judge nhận slide nguồn, câu hỏi và 4 phương án đã xáo, rồi chọn một phương án hoặc `NONE`. Những câu judge chọn khác đáp án đã lưu, hoặc chọn `NONE`, nằm trong `results/judge_nghi_ngo.csv`. Hãy đọc lại từng câu trong file này, vì judge chỉ đánh dấu chứ không tự loại câu nào.

## Bước 6: Đánh giá chính judge

```
docker compose exec api python -m eval.mcq.step6_judge_check
```

Kết quả: `results/danh_gia_judge.csv`.

| Tiêu chí | Cách đo | Mong muốn |
| --- | --- | --- |
| `so_voi_nguoi_precision` | Câu judge đánh dấu, người chấm cũng thấy lỗi | Cao: ít báo động giả |
| `so_voi_nguoi_recall` | Câu người chấm thấy lỗi, judge cũng đánh dấu | Cao: ít bỏ sót |
| `cai_loi_chon_NONE` | Thay phương án đúng bằng đáp án của câu khác; judge phải chọn `NONE` | Cao |
| `cai_loi_chon_phuong_an_gia` | Trong phép thử trên, judge chọn đúng phương án giả | Thấp |
| `sai_ngu_canh_chon_NONE` | Đưa slide của bài khác; judge phải chọn `NONE` | Cao |
| `on_dinh_giong_lan_truoc` | Chạy lại, so với bước 5 | Cao |

Phép thử cài lỗi không chỉ đổi chữ cái đáp án đã lưu, vì judge không thấy đáp án đó nên kết quả sẽ không đổi. Nó thay chính nội dung phương án đúng để câu không còn đáp án đúng.

Khi báo cáo, ghi rõ hạn chế: `gpt-6-sol` cùng họ với model sinh nên có thể mắc lỗi giống nhau. Judge đồng ý không chứng minh câu đó đúng.

## Hạn chế cần nêu trong báo cáo

- Judge chỉ thấy chunk có trong `source_chunk_ids`, vì DB không lưu chunk bổ trợ mà câu hỏi không dùng. Câu thật sự cần chunk khác có thể bị chọn `NONE`.
- Khi nhóm rejected ít câu, `recall_bo_loc` và `ti_le_loai_oan` có sai số lớn.
- Thống kê so với người chỉ đại diện cho các bài đã nạp lúc đóng băng.
