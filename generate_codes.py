"""Generate printable QR code sheets for PackStation function codes."""
import os
import sys

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def generate_function_code_sheets(output_dir: str):
    """Generate printable A5 sheets with QR codes for function codes."""
    if not HAS_QRCODE:
        print("Cần cài thư viện: pip install qrcode[pil]")
        return
    if not HAS_PIL:
        print("Cần cài thư viện: pip install Pillow")
        return

    os.makedirs(output_dir, exist_ok=True)

    codes = [
        {
            "code": "KETTHUC",
            "title": "MÃ KẾT THÚC TỰ ĐỘNG",
            "subtitle": "Quét mã này để kết thúc đơn hàng hiện tại",
            "color": (34, 197, 94),  # green
            "filename": "ma_ket_thuc.png",
        },
        {
            "code": "HUYDON",
            "title": "MÃ HỦY ĐƠN",
            "subtitle": "Quét mã này để hủy đơn hàng hiện tại",
            "color": (239, 68, 68),  # red
            "filename": "ma_huy_don.png",
        },
        {
            "code": "SETCA_Ca1",
            "title": "SET CA LÀM VIỆC - CA 1",
            "subtitle": "Quét để đặt ca làm việc: Ca 1",
            "color": (59, 130, 246),  # blue
            "filename": "ma_set_ca1.png",
        },
        {
            "code": "SETCA_Ca2",
            "title": "SET CA LÀM VIỆC - CA 2",
            "subtitle": "Quét để đặt ca làm việc: Ca 2",
            "color": (168, 85, 247),  # purple
            "filename": "ma_set_ca2.png",
        },
    ]

    for item in codes:
        img = create_code_sheet(
            code=item["code"],
            title=item["title"],
            subtitle=item["subtitle"],
            accent_color=item["color"],
        )
        filepath = os.path.join(output_dir, item["filename"])
        img.save(filepath, quality=95)
        print(f"✅ Saved: {filepath}")

    # Create combined sheet (all codes on one page)
    combined = create_combined_sheet(codes)
    combined_path = os.path.join(output_dir, "tat_ca_ma_chuc_nang.png")
    combined.save(combined_path, quality=95)
    print(f"✅ Saved combined: {combined_path}")
    print(f"\n📁 Mở thư mục: {output_dir}")
    print("In ra giấy A4/A5 rồi dán ở bàn đóng gói!")


def create_code_sheet(code: str, title: str, subtitle: str,
                      accent_color=(34, 197, 94), width=800, height=1000):
    """Create a single printable sheet with QR code."""
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Try to load good fonts, fallback to default
    try:
        font_title = ImageFont.truetype("arial.ttf", 42)
        font_sub = ImageFont.truetype("arial.ttf", 22)
        font_code = ImageFont.truetype("consola.ttf", 28)
        font_brand = ImageFont.truetype("arial.ttf", 18)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = font_title
        font_code = font_title
        font_brand = font_title

    # Header bar with accent color
    draw.rectangle([(0, 0), (width, 8)], fill=accent_color)

    # Title
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_w = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_w) // 2, 40), title, fill=(30, 30, 30), font=font_title)

    # Generate QR code
    qr = qrcode.QRCode(version=3, box_size=12, border=2, error_correction=qrcode.constants.ERROR_CORRECT_H)
    qr.add_data(code)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")

    # Resize and paste QR
    qr_size = 400
    qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
    qr_x = (width - qr_size) // 2
    qr_y = 120
    img.paste(qr_img, (qr_x, qr_y))

    # QR border
    draw.rectangle(
        [(qr_x - 4, qr_y - 4), (qr_x + qr_size + 4, qr_y + qr_size + 4)],
        outline=accent_color, width=3
    )

    # Code text below QR
    code_text = f"Nội dung mã: {code}"
    code_bbox = draw.textbbox((0, 0), code_text, font=font_code)
    code_w = code_bbox[2] - code_bbox[0]
    draw.text(((width - code_w) // 2, qr_y + qr_size + 30), code_text, fill=(100, 100, 100), font=font_code)

    # Subtitle
    sub_bbox = draw.textbbox((0, 0), subtitle, font=font_sub)
    sub_w = sub_bbox[2] - sub_bbox[0]
    draw.text(((width - sub_w) // 2, qr_y + qr_size + 80), subtitle, fill=(120, 120, 120), font=font_sub)

    # Divider line
    y_div = qr_y + qr_size + 130
    draw.line([(80, y_div), (width - 80, y_div)], fill=(200, 200, 200), width=1)

    # Instructions
    instructions = [
        "📋 Hướng dẫn sử dụng:",
        "1. Đặt tờ giấy này ở bàn đóng gói",
        "2. Khi cần kết thúc đơn, đưa mã này vào máy quét",
        "3. Hệ thống sẽ tự động kết thúc đơn + dừng ghi hình",
    ]
    y_instr = y_div + 20
    for line in instructions:
        draw.text((80, y_instr), line, fill=(80, 80, 80), font=font_brand)
        y_instr += 32

    # Brand footer
    brand = "PackStation - Quản lý đóng gói"
    brand_bbox = draw.textbbox((0, 0), brand, font=font_brand)
    brand_w = brand_bbox[2] - brand_bbox[0]
    draw.text(((width - brand_w) // 2, height - 50), brand, fill=(180, 180, 180), font=font_brand)

    # Bottom bar
    draw.rectangle([(0, height - 8), (width, height)], fill=accent_color)

    return img


def create_combined_sheet(codes, page_width=2480, page_height=3508):
    """Create A4 page with all codes (2x2 grid)."""
    img = Image.new("RGB", (page_width, page_height), (255, 255, 255))

    card_w = page_width // 2 - 40
    card_h = page_height // 2 - 40

    for i, item in enumerate(codes[:4]):
        card = create_code_sheet(
            code=item["code"], title=item["title"],
            subtitle=item["subtitle"], accent_color=item["color"],
            width=card_w, height=card_h,
        )
        col = i % 2
        row = i // 2
        x = 20 + col * (card_w + 40)
        y = 20 + row * (card_h + 40)
        img.paste(card, (x, y))

    return img


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    output = os.path.join(base, "printed_codes")
    generate_function_code_sheets(output)
