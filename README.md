# PackStation — bản chạy Windows

Đây là bản PackStation đã đóng gói để chạy trên Windows. Không cần cài Python.

## Sử dụng

1. Mở mục **Releases** trên GitHub và tải file ZIP của phiên bản mới nhất.
2. Giữ nguyên cấu trúc thư mục, đặc biệt là `_internal`.
3. Chạy `PackStation.exe`.

Ứng dụng sẽ tạo cấu hình, cơ sở dữ liệu, nhật ký và thư mục video trên máy sử dụng. Các dữ liệu này không thuộc bản phát hành và không nên đẩy lên GitHub.

Nút **Xuất gửi Zalo** trong trang tra cứu đơn tạo bản H.264 ở thư mục `ZaloExports` mà không thay đổi video gốc.

Từ bản v1.5.2, app hiển thị cảnh báo khi camera/ghi hình gặp lỗi và kiểm tra nhanh video sau khi kết thúc đơn. Từ bản v1.5.3, video được ghi theo nhịp 10 khung hình/giây trực tiếp từ luồng camera, độc lập với tốc độ hiển thị giao diện.

Hướng dẫn PDF cũ đã được gỡ khỏi bản phát hành vì không còn khớp với giao diện hiện tại.
