"""Video recorder - records camera feed to file per order asynchronously."""
import cv2
import os
import queue
import threading
import time
from datetime import datetime, date
from typing import Optional, Callable
from core.logger import get_logger

log = get_logger()


class VideoRecorder:
    """Records video from camera frames asynchronously, organized by date/order.
    
    Fully non-blocking:
    - start_recording() queues a START command and returns immediately (0ms UI wait)
    - write_frame() enqueues frame with no-wait dropping if queue is full
    - stop_recording() queues a STOP command and returns immediately (0ms UI wait)
    - All cv2.VideoWriter creation, frame encoding, and release happen in background worker
    """

    def __init__(self, video_dir: str, fps: int = 10, resolution: tuple = (1280, 720), db=None):
        self.video_dir = video_dir
        self.fps = fps
        self.resolution = resolution
        self.db = db
        self._writers: dict[str, cv2.VideoWriter] = {}
        self._recording: dict[str, bool] = {}
        self._pending_starts: dict[str, str] = {}  # key -> filepath
        self._current_filepaths: dict[str, str] = {}  # key -> exact filepath
        self._health: dict[str, dict] = {}
        self._frame_state: dict[str, dict] = {}  # Used only by the writer thread
        self._lock = threading.Lock()

        # Background worker for non-blocking frame encoding and writer management
        # Queue items:
        # ("START", key, filepath)
        # ("FRAME", key, frame)
        # ("STOP", key, filepath, callback)
        # Control commands must never be discarded. Only frames are bounded.
        self._frame_queue: queue.Queue = queue.Queue()
        self._frame_slots = threading.BoundedSemaphore(30)
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._writer_worker, daemon=True, name="VideoRecorderWorker"
        )
        self._worker_thread.start()

    def _get_date_dir(self) -> str:
        today = date.today().isoformat()
        dir_path = os.path.join(self.video_dir, today)
        os.makedirs(dir_path, exist_ok=True)
        return dir_path

    def get_disk_free_gb(self) -> float:
        """Returns free disk space in GB for video storage partition."""
        try:
            import shutil
            target = self.video_dir if os.path.exists(self.video_dir) else os.path.dirname(self.video_dir)
            _, _, free = shutil.disk_usage(target)
            return round(free / (1024 ** 3), 1)
        except Exception:
            return 999.0

    @staticmethod
    def clean_order_sn(order_sn: str) -> str:
        safe = "".join(c for c in order_sn if c not in r'\/:*?"<>|' and ord(c) >= 32).strip()
        return safe or "UNKNOWN_ORDER"

    def start_recording(self, order_sn: str, channel: int = 1) -> str:
        """Start recording asynchronously. Returns filepath immediately without blocking UI."""
        # Safety check: if disk free is under 500MB, trigger emergency cleanup
        if self.get_disk_free_gb() < 0.5:
            log.warning("[Video] ⚠️ Dung lượng ổ đĩa dưới 500MB! Kích hoạt dọn dẹp video cũ...")
            self.cleanup_old_videos(retention_days=7)

        safe_sn = self.clean_order_sn(order_sn)
        suffix = f"Cam{channel}"
        date_dir = self._get_date_dir()
        base_name = f"{safe_sn}_{suffix}"

        # If file already exists today, auto-increment _Lan2, _Lan3...
        filename = f"{base_name}.mp4"
        count = 1
        while os.path.exists(os.path.join(date_dir, filename)):
            count += 1
            filename = f"{base_name}_Lan{count}.mp4"

        filepath = os.path.join(date_dir, filename)
        key = f"{order_sn}_{channel}"

        with self._lock:
            if self._recording.get(key):
                return self._current_filepaths[key]
            self._recording[key] = True
            self._pending_starts[key] = filepath
            self._current_filepaths[key] = filepath
            self._health[key] = {"dropped": 0, "written": 0, "error": "", "filepath": filepath}

        self._frame_queue.put_nowait(("START", key, filepath))

        log.info(f"[Video] 🔴 Queued recording: {filepath}")
        return filepath

    def write_frame(self, order_sn: str, frame, channel: int = 1):
        """Enqueue frame for asynchronous writing without blocking caller thread."""
        key = f"{order_sn}_{channel}"
        with self._lock:
            is_rec = self._recording.get(key, False)
        if not is_rec or frame is None:
            return

        if self._frame_slots.acquire(blocking=False):
            self._frame_queue.put_nowait(("FRAME", key, frame, time.monotonic(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        else:
            with self._lock:
                self._health[key]["dropped"] += 1

    def get_recording_health(self, order_sn: str, channel: int = 1) -> dict:
        with self._lock:
            return dict(self._health.get(f"{order_sn}_{channel}", {}))

    def stop_recording(self, order_sn: str, channel: int = 1, on_complete: Optional[Callable] = None) -> Optional[str]:
        """Stop recording asynchronously. Returns target filepath immediately without blocking UI."""
        key = f"{order_sn}_{channel}"
        with self._lock:
            filepath = self._current_filepaths.pop(key, None)
            if not filepath:
                safe_sn = self.clean_order_sn(order_sn)
                suffix = f"Cam{channel}"
                filename = f"{safe_sn}_{suffix}.mp4"
                filepath = os.path.join(self._get_date_dir(), filename)

            if not self._recording.get(key, False):
                return filepath if (filepath and os.path.exists(filepath)) else None
            self._recording[key] = False

        self._frame_queue.put_nowait(("STOP", key, filepath, on_complete, time.monotonic()))

        log.info(f"[Video] ⏹️ Stop requested: {order_sn} ch{channel}")
        return filepath

    def _close_writer(self, key: str, filepath: str, callback: Optional[Callable] = None, stopped_at: float = 0):
        with self._lock:
            writer = self._writers.pop(key, None)
            self._pending_starts.pop(key, None)
        if writer:
            try:
                state = self._frame_state.get(key)
                if state and stopped_at > state["last_time"]:
                    due = max(0, round((stopped_at - state["started"]) * self.fps) + 1 - state["count"])
                    remaining = min(self.fps * 2, due)
                    if due > remaining:
                        with self._lock:
                            self._health[key]["error"] = "Camera gián đoạn hơn 2 giây"
                    for _ in range(remaining):
                        writer.write(state["last_frame"])
                    with self._lock:
                        self._health[key]["written"] += remaining
            except Exception as e:
                log.error(f"[Video] Release error {key}: {e}")
                with self._lock:
                    self._health[key]["error"] = str(e)
            finally:
                try:
                    writer.release()
                except Exception as exc:
                    log.error(f"[Video] Release error {key}: {exc}")
                    with self._lock:
                        self._health[key]["error"] = str(exc)
        self._frame_state.pop(key, None)

        size = os.path.getsize(filepath) if (filepath and os.path.exists(filepath)) else 0
        if size == 0 and filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
            size = 0
            filepath = None

        if size == 0:
            with self._lock:
                self._health[key]["error"] = self._health[key]["error"] or "Không tạo được file video"

        if callback:
            try:
                callback(filepath, size)
            except Exception as e:
                log.error(f"[Video] Callback error {key}: {e}")
        with self._lock:
            self._health.pop(key, None)
            self._recording.pop(key, None)

    def _write_timed_frame(self, key: str, writer, frame, captured_at: float, timestamp: str):
        """Write at a fixed frame rate using capture time, including a small gap fill."""
        state = self._frame_state.get(key)
        target_count = round((captured_at - state["started"]) * self.fps) + 1 if state else 1
        needed = target_count - state["count"] if state else 1
        if needed <= 0:
            return  # Skip resize and watermark work for frames outside an output slot.
        h, w = frame.shape[:2]
        if (w, h) != self.resolution:
            frame = cv2.resize(frame, self.resolution, interpolation=cv2.INTER_NEAREST)
        else:
            frame = frame.copy()
        cv2.putText(frame, timestamp, (12, self.resolution[1] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2, cv2.LINE_8)
        cv2.putText(frame, timestamp, (12, self.resolution[1] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_8)

        if state is None:
            state = {"started": captured_at, "last_time": captured_at, "count": 0, "last_frame": frame}
            self._frame_state[key] = state
        max_gap = self.fps * 2
        if needed > max_gap:
            with self._lock:
                self._health[key]["error"] = "Camera gián đoạn hơn 2 giây"
            needed = max_gap
            state["started"] = captured_at - (state["count"] + needed - 1) / self.fps
        for _ in range(needed - 1):
            writer.write(state["last_frame"])
        writer.write(frame)
        state["count"] += needed
        state["last_time"] = captured_at
        state["last_frame"] = frame
        with self._lock:
            self._health[key]["written"] += needed

    def _writer_worker(self):
        """Background thread that manages writers and encodes video frames to disk."""
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        while True:
            try:
                item = self._frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if item is None:
                    break
                cmd, key = item[:2]
                if cmd == "START":
                    _, _, filepath = item
                    if key not in self._writers:
                        writer = cv2.VideoWriter(filepath, fourcc, self.fps, self.resolution)
                        if writer.isOpened():
                            with self._lock:
                                self._writers[key] = writer
                                self._pending_starts.pop(key, None)
                            log.info(f"[Video] 🔴 Writer opened in background: {filepath}")
                        else:
                            log.error(f"[Video] ❌ Failed to open writer: {filepath}")
                            with self._lock:
                                self._health[key]["error"] = "Không mở được bộ ghi video"
                elif cmd == "FRAME":
                    _, _, frame, captured_at, timestamp = item
                    with self._lock:
                        writer = self._writers.get(key)
                        pending_path = self._pending_starts.get(key)
                    # START is ordered before FRAME. Retry once if opening failed.
                    if writer is None and pending_path:
                        writer = cv2.VideoWriter(pending_path, fourcc, self.fps, self.resolution)
                        if writer.isOpened():
                            with self._lock:
                                self._writers[key] = writer
                                self._pending_starts.pop(key, None)
                                self._health[key]["error"] = ""
                        else:
                            writer = None
                    if writer and writer.isOpened():
                        self._write_timed_frame(key, writer, frame, captured_at, timestamp)
                elif cmd == "STOP":
                    _, _, filepath, callback, stopped_at = item
                    self._close_writer(key, filepath, callback, stopped_at)
            except Exception as e:
                log.error(f"[Video] Worker error: {e}")
                if item is not None:
                    with self._lock:
                        if key in self._health:
                            self._health[key]["error"] = str(e)
            finally:
                if item is not None and item[0] == "FRAME":
                    self._frame_slots.release()
                self._frame_queue.task_done()

    def stop_all(self):
        """Stop all active recordings and terminate worker thread cleanly."""
        with self._lock:
            remaining = [(key, filepath) for key, filepath in self._current_filepaths.items() if self._recording.get(key)]
            for key, _ in remaining:
                self._recording[key] = False
            self._current_filepaths.clear()
        for key, filepath in remaining:
            self._frame_queue.put_nowait(("STOP", key, filepath, None, time.monotonic()))
        self._running = False
        self._frame_queue.put_nowait(None)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=15)
            if self._worker_thread.is_alive():
                log.error("[Video] Writer did not stop within 15 seconds")

    def is_recording(self, order_sn: str, channel: int = 1) -> bool:
        key = f"{order_sn}_{channel}"
        with self._lock:
            return self._recording.get(key, False)

    def cleanup_old_videos(self, retention_days: int = 30, db=None):
        """Delete video folders older than retention_days (minimum 7 days safety floor) and cleanup DB records."""
        try:
            database = db or getattr(self, "db", None)
            safe_days = max(7, int(retention_days))
            cutoff = date.today() - __import__("datetime").timedelta(days=safe_days)
            if not os.path.exists(self.video_dir):
                return
            for folder_name in os.listdir(self.video_dir):
                folder_path = os.path.join(self.video_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                try:
                    folder_date = date.fromisoformat(folder_name)
                    if folder_date < cutoff:
                        import shutil
                        shutil.rmtree(folder_path, ignore_errors=True)
                        log.info(f"[Video] 🗑️ Cleaned old folder: {folder_name} (older than {safe_days} days)")
                        if database:
                            database.remove_videos_in_folder(folder_path)
                except ValueError:
                    pass
            if database:
                database.cleanup_missing_videos()
        except Exception as e:
            log.error(f"[Video] Cleanup error: {e}")
