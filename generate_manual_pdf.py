# -*- coding: utf-8 -*-
"""Generate high-quality user manual PDF for PackStation using headless Edge/Chrome."""
import os
import sys
import base64
import subprocess
import shutil

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    logo_path = os.path.join(base_dir, "assets", "logo.png")
    
    logo_b64 = ""
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode("utf-8")

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>Hướng Dẫn Sử Dụng Phần Mềm PackStation</title>
<style>
    @page {{
        size: A4 portrait;
        margin: 12mm 14mm 14mm 14mm;
    }}
    
    * {{
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }}

    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        color: #1e293b;
        background: #ffffff;
        font-size: 9.5pt;
        line-height: 1.5;
    }}

    /* Cover Page */
    .cover-page {{
        page-break-after: always;
        height: 270mm;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        padding: 40px 20px;
        background: linear-gradient(145deg, #0f172a 0%, #1e293b 100%);
        color: #ffffff;
        border-radius: 8px;
    }}

    .cover-logo {{
        width: 140px;
        height: 140px;
        border-radius: 50%;
        box-shadow: 0 10px 25px rgba(0,0,0,0.4);
        border: 4px solid #f97316;
        margin-bottom: 25px;
        background: #ffffff;
        object-fit: contain;
        padding: 6px;
    }}

    .cover-badge {{
        background: #ea580c;
        color: #ffffff;
        font-size: 11pt;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 2px;
        padding: 6px 20px;
        border-radius: 20px;
        margin-bottom: 20px;
        display: inline-block;
    }}

    .cover-title {{
        font-size: 26pt;
        font-weight: 800;
        letter-spacing: -0.5px;
        margin-bottom: 12px;
        color: #ffffff;
        text-shadow: 0 2px 4px rgba(0,0,0,0.3);
    }}

    .cover-subtitle {{
        font-size: 12.5pt;
        color: #cbd5e1;
        max-width: 520px;
        margin-bottom: 30px;
        font-weight: 400;
        line-height: 1.4;
    }}

    .cover-divider {{
        width: 80px;
        height: 4px;
        background: #f97316;
        border-radius: 2px;
        margin-bottom: 30px;
    }}

    .cover-meta {{
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 8px;
        padding: 16px 24px;
        width: 85%;
        max-width: 480px;
        text-align: left;
        font-size: 9.5pt;
        color: #e2e8f0;
    }}

    .cover-meta table {{
        width: 100%;
        border-collapse: collapse;
    }}

    .cover-meta td {{
        padding: 4px 6px;
    }}

    .cover-meta td:first-child {{
        font-weight: 600;
        color: #fdba74;
        width: 38%;
    }}

    /* Main Content */
    .page {{
        page-break-after: always;
        height: 270mm;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
    }}

    .page-header {{
        border-bottom: 2px solid #f1f5f9;
        padding-bottom: 6px;
        margin-bottom: 14px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 8.5pt;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}

    .page-header strong {{
        color: #ea580c;
    }}

    .page-footer {{
        margin-top: auto;
        border-top: 1px solid #f1f5f9;
        padding-top: 6px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 8pt;
        color: #94a3b8;
    }}

    h1.chapter-title {{
        font-size: 16pt;
        font-weight: 800;
        color: #0f172a;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        border-left: 5px solid #ea580c;
        padding-left: 10px;
    }}

    h2.section-title {{
        font-size: 11.5pt;
        font-weight: 700;
        color: #1e293b;
        margin-top: 12px;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
    }}

    p {{
        margin-bottom: 8px;
        text-align: justify;
    }}

    /* Cards & Containers */
    .card {{
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 10px 14px;
        margin-bottom: 10px;
    }}

    .alert {{
        border-radius: 6px;
        padding: 9px 13px;
        margin-bottom: 10px;
        font-size: 9pt;
        line-height: 1.45;
    }}

    .alert-tip {{
        background: #f0fdf4;
        border-left: 4px solid #16a34a;
        color: #166534;
    }}

    .alert-warning {{
        background: #fffbeb;
        border-left: 4px solid #f59e0b;
        color: #92400e;
    }}

    .alert-info {{
        background: #eff6ff;
        border-left: 4px solid #3b82f6;
        color: #1e40af;
    }}

    /* Workflow steps */
    .step-container {{
        margin-bottom: 8px;
    }}

    .step-item {{
        display: flex;
        align-items: flex-start;
        margin-bottom: 9px;
    }}

    .step-num {{
        width: 24px;
        height: 24px;
        background: #ea580c;
        color: #ffffff;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 9pt;
        flex-shrink: 0;
        margin-right: 10px;
        margin-top: 1px;
    }}

    .step-body {{
        flex-grow: 1;
    }}

    .step-title {{
        font-weight: 700;
        font-size: 10pt;
        color: #0f172a;
        margin-bottom: 2px;
    }}

    /* Tables */
    table.data-table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 6px;
        margin-bottom: 10px;
        font-size: 8.5pt;
    }}

    table.data-table th {{
        background: #1e293b;
        color: #ffffff;
        font-weight: 600;
        text-align: left;
        padding: 6px 8px;
    }}

    table.data-table td {{
        border: 1px solid #e2e8f0;
        padding: 6px 8px;
        vertical-align: top;
    }}

    table.data-table tr:nth-child(even) {{
        background: #f8fafc;
    }}

    /* Badges & Tags */
    .badge {{
        display: inline-block;
        padding: 1px 6px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 7.5pt;
        text-transform: uppercase;
    }}

    .badge-live {{
        background: #dcfce7;
        color: #15803d;
    }}

    .badge-rec {{
        background: #fee2e2;
        color: #b91c1c;
    }}

    .badge-idle {{
        background: #f1f5f9;
        color: #64748b;
    }}

    kbd {{
        background: #e2e8f0;
        color: #334155;
        border-radius: 4px;
        padding: 1px 5px;
        font-size: 8pt;
        font-family: Consolas, monospace;
        border: 1px solid #cbd5e1;
    }}

    /* Barcode Demo Box */
    .barcode-card {{
        border: 2px dashed #94a3b8;
        border-radius: 6px;
        padding: 14px;
        text-align: center;
        background: #ffffff;
        margin: 8px 0;
    }}

    .barcode-title {{
        font-weight: 700;
        font-size: 10.5pt;
        color: #0f172a;
        margin-bottom: 4px;
    }}

    .barcode-box {{
        display: inline-block;
        font-family: "Courier New", Courier, monospace;
        font-size: 18pt;
        letter-spacing: 5px;
        padding: 8px 16px;
        border: 2px solid #0f172a;
        border-radius: 4px;
        font-weight: 800;
        background: #f8fafc;
        margin: 4px 0;
    }}

    .barcode-desc {{
        font-size: 8pt;
        color: #64748b;
    }}

    /* TOC */
    .toc-item {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        padding: 5px 0;
        border-bottom: 1px dotted #cbd5e1;
        font-size: 9.5pt;
    }}
    .toc-title {{
        font-weight: 600;
        color: #0f172a;
    }}
    .toc-page {{
        color: #ea580c;
        font-weight: 700;
    }}

</style>
</head>
<body>

<!-- ═══════════════════════════════════════════
     BÌA SỔ TAY HƯỚNG DẪN (TRANG 1)
     ═══════════════════════════════════════════ -->
<div class="cover-page">
    <img src="data:image/png;base64,{logo_b64}" class="cover-logo" alt="Logo Ba Duy">
    <div class="cover-badge">SỔ TAY VẬN HÀNH TIÊU CHUẨN</div>
    <h1 class="cover-title">HƯỚNG DẪN SỬ DỤNG<br>PACKSTATION</h1>
    <p class="cover-subtitle">Hệ thống Giám Sát Camera Đóng Gói Tự Động, Lưu Trữ Video Đối Soát Khiếu Nại & Quản Lý Năng Suất Nhà Xưởng</p>
    <div class="cover-divider"></div>
    <div class="cover-meta">
        <table>
            <tr>
                <td>Đơn vị áp dụng:</td>
                <td><strong>BA DUY - TINH HOA ẨM THỰC VIỆT</strong></td>
            </tr>
            <tr>
                <td>Phiên bản:</td>
                <td><strong>v2.5 Portable (Đa Camera & NetSDK)</strong></td>
            </tr>
            <tr>
                <td>Mục đích:</td>
                <td>Chống thất thoát hàng hóa, đối soát khiếu nại sàn TMĐT</td>
            </tr>
            <tr>
                <td>Phạm vi áp dụng:</td>
                <td>Bàn đóng gói hàng, Quản lý kho, Bộ phận CSKH</td>
            </tr>
        </table>
    </div>
</div>

<!-- ═══════════════════════════════════════════
     TRANG 2: MỤC LỤC & TỔNG QUAN HỆ THỐNG
     ═══════════════════════════════════════════ -->
<div class="page">
    <div class="page-header">
        <span>PackStation Manual</span>
        <strong>Ba Duy - Tinh Hoa Ẩm Thực Việt</strong>
    </div>

    <h1 class="chapter-title" style="margin-bottom: 10px;">MỤC LỤC TÀI LIỆU</h1>
    <div style="margin-bottom: 16px;">
        <div class="toc-item"><span class="toc-title">Chương 1: Giới Thiệu & Mô Hình Vận Hành</span><span class="toc-page">Trang 2</span></div>
        <div class="toc-item"><span class="toc-title">Chương 2: Cài Đặt Camera & Nhận Diện Đa Góc (1, 2, 3, 4+ Cam)</span><span class="toc-page">Trang 3</span></div>
        <div class="toc-item"><span class="toc-title">Chương 3: Quy Trình Đóng Gói Hàng Ngày (Workflow Chuẩn)</span><span class="toc-page">Trang 4</span></div>
        <div class="toc-item"><span class="toc-title">Chương 4: Tra Cứu Đơn & Xem Lại Video Đối Soát</span><span class="toc-page">Trang 5</span></div>
        <div class="toc-item"><span class="toc-title">Chương 5: Báo Cáo Năng Suất & Xuất File Excel</span><span class="toc-page">Trang 6</span></div>
        <div class="toc-item"><span class="toc-title">Chương 6: Mẹo Chạy Mượt Trên Laptop & Bảng Mã Lệnh Quét Nhanh</span><span class="toc-page">Trang 7</span></div>
    </div>

    <h1 class="chapter-title">CHƯƠNG 1: GIỚI THIỆU & MÔ HÌNH VẬN HÀNH</h1>
    
    <h2 class="section-title">1.1. Mục đích sử dụng</h2>
    <p><strong>PackStation</strong> là phần mềm chuyên dụng hỗ trợ xưởng sản xuất, tổng kho và nhà bán hàng thương mại điện tử (Shopee, TikTok Shop, Lazada, bưu cục vận chuyển) tự động hóa quy trình ghi hình đóng gói từng đơn hàng:</p>
    
    <div class="card">
        <ul style="padding-left: 18px; line-height: 1.6;">
            <li><strong>Chống thất thoát & Khiếu nại sai:</strong> Mỗi kiện hàng đều có video bằng chứng đóng gói rõ nét, quay cận cảnh sản phẩm, quà tặng, mã đơn và quy cách dán băng dính.</li>
            <li><strong>Tự động hóa 100%:</strong> Nhân viên chỉ cần quét mã vận đơn bằng súng bắn mã vạch, phần mềm tự kích hoạt quay tất cả camera và tự lưu khi xong việc.</li>
            <li><strong>Quản trị năng suất:</strong> Tự động đếm sản lượng kiện đóng trong ca/ngày, đo thời gian đóng trung bình để đánh giá KPI nhân viên.</li>
            <li><strong>Phiên bản Portable tiện lợi:</strong> Toàn bộ ứng dụng đặt gọn tại <code>C:\\PackStation</code>, không cần cài đặt phức tạp, sao chép sang máy khác chạy được ngay.</li>
        </ul>
    </div>

    <h2 class="section-title">1.2. Mô hình kết nối thiết bị</h2>
    <table class="data-table">
        <thead>
            <tr>
                <th style="width: 25%;">Thành phần</th>
                <th style="width: 40%;">Khuyến nghị phần cứng</th>
                <th style="width: 35%;">Chức năng</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><strong>Máy tính (PC/Laptop)</strong></td>
                <td>Windows 10/11 64-bit, RAM từ 8GB, ổ cứng SSD.</td>
                <td>Chạy PackStation, lưu trữ database và video đơn hàng.</td>
            </tr>
            <tr>
                <td><strong>Súng quét mã vạch</strong></td>
                <td>Súng bắn mã vạch 1D/2D cổng USB (Honeywell, Zebra, Netum...).</td>
                <td>Nhân viên cầm bắn tít vào tem đơn để ra lệnh bắt đầu quay.</td>
            </tr>
            <tr>
                <td><strong>Camera giám sát</strong></td>
                <td>Camera IP mạng LAN/Wi-Fi: Imou, Dahua, Ezviz, Yoosee...</td>
                <td>Quay cận cảnh thao tác xếp hàng và góc rộng bàn gói.</td>
            </tr>
        </tbody>
    </table>

    <div class="alert alert-tip">
        <strong>💡 Lưu ý quan trọng:</strong> Máy tính và các Camera IP phải được kết nối chung vào cùng một mạng nội bộ (cùng cắm dây mạng hoặc bắt cùng một bộ phát Wi-Fi) thì mới có thể kết nối hình ảnh.
    </div>

    <div class="page-footer">
        <span>PackStation v2.5 - Hướng Dẫn Sử Dụng</span>
        <span>Trang 2</span>
    </div>
</div>

<!-- ═══════════════════════════════════════════
     TRANG 3: CÀI ĐẶT CAMERA
     ═══════════════════════════════════════════ -->
<div class="page">
    <div class="page-header">
        <span>PackStation Manual</span>
        <strong>Chương 2: Cài Đặt Camera</strong>
    </div>

    <h1 class="chapter-title">CHƯƠNG 2: HƯỚNG DẪN CÀI ĐẶT CAMERA</h1>
    <p>Phần mềm hỗ trợ linh hoạt <strong>1, 2, 3, 4 hoặc nhiều camera cùng lúc</strong>. Để cài đặt camera, từ thanh điều hướng bên trái, bấm vào biểu tượng <strong>⚙️ Cài đặt</strong>.</p>

    <h2 class="section-title">2.1. Bốn cách thêm Camera vào hệ thống</h2>

    <div class="step-container">
        <div class="step-item">
            <div class="step-num">1</div>
            <div class="step-body">
                <div class="step-title">📱 Cách 1: Quét mã QR dưới đáy Camera (Khuyên dùng khi lắp mới)</div>
                <p>Bấm nút <strong>"📱 Quét QR Camera"</strong> → Dùng webcam máy tính soi vào tem QR dưới đáy camera Imou/Dahua. Phần mềm sẽ tự động đọc ra mã <strong>Serial (SN)</strong> và <strong>Safety Code (SC)</strong>.</p>
                <div class="alert alert-info" style="margin-bottom: 4px; padding: 6px 10px;">
                    Tại mục <strong>"Gán vào:"</strong>, bác chọn camera đích (VD: <em>Cam 1</em>, <em>Cam 2</em>, hoặc <em>➕ Thêm camera mới</em>). Nếu camera của bác là dòng 2 mắt thì tích chọn <strong>[x] Camera 2 mắt</strong> để tự gán cả 2 ống kính!
                </div>
            </div>
        </div>

        <div class="step-item">
            <div class="step-num">2</div>
            <div class="step-body">
                <div class="step-title">🔍 Cách 2: Tự động dò Camera trên mạng LAN</div>
                <p>Bấm nút <strong>"🔍 Dò Camera"</strong> → Bấm <strong>"Bắt đầu dò"</strong>. Phần mềm sẽ quét dải IP nội bộ và liệt kê tất cả các camera đang online. Nhập mật khẩu camera, chọn mục <em>Gán vào</em> và bấm <strong>"Chọn"</strong>.</p>
            </div>
        </div>

        <div class="step-item">
            <div class="step-num">3</div>
            <div class="step-body">
                <div class="step-title">⚡ Cách 3: Kích hoạt trực tiếp Imou / Dahua qua cổng 37777 (NetSDK)</div>
                <p>Bấm nút <strong>"⚡ Kích hoạt Imou (37777)"</strong> → Nhập địa chỉ IP và Mật khẩu của camera. Phần mềm sẽ tự động bật giao thức H.264 tối ưu, bỏ qua bước cấu hình ONVIF phức tạp.</p>
            </div>
        </div>

        <div class="step-item">
            <div class="step-num">4</div>
            <div class="step-body">
                <div class="step-title">✏️ Cách 4: Nhập đường dẫn RTSP thủ công & Nút Đổi Mật Khẩu</div>
                <p>Dán trực tiếp đường dẫn RTSP vào ô nhập theo cú pháp: <code>rtsp://admin:MậtKhẩu@192.168.1.108:554/cam/realmonitor?channel=1&subtype=0</code></p>
                <div style="background: rgba(37, 99, 235, 0.1); border-left: 3px solid #2563eb; padding: 6px 12px; margin-top: 6px; border-radius: 4px; font-size: 8.5pt;">
                    <strong>🔑 Nút "Đổi mật khẩu" tiện lợi:</strong> Cạnh mỗi thanh URL camera có sẵn nút màu xanh <strong>"🔑 Đổi mật khẩu"</strong>. Người dùng chỉ cần bấm vào, nhập mã an toàn (Safety Code) dưới đáy camera và bấm <em>Cập nhật</em>. Phần mềm sẽ tự động chèn đúng mật khẩu vào chuỗi RTSP mà không lo gõ sai cú pháp!
                </div>
            </div>
        </div>
    </div>

    <h2 class="section-title">2.2. Thêm / Xóa Camera & Bố cục hiển thị</h2>
    <table class="data-table">
        <thead>
            <tr>
                <th style="width: 25%;">Số lượng Camera</th>
                <th style="width: 35%;">Bố cục trực tiếp</th>
                <th style="width: 40%;">Ứng dụng thực tế</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><strong>1 Camera</strong></td>
                <td>Toàn màn hình lớn</td>
                <td>Quay cận cảnh thao tác xếp hàng vào thùng/hộp.</td>
            </tr>
            <tr>
                <td><strong>2 Camera</strong></td>
                <td>Chia đôi màn hình (50% - 50%)</td>
                <td>Cam 1: Góc cận bàn gói / Cam 2: Góc rộng toàn thân nhân viên.</td>
            </tr>
            <tr>
                <td><strong>3 Camera</strong></td>
                <td>Chia 3 cột ngang đều nhau</td>
                <td>Cam 1 cận cảnh / Cam 2 góc rộng / Cam 3 quay kệ lấy hàng.</td>
            </tr>
            <tr>
                <td><strong>4+ Camera</strong></td>
                <td>Dạng lưới ma trận (2x2, 2x3...)</td>
                <td>Giám sát bàn đóng gói đa góc hoặc nhiều góc xưởng cùng lúc.</td>
            </tr>
        </tbody>
    </table>

    <div class="alert alert-tip">
        <strong>💡 Thao tác thêm/xóa:</strong> Trong Cài đặt, bấm <strong>➕ Thêm Camera</strong> để mở rộng thêm Cam 4, Cam 5... hoặc bấm biểu tượng <strong>🗑️ Xóa</strong> màu đỏ để gỡ bớt camera. Sau khi thay đổi, luôn bấm <strong>💾 Lưu</strong>.
    </div>

    <div class="page-footer">
        <span>PackStation v2.5 - Hướng Dẫn Sử Dụng</span>
        <span>Trang 3</span>
    </div>
</div>

<!-- ═══════════════════════════════════════════
     TRANG 4: QUY TRÌNH ĐÓNG GÓI HÀNG NGÀY
     ═══════════════════════════════════════════ -->
<div class="page">
    <div class="page-header">
        <span>PackStation Manual</span>
        <strong>Chương 3: Quy Trình Đóng Gói</strong>
    </div>

    <h1 class="chapter-title">CHƯƠNG 3: QUY TRÌNH ĐÓNG GÓI HÀNG NGÀY</h1>
    <p>Quy trình thao tác chuẩn dành cho nhân viên đóng gói tại bàn. Đơn giản, tự động và chỉ mất 1 giây để thao tác:</p>

    <div class="step-container">
        <div class="step-item">
            <div class="step-num">1</div>
            <div class="step-body">
                <div class="step-title">Khởi động phần mềm PackStation</div>
                <p>Bấm đúp vào biểu tượng <strong>PackStation</strong> trên Desktop (hình chú tôm Ba Duy). Màn hình chính mở ra với các góc camera giám sát trực tiếp hiển thị <span class="badge badge-live">● TRỰC TIẾP</span>.</p>
            </div>
        </div>

        <div class="step-item">
            <div class="step-num">2</div>
            <div class="step-body">
                <div class="step-title">Quét mã vận đơn để bắt đầu gói hàng</div>
                <p>Nhân viên cầm súng quét bắn vào mã vạch in trên phiếu gửi hàng (hoặc tem Shopee/TikTok):</p>
                <div class="card" style="background: #fff7ed; border-color: #fdba74; margin-bottom: 6px;">
                    <p>🔔 <strong>Âm thanh:</strong> Kêu <em>"Bíp"</em> xác nhận tiếp nhận đơn thành công.</p>
                    <p>🔴 <strong>Đèn báo:</strong> Chuyển sang màu đỏ nhấp nháy <span class="badge badge-rec">🔴 Đang ghi hình...</span></p>
                    <p>📹 <strong>Hệ thống:</strong> Bắt đầu ghi đồng thời tất cả các mắt camera vào thư mục video của ngày.</p>
                </div>
            </div>
        </div>

        <div class="step-item">
            <div class="step-num">3</div>
            <div class="step-body">
                <div class="step-title">Thao tác đóng kiện hàng</div>
                <p>Nhân viên tiến hành kiểm hàng, xếp hàng vào hộp và dán băng dính niêm phong ngay dưới tầm quan sát của camera. <em>Mẹo: Nên đưa lướt gói hàng hoặc tem vận đơn qua trước camera 1 giây để ghi nhận rõ nét bằng chứng.</em></p>
            </div>
        </div>

        <div class="step-item">
            <div class="step-num">4</div>
            <div class="step-body">
                <div class="step-title">Kết thúc đóng gói đơn hàng</div>
                <p>Để dừng quay và lưu video, nhân viên chọn 1 trong 2 cách:</p>
                <ul style="padding-left: 18px; line-height: 1.5;">
                    <li><strong>Cách 1 (Nhanh nhất):</strong> Quét ngay <strong>mã đơn hàng tiếp theo</strong>. Hệ thống sẽ tự đóng đơn cũ và bắt đầu quay đơn mới.</li>
                    <li><strong>Cách 2 (Hết ca / Nghỉ):</strong> Quét mã lệnh <strong><code>KETTHUC</code></strong>. Video sẽ dừng quay, chuông reo báo hoàn tất và đèn chuyển về <span class="badge badge-idle">⚪ Chờ quét mã</span>.</li>
                </ul>
            </div>
        </div>
    </div>

    <h2 class="section-title">3.2. Xử lý các tình huống đặc biệt</h2>
    <table class="data-table">
        <thead>
            <tr>
                <th style="width: 25%;">Tình huống</th>
                <th style="width: 40%;">Biểu hiện của phần mềm</th>
                <th style="width: 35%;">Cách nhân viên xử lý</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><strong>Mã đơn bị quét trùng</strong></td>
                <td>Phần mềm kêu âm thanh cảnh báo lỗi và hiện thông báo: <code>⚠️ Đơn trùng: [MãĐơn]</code></td>
                <td>Kiểm tra xem đơn hàng này đã được người khác đóng gói trước đó chưa để tránh gửi thừa hàng cho khách.</td>
            </tr>
            <tr>
                <td><strong>Tem bị rách / Súng không đọc được</strong></td>
                <td>Súng quét không kêu bíp, ô nhập không có ký tự.</td>
                <td>Nhân viên gõ trực tiếp mã đơn bằng bàn phím vào ô <em>"Nhập hoặc quét mã vận đơn..."</em> rồi nhấn phím <kbd>Enter</kbd>.</td>
            </tr>
            <tr>
                <td><strong>Muốn hủy bỏ đơn đang đóng</strong></td>
                <td>Đang quay video nhưng kiện hàng bị lỗi, cần hủy bỏ.</td>
                <td>Quét mã lệnh <strong><code>HUYDON</code></strong>. Hệ thống sẽ lưu trạng thái đơn là Đã hủy và ngừng quay.</td>
            </tr>
        </tbody>
    </table>

    <div class="page-footer">
        <span>PackStation v2.5 - Hướng Dẫn Sử Dụng</span>
        <span>Trang 4</span>
    </div>
</div>

<!-- ═══════════════════════════════════════════
     TRANG 5: TRA CỨU ĐƠN & ĐỐI SOÁT VIDEO
     ═══════════════════════════════════════════ -->
<div class="page">
    <div class="page-header">
        <span>PackStation Manual</span>
        <strong>Chương 4: Tra Cứu & Đối Soát</strong>
    </div>

    <h1 class="chapter-title">CHƯƠNG 4: TRA CỨU ĐƠN & XEM LẠI VIDEO ĐỐI SOÁT</h1>
    <p>Khi khách hàng khiếu nại báo thiếu hàng, tráo hàng hoặc sàn TMĐT yêu cầu cung cấp video bằng chứng, nhân viên chỉ mất <strong>5 giây</strong> để tìm và trích xuất video.</p>

    <h2 class="section-title">4.1. Cách tra cứu nhanh đơn hàng</h2>
    <div class="card">
        <p><strong>Bước 1:</strong> Tại thanh menu bên trái, bấm vào <strong>🔍 Tra cứu</strong> (hoặc <strong>📋 Đơn hàng</strong>).</p>
        <p><strong>Bước 2:</strong> Nhập mã vận đơn (hoặc mã đơn Shopee/TikTok) vào ô tìm kiếm và bấm <strong>🔍 Tìm</strong>.</p>
        <p><strong>Bước 3:</strong> Kết quả hiển thị đầy đủ thông tin: <em>Thời gian bắt đầu, thời gian kết thúc, tổng số giây đóng hàng, người phụ trách và trạng thái</em>.</p>
        <p><strong>Bước 4:</strong> Bấm nút <strong>▶ Phát</strong> (hoặc <strong>Tải/Mở</strong>) bên cạnh đơn hàng để xem lại video trực tiếp trên máy tính.</p>
    </div>

    <h2 class="section-title">4.2. Cấu trúc thư mục lưu trữ Video trên ổ cứng</h2>
    <p>Tất cả video được tổ chức khoa học tự động theo từng ngày và từng mã đơn hàng, không sợ bị nhầm lẫn:</p>
    
    <div class="card" style="font-family: Consolas, monospace; font-size: 8.5pt; background: #0f172a; color: #38bdf8;">
        📁 C:/PackStation/Videos/<br>
        &nbsp;&nbsp;&nbsp;&nbsp;└── 📁 2026-09-26/<br>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;├── 🎬 SPX_VN12345678_Cam1.mp4 &nbsp;&nbsp;&nbsp;&nbsp;&lt;-- Video góc quay cận cảnh<br>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;├── 🎬 SPX_VN12345678_Cam2.mp4 &nbsp;&nbsp;&nbsp;&nbsp;&lt;-- Video góc quay toàn cảnh rộng<br>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;├── 🎬 JNT_VN98765432_Cam1.mp4<br>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└── 🎬 JNT_VN98765432_Cam2.mp4
    </div>

    <h2 class="section-title">4.3. Cơ chế tự động dọn dẹp ổ cứng (Retention Policy)</h2>
    <div class="alert alert-tip">
        <strong>🛡️ Không lo đầy ổ cứng:</strong> Phần mềm tích hợp tính năng tự động xóa các video cũ đã quay quá <strong>30 ngày</strong> (hoặc số ngày bác cài đặt trong Cài đặt). Video quá hạn sẽ được giải phóng dung lượng ngầm mà không làm ảnh hưởng đến hoạt động bán hàng.
    </div>

    <h2 class="section-title">4.4. Đổi thư mục lưu video sang ổ đĩa khác</h2>
    <p>Nếu ổ đĩa C của máy tính bị đầy, bác có thể vào <strong>⚙️ Cài đặt</strong> → mục <em>"Thư mục video"</em> → bấm nút <strong>📁</strong> để chuyển nơi lưu sang ổ <code>D:\\Videos_DongGoi</code> hoặc ổ cứng gắn ngoài một cách dễ dàng.</p>

    <div class="page-footer">
        <span>PackStation v2.5 - Hướng Dẫn Sử Dụng</span>
        <span>Trang 5</span>
    </div>
</div>

<!-- ═══════════════════════════════════════════
     TRANG 6: BÁO CÁO THỐNG KÊ & XUẤT EXCEL
     ═══════════════════════════════════════════ -->
<div class="page">
    <div class="page-header">
        <span>PackStation Manual</span>
        <strong>Chương 5: Báo Cáo & Xuất Excel</strong>
    </div>

    <h1 class="chapter-title">CHƯƠNG 5: BÁO CÁO THỐNG KÊ & XUẤT EXCEL</h1>
    <p>Phần mềm tự động thống kê toàn bộ hoạt động sản xuất để chủ cửa hàng và quản lý kho nắm bắt sản lượng tức thì mà không cần đếm tay.</p>

    <h2 class="section-title">5.1. Xem các biểu đồ và chỉ số hiệu suất</h2>
    <p>Bấm vào mục <strong>📊 Thống kê</strong> trên menu điều hướng bên trái:</p>

    <div class="card">
        <ul style="padding-left: 18px; line-height: 1.7;">
            <li><strong>Tổng đơn trong ngày:</strong> Đếm số lượng kiện hàng đã hoàn tất đóng gói trong ngày hôm nay.</li>
            <li><strong>Thời gian đóng gói trung bình (TB/đơn):</strong> Tính toán số giây trung bình nhân viên đóng 1 đơn (VD: 45 giây/đơn). Giúp phát hiện đơn nào đóng quá chậm hoặc nhân viên nào có tay nghề nhanh.</li>
            <li><strong>Biểu đồ theo giờ:</strong> Cho biết khung giờ nào trong ngày xưởng đóng gói cao điểm nhất (VD: từ 9h-11h sáng và 14h-16h chiều).</li>
            <li><strong>Thống kê theo tuần / tháng:</strong> Theo dõi tiến độ hoàn thành chỉ tiêu đơn hàng trong tháng.</li>
        </ul>
    </div>

    <h2 class="section-title">5.2. Hướng dẫn xuất dữ liệu ra file Excel</h2>
    <div class="step-container">
        <div class="step-item">
            <div class="step-num">1</div>
            <div class="step-body">
                <p>Tại trang <strong>📊 Thống kê</strong>, bấm vào nút màu xanh <strong>⬇️ Xuất Excel</strong>.</p>
            </div>
        </div>
        <div class="step-item">
            <div class="step-num">2</div>
            <div class="step-body">
                <p>Hộp thoại lưu file sẽ hiện ra, bác chọn thư mục cần lưu trên máy tính (VD: Màn hình Desktop).</p>
            </div>
        </div>
        <div class="step-item">
            <div class="step-num">3</div>
            <div class="step-body">
                <p>File Excel xuất ra có đầy đủ các cột: <em>Mã đơn, Bàn đóng gói, Giờ bắt đầu, Giờ kết thúc, Thời gian đóng gói (giây), Đường dẫn video lưu trữ, Trạng thái</em>.</p>
            </div>
        </div>
    </div>

    <div class="alert alert-info">
        <strong>💡 Ứng dụng file Excel:</strong> File Excel có thể gửi cho bộ phận kế toán để tính lương sản phẩm cho nhân viên đóng hàng, hoặc nộp cho quản lý kho để đối soát với danh sách bàn giao của bưu tá vận chuyển.
    </div>

    <div class="page-footer">
        <span>PackStation v2.5 - Hướng Dẫn Sử Dụng</span>
        <span>Trang 6</span>
    </div>
</div>

<!-- ═══════════════════════════════════════════
     TRANG 7: MẸO LAPTOP & BẢNG MÃ QUÉT NHANH
     ═══════════════════════════════════════════ -->
<div class="page">
    <div class="page-header">
        <span>PackStation Manual</span>
        <strong>Chương 6: Mẹo Laptop & Mã Quét</strong>
    </div>

    <h1 class="chapter-title">CHƯƠNG 6: MẸO CHẠY MƯỢT TRÊN LAPTOP & MÃ QUÉT NHANH</h1>

    <h2 class="section-title">6.1. Ba bí quyết giúp Laptop chạy cực êm và mượt cả ngày</h2>
    <div class="card">
        <ol style="padding-left: 18px; line-height: 1.7;">
            <li><strong>Luôn cắm sạc khi sử dụng:</strong> Khi cắm sạc, Windows sẽ cho phép chip CPU chạy ở hiệu suất tối đa, video mượt mà không bị bóp xung nhịp.</li>
            <li><strong>Chỉnh chế độ Pin sang Best Performance:</strong> Bấm vào biểu tượng Pin ở góc phải dưới thanh Taskbar Windows → kéo thanh trượt sang <em>"Best performance" (Hiệu suất tốt nhất)</em>.</li>
            <li><strong>Dùng luồng phụ (Sub-stream) nếu mạng yếu:</strong> Nếu laptop đời cũ hoặc bắt Wi-Fi yếu, khi cài đặt RTSP bác có thể đổi đuôi <code>subtype=0</code> thành <code>subtype=1</code> để hình ảnh truyền tải nhẹ nhàng hơn mà video vẫn đủ nét để đối soát.</li>
        </ol>
    </div>

    <h2 class="section-title">6.2. Bảng mã vạch thao tác nhanh (In ra dán tại bàn gói hàng)</h2>
    <p>Bác có thể in trang này ra giấy A4, cắt các khung mã vạch bên dưới và dùng băng dính trong dán ngay cạnh mép bàn đóng gói. Khi nhân viên làm việc xong chỉ cần lia súng quét qua là xong:</p>

    <div style="display: flex; gap: 15px; justify-content: space-between; margin-top: 10px;">
        <div class="barcode-card" style="flex: 1;">
            <div class="barcode-title">LỆNH KẾT THÚC ĐƠN</div>
            <div class="barcode-box">KETTHUC</div>
            <div class="barcode-desc">Quét mã này khi đóng xong đơn cuối ca để dừng quay và lưu video hoàn tất.</div>
        </div>

        <div class="barcode-card" style="flex: 1;">
            <div class="barcode-title">LỆNH HỦY BỎ ĐƠN</div>
            <div class="barcode-box">HUYDON</div>
            <div class="barcode-desc">Quét mã này khi kiện hàng bị lỗi, gói hàng bị hỏng cần hủy bỏ không gửi đi.</div>
        </div>
    </div>

    <div class="alert alert-warning" style="margin-top: 14px;">
        <strong>📞 Hỗ trợ kỹ thuật:</strong> Nếu cần thêm bất kỳ tính năng nào hoặc cần mở rộng thêm camera, bác có thể liên hệ trực tiếp để được nâng cấp và hỗ trợ kỹ thuật nhanh nhất!
    </div>

    <div class="page-footer">
        <span>PackStation v2.5 - Hướng Dẫn Sử Dụng</span>
        <span>Trang 7</span>
    </div>
</div>

</body>
</html>
"""

    html_file = os.path.join(base_dir, "Huong_Dan_Su_Dung_PackStation.html")
    pdf_file = os.path.join(base_dir, "Huong_Dan_Su_Dung_PackStation.pdf")
    portable_pdf = r"C:\PackStation\Huong_Dan_Su_Dung_PackStation.pdf"

    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print("📄 Đã tạo file HTML:", html_file)

    browser_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]

    browser_exe = None
    for b in browser_candidates:
        if os.path.exists(b):
            browser_exe = b
            break

    if not browser_exe:
        print("❌ Không tìm thấy trình duyệt Edge/Chrome để in PDF")
        return

    print(f"🖨️ Đang in PDF bằng {browser_exe}...")
    cmd = [
        browser_exe,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_file}",
        html_file
    ]

    res = subprocess.run(cmd, capture_output=True)
    if os.path.exists(pdf_file) and os.path.getsize(pdf_file) > 0:
        print(f"✅ Tạo PDF thành công: {pdf_file} ({os.path.getsize(pdf_file):,} bytes)")
        try:
            shutil.copy2(pdf_file, portable_pdf)
            print(f"✅ Đã sao chép sang: {portable_pdf}")
        except Exception as e:
            print(f"⚠️ Sao chép sang C:\\PackStation: {e}")
    else:
        print("❌ Lỗi in PDF:", res.stderr.decode("utf-8", errors="replace"))

if __name__ == "__main__":
    main()
