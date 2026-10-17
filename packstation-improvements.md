# PackStation Improvements & Git Deployment Plan

## Goal
Kiểm tra, cải thiện các lỗi nghiệp vụ và tính năng, đạt 100% test pass, bảo toàn dữ liệu/video hiện có, và thiết lập Git repository an toàn cho PackStation.

## Tasks
- [ ] Task 1: Fix delayed stop cancellation bug (`order_manager.py`) - gắn timer với đúng `order_id` để khi hủy không kết thúc nhầm đơn mới → Verify: Viết test tái hiện và pass trong `test_unit.py`.
- [ ] Task 2: Fix race condition khi 2 lần quét đến đồng thời (`order_manager.py`, `database.py`) - đảm bảo nguyên tử, mỗi bàn chỉ 1 đơn 'packing' → Verify: Viết test đa luồng quét đồng thời trong `test_unit.py`.
- [ ] Task 3: Hoàn thiện tính năng PIN & bảo vệ thông tin đăng nhập camera (`config.py`, `ui/app_window.py`, `README.md`) → Verify: Test xác thực PIN và mask password camera.
- [ ] Task 4: Fix dọn dẹp video & đồng bộ video (`core/video_recorder.py`, `database.py`, `sync_videos.py`) - xóa tham chiếu SQLite khi dọn video; đồng bộ theo cặp `(order_sn, order_date)` tránh ghép nhầm đơn khác ngày; bảo toàn file video/DB hiện có → Verify: Test sync đa ngày và cleanup video record.
- [ ] Task 5: Sửa 2 test đang thất bại (`tests/test_ui_search_e2e.py` và `tests/test_unit.py`) → Verify: Chạy lại unittest discover đạt 100% pass.
- [ ] Task 6: Bỏ `shell=True` khi mở video bằng Explorer (`ui/app_window.py`) → Verify: Kiểm tra code `subprocess.Popen(["explorer", ...])`.
- [ ] Task 7: Thêm `.gitignore` và `packstation-config.example.json` mẫu → Verify: Kiểm tra không chứa secrets, ignore đúng video/db/dist/logs.
- [ ] Task 8: Chạy toàn bộ test suite và audit → Verify: Báo cáo số lượng pass/fail cụ thể.
- [ ] Task 9: Git init, kiểm tra status & diff, commit sạch → Verify: `git status`, `git log`.

## Done When
- Toàn bộ test suite pass 100%.
- Không mất dữ liệu/video hiện có.
- Git repository được khởi tạo, commit sạch sẽ, tuân thủ hướng dẫn remote/push.
