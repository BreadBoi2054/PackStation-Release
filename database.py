"""SQLite database for orders, scan logs, videos."""
import sqlite3
import os
import threading
from datetime import datetime, date, timedelta


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = None
        self._lock = threading.Lock()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-8000")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def initialize(self):
        c = self.conn.cursor()
        c.executescript("""
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
            CREATE INDEX IF NOT EXISTS idx_orders_status_scanner ON orders(status, scanner_id);
            CREATE INDEX IF NOT EXISTS idx_orders_start_scanner ON orders(start_time, scanner_id);

            CREATE TABLE IF NOT EXISTS scan_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                scanner_id INTEGER DEFAULT 1,
                scan_time TEXT DEFAULT (datetime('now','localtime')),
                code_type TEXT DEFAULT 'barcode',
                order_id INTEGER REFERENCES orders(id)
            );
            CREATE INDEX IF NOT EXISTS idx_scans_time ON scan_logs(scan_time);

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
            CREATE INDEX IF NOT EXISTS idx_videos_order_ch ON videos(order_id, camera_channel);

            CREATE TABLE IF NOT EXISTS video_checks (
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                camera_channel INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'recording',
                message TEXT NOT NULL DEFAULT '',
                dropped_frames INTEGER NOT NULL DEFAULT 0,
                checked_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (order_id, camera_channel)
            );
        """)
        self.conn.commit()

    def recover_crashed_orders(self) -> int:
        """Close any orders left 'packing' from a previous crash. Returns count recovered."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, order_sn FROM orders WHERE status='packing'"
            ).fetchall()
            if not rows:
                return 0
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for row in rows:
                self.conn.execute(
                    "UPDATE orders SET end_time=?, status='crashed' WHERE id=?",
                    (now, row["id"])
                )
                self.conn.execute(
                    """UPDATE video_checks SET status='corrupt',
                       message='App đóng đột ngột, cần kiểm tra video', checked_at=?
                       WHERE order_id=? AND status='recording'""",
                    (now, row["id"]),
                )
            self.conn.commit()
            return len(rows)

    def close(self):
        if self._conn:
            with self._lock:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass
            self._conn.close()
            self._conn = None

    # ── Orders ──
    def start_order(self, order_sn: str, scanner_id: int = 1, operator: str = "") -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            c = self.conn.execute(
                "INSERT INTO orders (order_sn, scanner_id, start_time, operator) VALUES (?, ?, ?, ?)",
                (order_sn, scanner_id, now, operator),
            )
            self.conn.commit()
            return c.lastrowid

    def end_order(self, order_id: int, status: str = "completed"):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self.conn.execute(
                "UPDATE orders SET end_time=?, status=? WHERE id=?",
                (now, status, order_id),
            )
            self.conn.commit()

    def delete_order(self, order_id: int, delete_video_files: bool = True) -> list:
        """Delete an order and its associated video/scan records from DB.
        Optionally deletes physical video files from disk.
        Returns list of deleted video file paths.
        """
        deleted_files = []
        with self._lock:
            # 1. Fetch associated video paths before deleting records
            videos = self.conn.execute("SELECT filepath FROM videos WHERE order_id=?", (order_id,)).fetchall()
            for v in videos:
                fp = v["filepath"] if isinstance(v, sqlite3.Row) else v[0]
                if fp:
                    deleted_files.append(fp)

            # 2. Delete database records
            self.conn.execute("DELETE FROM videos WHERE order_id=?", (order_id,))
            self.conn.execute("DELETE FROM video_checks WHERE order_id=?", (order_id,))
            self.conn.execute("DELETE FROM scan_logs WHERE order_id=?", (order_id,))
            self.conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
            self.conn.commit()

        # 3. Clean up physical video files if requested
        if delete_video_files:
            for fp in deleted_files:
                if fp and os.path.exists(fp):
                    try:
                        os.remove(fp)
                    except Exception:
                        pass

        return deleted_files

    def get_active_order(self, scanner_id: int = 1):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM orders WHERE scanner_id=? AND status='packing' ORDER BY id DESC LIMIT 1",
                (scanner_id,),
            ).fetchone()

    def get_active_orders(self):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM orders WHERE status='packing' ORDER BY start_time DESC"
            ).fetchall()

    def search_orders(self, keyword: str, limit: int = 100):
        kw = f"%{keyword}%"
        with self._lock:
            return self.conn.execute(
                """SELECT o.*,
                          COALESCE(MAX(v.created_at), o.end_time) AS video_export_time,
                          COUNT(v.id) AS video_count,
                          GROUP_CONCAT(v.filename, ', ') AS video_filenames,
                          GROUP_CONCAT(v.filepath, ';') AS video_filepaths,
                          SUM(v.file_size) AS total_video_size,
                          MAX(v.duration_seconds) AS max_duration
                   FROM orders o
                   LEFT JOIN videos v ON v.order_id = o.id
                   WHERE o.order_sn LIKE ? OR o.start_time LIKE ? OR o.operator LIKE ? OR o.status LIKE ?
                   GROUP BY o.id
                   ORDER BY o.start_time DESC LIMIT ?""",
                (kw, kw, kw, kw, limit),
            ).fetchall()

    def get_orders_by_date(self, date_str: str):
        with self._lock:
            return self.conn.execute(
                """SELECT o.*,
                          COALESCE(MAX(v.created_at), o.end_time) AS video_export_time,
                          COUNT(v.id) AS video_count,
                          GROUP_CONCAT(v.filename, ', ') AS video_filenames,
                          GROUP_CONCAT(v.filepath, ';') AS video_filepaths,
                          SUM(v.file_size) AS total_video_size,
                          MAX(v.duration_seconds) AS max_duration
                   FROM orders o
                   LEFT JOIN videos v ON v.order_id = o.id
                   WHERE o.start_time >= ? AND o.start_time <= ?
                   GROUP BY o.id
                   ORDER BY o.start_time DESC""",
                (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
            ).fetchall()

    def get_today_orders(self):
        today = date.today().isoformat()
        return self.get_orders_by_date(today)

    def get_all_orders(self, limit: int = 200):
        with self._lock:
            return self.conn.execute(
                """SELECT o.*,
                          COALESCE(MAX(v.created_at), o.end_time) AS video_export_time,
                          COUNT(v.id) AS video_count,
                          GROUP_CONCAT(v.filename, ', ') AS video_filenames,
                          GROUP_CONCAT(v.filepath, ';') AS video_filepaths,
                          SUM(v.file_size) AS total_video_size,
                          MAX(v.duration_seconds) AS max_duration
                   FROM orders o
                   LEFT JOIN videos v ON v.order_id = o.id
                   GROUP BY o.id
                   ORDER BY o.start_time DESC LIMIT ?""",
                (limit,),
            ).fetchall()

    def get_recorded_dates(self) -> list:
        """Returns list of distinct dates that have recorded orders, sorted newest first."""
        with self._lock:
            rows = self.conn.execute(
                """SELECT substr(start_time, 1, 10) as order_date, COUNT(*) as cnt
                   FROM orders
                   GROUP BY order_date
                   ORDER BY order_date DESC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def get_videos_by_order_sn(self, order_sn: str):
        with self._lock:
            return self.conn.execute(
                """SELECT v.* FROM videos v
                   JOIN orders o ON v.order_id = o.id
                   WHERE o.order_sn = ?
                   ORDER BY v.id DESC""", (order_sn,)
            ).fetchall()

    def get_today_count(self, scanner_id: int = None) -> int:
        today = date.today().isoformat()
        t_start, t_end = f"{today} 00:00:00", f"{today} 23:59:59"
        with self._lock:
            if scanner_id:
                row = self.conn.execute(
                    "SELECT COUNT(*) as cnt FROM orders WHERE start_time >= ? AND start_time <= ? AND scanner_id=?",
                    (t_start, t_end, scanner_id),
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT COUNT(*) as cnt FROM orders WHERE start_time >= ? AND start_time <= ?",
                    (t_start, t_end),
                ).fetchone()
            return row["cnt"] if row else 0

    def check_duplicate(self, order_sn: str, cooldown_seconds: int = 60) -> bool:
        cutoff = (datetime.now() - timedelta(seconds=cooldown_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            row = self.conn.execute(
                "SELECT id FROM orders WHERE order_sn=? AND start_time > ?",
                (order_sn, cutoff),
            ).fetchone()
            return row is not None

    def get_orders_in_range(self, start_date: str, end_date: str):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM orders WHERE start_time >= ? AND start_time <= ? ORDER BY start_time DESC",
                (f"{start_date} 00:00:00", f"{end_date} 23:59:59"),
            ).fetchall()

    def get_stats_by_date(self, date_str: str):
        with self._lock:
            rows = self.conn.execute(
                """SELECT scanner_id, COUNT(*) as count,
                          AVG(CASE WHEN end_time IS NOT NULL
                              THEN (julianday(end_time) - julianday(start_time)) * 86400
                              ELSE NULL END) as avg_seconds
                   FROM orders WHERE start_time >= ? AND start_time <= ?
                   GROUP BY scanner_id""",
                (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
            ).fetchall()
            return rows

    def get_hourly_stats(self, date_str: str):
        with self._lock:
            return self.conn.execute(
                """SELECT CAST(strftime('%H', start_time) AS INTEGER) as hour, COUNT(*) as count
                   FROM orders WHERE start_time >= ? AND start_time <= ?
                   GROUP BY hour ORDER BY hour""",
                (f"{date_str} 00:00:00", f"{date_str} 23:59:59"),
            ).fetchall()

    # ── Scan Logs ──
    def add_scan_log(self, code: str, scanner_id: int = 1, code_type: str = "barcode", order_id: int = None):
        with self._lock:
            self.conn.execute(
                "INSERT INTO scan_logs (code, scanner_id, code_type, order_id) VALUES (?, ?, ?, ?)",
                (code, scanner_id, code_type, order_id),
            )
            self.conn.commit()

    def get_recent_scans(self, limit: int = 50):
        today = date.today().isoformat()
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM scan_logs WHERE scan_time >= ? AND scan_time <= ? ORDER BY scan_time DESC LIMIT ?",
                (f"{today} 00:00:00", f"{today} 23:59:59", limit),
            ).fetchall()

    # ── Videos ──
    def add_video(self, order_id: int, filename: str, filepath: str, channel: int = 1) -> int:
        with self._lock:
            c = self.conn.execute(
                "INSERT INTO videos (order_id, filename, filepath, camera_channel) VALUES (?, ?, ?, ?)",
                (order_id, filename, filepath, channel),
            )
            self.conn.commit()
            return c.lastrowid

    def update_video_info(self, video_id: int, file_size: int, duration: float):
        with self._lock:
            self.conn.execute(
                "UPDATE videos SET file_size=?, duration_seconds=? WHERE id=?",
                (file_size, duration, video_id),
            )
            self.conn.commit()

    def get_order_videos(self, order_id: int):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM videos WHERE order_id=?", (order_id,)
            ).fetchall()

    def set_video_check(self, order_id: int, channel: int, status: str, message: str = "", dropped_frames: int = 0):
        with self._lock:
            self.conn.execute(
                """INSERT INTO video_checks (order_id, camera_channel, status, message, dropped_frames)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(order_id, camera_channel) DO UPDATE SET
                     status=excluded.status, message=excluded.message,
                     dropped_frames=excluded.dropped_frames,
                     checked_at=datetime('now','localtime')""",
                (order_id, channel, status, message, dropped_frames),
            )
            self.conn.commit()

    def get_video_checks(self, order_id: int):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM video_checks WHERE order_id=? ORDER BY camera_channel", (order_id,)
            ).fetchall()

    def remove_videos_in_folder(self, folder_path: str) -> int:
        """Remove video records whose files were inside folder_path."""
        norm = os.path.normpath(folder_path)
        with self._lock:
            c = self.conn.execute(
                "DELETE FROM videos WHERE filepath LIKE ? OR filepath LIKE ?",
                (f"{norm}%", f"{folder_path}%"),
            )
            self.conn.commit()
            return c.rowcount

    def cleanup_missing_videos(self) -> int:
        """Scan videos table and delete records pointing to non-existent files on disk."""
        with self._lock:
            rows = self.conn.execute("SELECT id, filepath FROM videos").fetchall()
            removed = 0
            for r in rows:
                fp = r["filepath"]
                if fp and not os.path.exists(fp):
                    self.conn.execute("DELETE FROM videos WHERE id=?", (r["id"],))
                    removed += 1
            if removed > 0:
                self.conn.commit()
            return removed

    def sync_videos_from_folder(self, video_dir: str) -> dict:
        """Scan physical video directory on disk, recover missing orders and videos into database.
        Groups orders by (order_sn, date) so that orders with the same code on different days are kept distinct.
        Returns:
            {"orders_created": int, "videos_linked": int, "total_files": int}
        """
        import re
        if not video_dir or not os.path.exists(video_dir):
            return {"orders_created": 0, "videos_linked": 0, "total_files": 0}

        orders_created = 0
        videos_linked = 0
        total_files = 0

        # Pattern handles: ORDER_Cam1.mp4, ORDER_Cam2.mp4, ORDER_Cam1_Lan2.mp4, or ORDER.mp4
        pattern = re.compile(r"^(.*?)(?:_Cam(\d+))?(?:_Lan\d+)?\.mp4$", re.IGNORECASE)

        with self._lock:
            # Pre-cache existing (order_sn, date) -> id mapping so that orders on different dates are not merged
            existing_orders = {}
            for row in self.conn.execute("SELECT id, order_sn, substr(start_time, 1, 10) as o_date FROM orders").fetchall():
                sn = row["order_sn"].strip()
                odate = row["o_date"].strip() if row["o_date"] else ""
                if sn and odate:
                    existing_orders[(sn, odate)] = row["id"]
                elif sn and sn not in existing_orders:
                    existing_orders[sn] = row["id"]

            # Pre-cache existing video filepaths for 0ms duplicate check
            existing_videos = set()
            for row in self.conn.execute("SELECT filepath FROM videos").fetchall():
                if row["filepath"]:
                    existing_videos.add(os.path.normpath(row["filepath"]).lower())

            # Walk through video directory
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

                    # Determine file date and size
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
                        c = self.conn.execute(
                            "INSERT INTO orders (order_sn, scanner_id, start_time, end_time, status, operator) VALUES (?, ?, ?, ?, 'completed', 'sync')",
                            (order_sn, 1, start_time, file_time),
                        )
                        order_id = c.lastrowid
                        existing_orders[(order_sn, order_date)] = order_id
                        orders_created += 1

                    # 2. Ensure video exists in videos table
                    if norm_fp not in existing_videos:
                        self.conn.execute(
                            "INSERT INTO videos (order_id, filename, filepath, camera_channel, file_size, duration_seconds, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
                            (order_id, fname, fp, channel, file_size, file_time),
                        )
                        existing_videos.add(norm_fp)
                        videos_linked += 1

            self.conn.commit()

        return {
            "orders_created": orders_created,
            "videos_linked": videos_linked,
            "total_files": total_files,
        }
