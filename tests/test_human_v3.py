"""Đánh giá người v3: tạo phiếu → điền giả → phân tích chạy trọn, và báo đúng ô điền sai."""
import importlib
import json
import random
import sys

import pytest

CODES = ["nham_khai_niem_lan_can", "sai_mot_chi_tiet", "dao_nhan_qua", "khong_ro"]


def _fake_inputs(tmp_path):
    data, res = tmp_path / "data_g1", tmp_path / "G1"
    data.mkdir()
    res.mkdir()
    for v in ("V1", "V3"):
        with (data / f"{v}_items.jsonl").open("w", encoding="utf-8") as f:
            for c in range(30):
                f.write(json.dumps({"item_id": f"{v}_{c}", "version": v, "chunk_id": c, "doc_id": c % 3,
                                    "source_context": f"slide {c}", "stem": f"Câu {v} {c}?",
                                    "options": {x: f"{v}{c}{x}" for x in "ABCD"}, "key": "B"},
                                   ensure_ascii=False) + "\n")
    with (res / "questions_C5.jsonl").open("w", encoding="utf-8") as f:
        for c in range(30):
            picked = [{"text": f"nhiễu {c}-{i}", "error_type": CODES[(c + i) % 4]} for i in range(3)]
            f.write(json.dumps({"question": {"stem": f"Câu {c}?", "answer": "đúng", "context": "ctx"},
                                "meta": {"seed_chunk": c, "passed": True, "v2": {"picked": picked}}},
                               ensure_ascii=False) + "\n")
    return data, res


def _load(monkeypatch, tmp_path):
    monkeypatch.setenv("HUMAN_V3_DIR", str(tmp_path / "hv3"))
    mods = {}
    for name in ("common", "xlsx_io", "guide", "tao_phieu", "phan_tich"):
        full = f"eval.human_v3.{name}"
        mods[name] = importlib.reload(importlib.import_module(full)) if full in sys.modules \
            else importlib.import_module(full)
    return mods


def _fill(C, rng):
    from eval.human_v3.xlsx_io import fill_kind, read_kind
    for kind, cols in (("cau_hoi", {**{c: (0, 1) for c in C.Q_BINARY}, **{c: (1, 5) for c in C.Q_SCALE}}),
                       ("dap_an_nhieu", {**{c: (0, 1) for c in C.D_BINARY}, **{c: (1, 5) for c in C.D_SCALE}})):
        base = read_kind(C.workbook("nguoi1"), kind)
        for r in base:
            for c, (lo, hi) in cols.items():
                r[c] = str(rng.randint(lo, hi))
        fill_kind(C.workbook("nguoi1"), kind, base)
        for r in base:                                  # người 2 giống người 1 phần lớn
            for c, (lo, hi) in cols.items():
                if rng.random() < 0.2:
                    r[c] = str(rng.randint(lo, hi))
        fill_kind(C.workbook("nguoi2"), kind, base)
    for rater in C.RATERS:
        rows = read_kind(C.workbook(rater), "nhan")
        for r in rows:
            r["nhan"] = rng.choice(CODES)
        fill_kind(C.workbook(rater), "nhan", rows)


def test_full_human_eval_flow(monkeypatch, tmp_path):
    m = _load(monkeypatch, tmp_path)
    data, res = _fake_inputs(tmp_path)
    monkeypatch.setattr(sys, "argv", ["x", "--data", str(data), "--results", str(res), "--pairs", "20", "--labels", "40",
                                      "--ten", "Bùi Minh Ảnh", "Lê Đình Trung"])
    m["tao_phieu"].main()
    C = m["common"]
    from eval.human_v3.xlsx_io import read_kind
    wb1 = C.workbook("nguoi1")
    assert wb1.name == "Phieu_cham_Bui_Minh_Anh.xlsx" and C.rater_name("nguoi2") == "Lê Đình Trung"
    assert (C.DATA / "gui_Le_Dinh_Trung" / "Phieu_cham_Le_Dinh_Trung.xlsx").exists()
    q = read_kind(wb1, "cau_hoi")
    key = C.read_csv(C.KEY_Q)
    assert len(q) == 40 and len(read_kind(wb1, "dap_an_nhieu")) == 120 and len(read_kind(wb1, "thu")) == 8
    assert "phien_ban" not in q[0] and {k["phien_ban"] for k in key} == {"V1", "V3"}   # ẩn phiên bản
    assert "<chunk" not in q[0]["noi_dung_slide"]
    lab = read_kind(C.workbook("nguoi2"), "nhan")
    assert len(lab) == 40 and "nhan_llm" not in lab[0]
    with pytest.raises(SystemExit):                     # chạy lại không --force: không ghi đè điểm
        m["tao_phieu"].main()
    _fill(C, random.Random(0))
    m["phan_tich"].main()
    rep = (C.RESULTS / "bao_cao_nguoi.md").read_text(encoding="utf-8")
    assert "20 cặp" in rep and "Bùi Minh Ảnh – Lê Đình Trung" in rep and "Độ chính xác nhãn LLM" in rep
    assert (C.RESULTS / "g2_so_sanh.csv").exists() and (C.RESULTS / "g3_ma_tran_nham_lan.csv").exists()


def test_bad_cell_is_reported(monkeypatch, tmp_path):
    m = _load(monkeypatch, tmp_path)
    data, res = _fake_inputs(tmp_path)
    monkeypatch.setattr(sys, "argv", ["x", "--data", str(data), "--results", str(res), "--pairs", "5", "--labels", "5"])
    m["tao_phieu"].main()
    C = m["common"]
    _fill(C, random.Random(1))
    from eval.human_v3.xlsx_io import fill_kind, read_kind
    rows = read_kind(C.workbook("nguoi1"), "cau_hoi")
    rows[0]["ro_rang"] = "7"
    fill_kind(C.workbook("nguoi1"), "cau_hoi", rows)
    with pytest.raises(SystemExit, match="ro_rang"):
        m["phan_tich"].main()
