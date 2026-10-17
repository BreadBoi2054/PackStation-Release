"""Standalone tool to sync and re-index all videos from Videos/ folder into packstation.db.
100% self-contained with pure Python standard library (sqlite3, os, re, datetime, json).
Zero external dependencies - runs in any environment!
"""
import os
import sys
import sqlite3
import re
import json
from datetime import datetime


def sync_videos_folder(base_dir: str):
    db_path = os.path.join(base_dir, "packstation.db")
    config_path = os.path.join(base_dir, "packstation-config.json")

    video_dir = os.path.join(base_dir, "Videos")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                custom_v = cfg.get("video_dir")
                if custom_v:
                    video_dir = custom_v if os.path.isabs(custom_v) else os.path.join(base_dir, custom_v)
        except Exception:
            pass

    print("==================================================")
    print("🔄 PACKSTATION VIDEO SYNC & RECOVERY TOOL")
    print("==================================================")
    print(f"📁 Thư mục Database: {db_path}")
    print(f"📁 Thư mục Videos:   {video_dir}")

    if not os.path.exists(video_dir):
        print(f"❌ Không tìm thấy thư mục: {video_dir}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # Ensure tables exist
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_sn TEXT NOT NULL,
            scanner_id INTEGER DEFAULT 1,
            start_time TEXT NOT NULL,
            end_time TEXT,
            status TEXT DEFAULT 'packing',
            operator TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_orders_sn ON orders(order_sn);
        CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(start_time);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER REFERENCES orders(id),
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            camera_channel INTEGER DEFAULT 1,
            file_size INTEGER DEFAULT 0,
            duration_seconds REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_videos_order_id ON videos(order_id);
        CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at);
    """)
    conn.commit()

    pattern = re.compile(r"^(.*?)(?:_Cam(\d+))?(?:_Lan\d+)?\.mp4$", re.IGNORECASE)

    existing_orders = {}
    for row in conn.execute("SELECT id, order_sn, substr(start_time, 1, 10) as o_date FROM orders").fetchall():
        sn = row["order_sn"].strip()
        odate = row["o_date"].strip() if row["o_date"] else ""
        if sn and odate:
            existing_orders[(sn, odate)] = row["id"]
        elif sn and sn not in existing_orders:
            existing_orders[sn] = row["id"]

    existing_videos = set()
    for row in conn.execute("SELECT filepath FROM videos").fetchall():
        if row["filepath"]:
            existing_videos.add(os.path.normpath(row["filepath"]).lower())

    orders_created = 0
    videos_linked = 0
    total_files = 0

    print("\n⏳ Đang quét toàn bộ file video .mp4...")

    for root, _, files in os.walk(video_dir):
        for fname in files:
            if not fname.lower().endswith(".mp4"):
                continue

            total_files += 1
            fp = os.path.join(root, fname)
            norm_fp = os.path.normpath(fp).lower()

            m = pattern.match(fname)
            if not m:
                order_sn = os.path.splitext(fname)[0].strip()
                channel = 1
            else:
                order_sn = m.group(1).strip()
                ch_str = m.group(2)
                channel = int(ch_str) if ch_str else 1

            if not order_sn:
                continue

            try:
                mtime = os.path.getmtime(fp)
                file_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                file_size = os.path.getsize(fp)
            except Exception:
                file_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                file_size = 0

            folder_name = os.path.basename(root)
            is_date_folder = len(folder_name) == 10 and folder_name.count("-") == 2
            order_date = folder_name if is_date_folder else file_time[:10]

            start_time = file_time
            if is_date_folder and not file_time.startswith(folder_name):
                start_time = f"{folder_name} 12:00:00"

            # 1. Ensure order exists for this specific (order_sn, order_date)
            order_id = existing_orders.get((order_sn, order_date))
            if not order_id:
                c = conn.execute(
                    "INSERT INTO orders (order_sn, scanner_id, start_time, end_time, status, operator) VALUES (?, ?, ?, ?, 'completed', 'sync')",
                    (order_sn, 1, start_time, file_time),
                )
                order_id = c.lastrowid
                existing_orders[(order_sn, order_date)] = order_id
                orders_created += 1

            # 2. Ensure video exists in videos table
            if norm_fp not in existing_videos:
                conn.execute(
                    "INSERT INTO videos (order_id, filename, filepath, camera_channel, file_size, duration_seconds, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
                    (order_id, fname, fp, channel, file_size, file_time),
                )
                existing_videos.add(norm_fp)
                videos_linked += 1

    conn.commit()
    conn.close()

    print("\n==================================================")
    print("✅ HOÀN TẤT ĐỒNG BỘ!")
    print(f"  - Tổng số file video tìm thấy:    {total_files}")
    print(f"  - Số đơn hàng mới được khôi phục: {orders_created}")
    print(f"  - Số video mới được liên kết:     {videos_linked}")
    print("==================================================")
    print("\nBây giờ bạn có thể mở lại PackStation, toàn bộ đơn và video đã hiển thị đầy đủ!")


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    sync_videos_folder(base_dir)


if __name__ == "__main__":
    main()
