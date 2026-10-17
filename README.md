# 📦 PackStation

Phần mềm quản lý đóng gói hàng hóa + Camera RTSP giám sát — chuyên dụng cho xưởng e-commerce (Shopee, Lazada, Tiki).

## Tính năng

- 📷 **Camera RTSP dual-lens** — hỗ trợ Imou/Dahua IPC-S2XEP-10M0S
- 🔍 **Quét QR/Barcode tự động** — 3 tầng fallback (pyzbar → OpenCV)
- 🔴 **Quay video bằng chứng** — tự tách 2 file Cam1/Cam2, timestamp watermark
- 📊 **Báo cáo Excel** — thống kê theo ngày, ca làm việc
- 🔐 **Bảo mật** — Mã PIN quản lý (SHA-256) bảo vệ Cài đặt hệ thống, ẩn/mask mật khẩu RTSP camera
- 💻 **Portable** — cắm USB là chạy, không cần cài đặt
- 🧠 **Tối ưu máy yếu** — adaptive FPS, chạy tốt trên i3 Gen 5

## Cấu trúc

```
PackStation/
├── main.py                  # Entry point
├── config.py                # Config management (JSON)
├── database.py              # SQLite WAL database
├── i18n.py                  # Internationalization
├── build.py                 # PyInstaller build script
├── core/
│   ├── camera_manager.py    # RTSP camera streams (OpenCV)
│   ├── barcode_scanner.py   # QR/Barcode scanner (pyzbar)
│   ├── video_recorder.py    # Async video recording
│   ├── order_manager.py     # Order lifecycle management
│   ├── audio_manager.py     # Sound alerts (winsound)
│   ├── startup_manager.py   # Windows auto-start (Registry)
│   ├── dahua_sdk.py         # Dahua/Imou NetSDK integration
│   ├── camera_discovery.py  # ONVIF camera discovery
│   └── logger.py            # Centralized file logging
├── ui/
│   ├── app_window.py        # Main UI (CustomTkinter)
│   └── theme.py             # Color/font design tokens
├── i18n/
│   └── vi-VN.json           # Vietnamese translations
├── tests/
│   └── test_deep_validation.py  # Integration test suite
└── assets/
    ├── icon.ico
    └── logo.png
```

## Yêu cầu phát triển

```bash
pip install -r requirements.txt
```

**Python 3.12+** | Dependencies: `customtkinter`, `opencv-python`, `pyzbar`, `Pillow`, `openpyxl`, `numpy`

## Chạy

```bash
python main.py
```

## Build Portable

```bash
python build.py
```

Output: `dist/PackStation/` → copy vào `C:\PackStation`

## Test

```bash
python tests/test_deep_validation.py
```

## Camera hỗ trợ

| Model | Resolution | Dual-lens | Tested |
|:---|:---:|:---:|:---:|
| Imou IPC-S2XEP-10M0S | 2K (2304×1296) | ✅ | ✅ |
| Dahua IPC-HDW series | 1080p-4K | ❌ | ✅ |
| ONVIF compatible | Any | ❌ | ⚠️ |

## License

Copyright (c) 2024-2026 BA DUY. All rights reserved.
