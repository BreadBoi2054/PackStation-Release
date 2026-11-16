"""Video recorder - records crash-safe H.264 MP4 evidence per order asynchronously."""
import collections
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, date, timedelta
from typing import Callable, Optional

import cv2
import numpy as np

from core.logger import get_logger

log = get_logger()


def _resolve_ffmpeg_exe() -> Optional[str]:
    try:
        from core.zalo_export import _ffmpeg_path
        path = _ffmpeg_path()
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return None


class _FFmpegPipeWriter:
    """Writes BGR frames into fragmented H.264 (.part.mp4), then remuxes to +faststart .mp4."""

    def __init__(self, ffmpeg_exe: str, part_path: str, final_path: str, fps: int, resolution: tuple[int, int]):
        self.ffmpeg_exe = ffmpeg_exe
        self.part_path = part_path
        self.final_path = final_path
        self.fps = max(1, int(fps))
        self.resolution = resolution
        self.error = ""
        self._closed = False
        self._proc = None

        w, h = int(resolution[0]), int(resolution[1])
        cmd = [
            ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{w}x{h}", "-r", str(self.fps), "-i", "-",
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-crf", "26", "-pix_fmt", "yuv420p", "-g", str(max(10, self.fps * 2)),
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
            "-flush_packets", "1",
            part_path,
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            self.error = str(exc)
            self._proc = None

    def isOpened(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and not self._closed

    def write(self, frame: np.ndarray) -> bool:
        if not self.isOpened() or frame is None:
            return False
        try:
            if not frame.flags["C_CONTIGUOUS"]:
                frame = np.ascontiguousarray(frame)
            self._proc.stdin.write(frame.tobytes())
            return True
        except Exception as exc:
            self.error = str(exc)
            return False

    def finalize(self, has_frames: bool):
        if self._closed:
            return
        self._closed = True
        if self._proc is None:
            return

        stderr_msg = ""
        try:
            if self._proc.stdin:
                try:
                    self._proc.stdin.flush()
                except Exception:
                    pass
                try:
                    self._proc.stdin.close()
                except Exception:
                    pass
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except Exception:
                    self._proc.kill()
            if self._proc.stderr:
                try:
                    raw_err = self._proc.stderr.read()
                    if raw_err:
                        stderr_msg = raw_err.decode("utf-8", errors="replace").strip()
                except Exception:
                    pass
                try:
                    self._proc.stderr.close()
                except Exception:
                    pass
        except Exception as exc:
            self.error = self.error or str(exc)

        if stderr_msg and self._proc.returncode not in (0, None):
            self.error = self.error or stderr_msg[-400:]

        if not has_frames:
            if os.path.exists(self.part_path):
                try:
                    os.remove(self.part_path)
                except Exception:
                    pass
            return

        if not os.path.isfile(self.part_path) or os.path.getsize(self.part_path) == 0:
            self.error = self.error or "Không tạo được dữ liệu H.264."
            return

        tmp_remux = self.final_path + ".remux.tmp.mp4"
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            res = subprocess.run(
                [
                    self.ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-i", self.part_path, "-c", "copy", "-movflags", "+faststart", tmp_remux,
                ],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=creation_flags,
            )
            if res.returncode == 0 and os.path.isfile(tmp_remux) and os.path.getsize(tmp_remux) > 0:
                os.replace(tmp_remux, self.final_path)
                try:
                    os.remove(self.part_path)
                except Exception:
                    pass
                return
        except Exception as exc:
            log.warning(f"[Video] Remux faststart fallback ({self.final_path}): {exc}")
        finally:
            if os.path.exists(tmp_remux):
                try:
                    os.remove(tmp_remux)
                except Exception:
                    pass

        # Fragmented MP4 itself is valid & playable even if remux fails
        try:
            os.replace(self.part_path, self.final_path)
        except Exception as exc:
            self.error = self.error or str(exc)

    def release(self):
        self.finalize(has_frames=True)


class VideoRecorder:
    """Records H.264 video from camera frames asynchronously with pre-roll and crash safety."""

    def __init__(
        self,
        video_dir: str,
        fps: int = 10,
        resolution: tuple = (1280, 720),
        db=None,
        pre_roll_seconds: int = 3,
    ):
        self.video_dir = video_dir
        self.fps = max(1, int(fps))
        self.resolution = resolution
        self.db = db
        self.pre_roll_seconds = max(0, int(pre_roll_seconds))

        self._writers: dict[int, object] = {}
        self._recording: dict[str, bool] = {}
        self._active_sessions: dict[str, int] = {}
        self._latest_health_sid: dict[str, int] = {}
        self._session_health: dict[int, dict] = {}
        self._pending_starts: dict[int, dict] = {}
        self._current_filepaths: dict[str, str] = {}
        self._frame_state: dict[int, dict] = {}
        self._lock = threading.Lock()

        self._next_session_id = 0
        self._pre_roll_buffers: dict[int, collections.deque] = {}
        self._pre_roll_last_ts: dict[int, float] = {}
        self._pre_roll_lock = threading.Lock()
        self._cleanup_running = False
        self._ffmpeg_exe = _resolve_ffmpeg_exe()

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
        """Returns free disk space in GB for video storage partition, or -1.0 if inaccessible."""
        try:
            target = self.video_dir if os.path.exists(self.video_dir) else os.path.dirname(os.path.abspath(self.video_dir))
            _, _, free = shutil.disk_usage(target)
            return round(free / (1024 ** 3), 1)
        except Exception as exc:
            log.warning(f"[Video] Could not inspect disk space: {exc}")
            return -1.0

    @staticmethod
    def clean_order_sn(order_sn: str) -> str:
        safe = "".join(c for c in order_sn if c not in r'\/:*?"<>|' and ord(c) >= 32).strip()
        return safe or "UNKNOWN_ORDER"

    def feed_live_frame(self, channel: int, frame):
        """Buffer recent live frames in a ring deque so each order includes pre-roll footage."""
        if self.pre_roll_seconds <= 0 or frame is None or not self._running:
            return
        now_mono = time.monotonic()
        min_interval = (1.0 / self.fps) * 0.85
        with self._pre_roll_lock:
            last_ts = self._pre_roll_last_ts.get(channel, 0.0)
            if (now_mono - last_ts) < min_interval:
                return
            self._pre_roll_last_ts[channel] = now_mono

        h, w = frame.shape[:2]
        if (w, h) != self.resolution:
            prepared = cv2.resize(frame, self.resolution, interpolation=cv2.INTER_LINEAR)
        else:
            prepared = frame.copy()
        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        max_len = max(1, self.fps * self.pre_roll_seconds)

        with self._pre_roll_lock:
            buf = self._pre_roll_buffers.get(channel)
            if buf is None or buf.maxlen != max_len:
                buf = collections.deque(maxlen=max_len)
                self._pre_roll_buffers[channel] = buf
            buf.append((prepared, now_mono, ts_str))

    def _pop_pre_roll(self, channel: int) -> list:
        if self.pre_roll_seconds <= 0:
            return []
        with self._pre_roll_lock:
            buf = self._pre_roll_buffers.get(channel)
            if not buf:
                return []
            frames = list(buf)
            buf.clear()
            return frames

    def _trigger_async_cleanup_if_low_disk(self):
        free_gb = self.get_disk_free_gb()
        if 0 <= free_gb < 0.5 and not self._cleanup_running:
            self._cleanup_running = True
            log.warning("[Video] ⚠️ Dung lượng ổ đĩa dưới 500MB! Kích hoạt dọn dẹp video cũ ngầm...")

            def _bg():
                try:
                    self.cleanup_old_videos(retention_days=7)
                finally:
                    self._cleanup_running = False

            threading.Thread(target=_bg, daemon=True, name="LowDiskCleanup").start()

    def start_recording(self, order_sn: str, channel: int = 1) -> str:
        """Start recording asynchronously. Returns target MP4 filepath immediately."""
        if not self._running:
            return ""
        self._trigger_async_cleanup_if_low_disk()

        safe_sn = self.clean_order_sn(order_sn)
        suffix = f"Cam{channel}"
        date_dir = self._get_date_dir()
        base_name = f"{safe_sn}_{suffix}"

        filename = f"{base_name}.mp4"
        count = 1
        while os.path.exists(os.path.join(date_dir, filename)) or os.path.exists(os.path.join(date_dir, f"{filename}.part.mp4")):
            count += 1
            filename = f"{base_name}_Lan{count}.mp4"

        filepath = os.path.join(date_dir, filename)
        key = f"{order_sn}_{channel}"
        pre_frames = self._pop_pre_roll(channel)

        with self._lock:
            if self._recording.get(key):
                return self._current_filepaths[key]
            self._next_session_id += 1
            sid = self._next_session_id
            self._recording[key] = True
            self._active_sessions[key] = sid
            self._latest_health_sid[key] = sid
            self._current_filepaths[key] = filepath
            self._pending_starts[sid] = {
                "key": key,
                "order_sn": order_sn,
                "channel": channel,
                "filepath": filepath,
            }
            self._session_health[sid] = {"dropped": 0, "written": 0, "error": "", "filepath": filepath}

        self._frame_queue.put_nowait(("START", sid, key, order_sn, channel, filepath, pre_frames))
        log.info(f"[Video] 🔴 Queued recording: {filepath}")
        return filepath

    def write_frame(self, order_sn: str, frame, channel: int = 1):
        """Enqueue frame for asynchronous writing without blocking caller thread."""
        if not self._running or frame is None:
            return
        key = f"{order_sn}_{channel}"
        with self._lock:
            if not self._recording.get(key, False):
                return
            sid = self._active_sessions.get(key)
        if sid is None:
            return

        if self._frame_slots.acquire(blocking=False):
            self._frame_queue.put_nowait(
                ("FRAME", sid, key, frame, time.monotonic(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
        else:
            with self._lock:
                if sid in self._session_health:
                    self._session_health[sid]["dropped"] += 1

    def get_recording_health(self, order_sn: str, channel: int = 1) -> dict:
        key = f"{order_sn}_{channel}"
        with self._lock:
            sid = self._active_sessions.get(key) or self._latest_health_sid.get(key)
            if sid is not None and sid in self._session_health:
                return dict(self._session_health[sid])
            return {}

    def stop_recording(self, order_sn: str, channel: int = 1, on_complete: Optional[Callable] = None) -> Optional[str]:
        """Stop recording asynchronously. Returns target filepath immediately without blocking UI."""
        key = f"{order_sn}_{channel}"
        with self._lock:
            sid = self._active_sessions.pop(key, None)
            filepath = self._current_filepaths.pop(key, None)
            if not filepath:
                safe_sn = self.clean_order_sn(order_sn)
                filepath = os.path.join(self._get_date_dir(), f"{safe_sn}_Cam{channel}.mp4")

            was_recording = self._recording.get(key, False)
            if not was_recording or sid is None:
                self._recording[key] = False
                return filepath if (filepath and os.path.exists(filepath)) else None
            self._recording[key] = False

        self._frame_queue.put_nowait(("STOP", sid, key, filepath, on_complete, time.monotonic()))
        log.info(f"[Video] ⏹️ Stop requested: {order_sn} ch{channel}")
        return filepath

    def _apply_watermark(self, frame: np.ndarray, order_sn: str, channel: int, timestamp: str) -> np.ndarray:
        h, w = frame.shape[:2]
        if (w, h) != self.resolution:
            out = cv2.resize(frame, self.resolution, interpolation=cv2.INTER_LINEAR)
        else:
            out = frame.copy()

        rw, rh = self.resolution
        safe_sn = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(order_sn or "ORDER"))[:32]
        meta_text = f" | Cam {channel} | {timestamp}"

        font_scale = max(0.36, min(0.56, rh / 1280.0))
        thickness = 2 if rh >= 640 else 1
        (sn_w, text_h), baseline = cv2.getTextSize(safe_sn, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        (meta_w, _), _ = cv2.getTextSize(meta_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)

        pad_x = 10
        bar_h = text_h + baseline + 10
        bar_w = min(rw, pad_x * 2 + sn_w + meta_w + 8)
        y1 = max(0, rh - bar_h - 4)

        region = out[y1:rh, 0:bar_w]
        region[:] = (region.astype(np.uint16) * 40 // 100).astype(np.uint8)

        text_y = rh - baseline - 6
        cv2.putText(out, safe_sn, (pad_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 215, 255), thickness, cv2.LINE_AA)
        cv2.putText(out, meta_text, (pad_x + sn_w, text_y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), 1, cv2.LINE_AA)
        return out

    def _open_writer(self, sid: int, filepath: str):
        if self._ffmpeg_exe:
            part_path = filepath + ".part.mp4"
            writer = _FFmpegPipeWriter(self._ffmpeg_exe, part_path, filepath, self.fps, self.resolution)
            if writer.isOpened():
                return writer
            log.warning(f"[Video] FFmpeg pipe failed to open ({writer.error}), falling back to OpenCV VideoWriter")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        return cv2.VideoWriter(filepath, fourcc, self.fps, self.resolution)

    def _write_timed_frame(self, sid: int, order_sn: str, channel: int, writer, frame, captured_at: float, timestamp: str):
        state = self._frame_state.get(sid)
        target_count = round((captured_at - state["started"]) * self.fps) + 1 if state else 1
        needed = target_count - state["count"] if state else 1
        if needed <= 0:
            return

        stamped = self._apply_watermark(frame, order_sn, channel, timestamp)
        if state is None:
            state = {
                "started": captured_at,
                "last_time": captured_at,
                "count": 0,
                "last_frame": stamped,
                "order_sn": order_sn,
                "channel": channel,
            }
            self._frame_state[sid] = state

        max_gap = self.fps * 2
        if needed > max_gap:
            with self._lock:
                if sid in self._session_health:
                    self._session_health[sid]["error"] = "Camera gián đoạn hơn 2 giây"
            needed = max_gap
            state["started"] = captured_at - (state["count"] + needed - 1) / self.fps

        for _ in range(needed - 1):
            writer.write(state["last_frame"])
        writer.write(stamped)
        state["count"] += needed
        state["last_time"] = captured_at
        state["last_frame"] = stamped
        with self._lock:
            if sid in self._session_health:
                self._session_health[sid]["written"] += needed

    def _write_pre_roll_frames(self, sid: int, order_sn: str, channel: int, writer, pre_frames: list):
        if not pre_frames or not writer or not writer.isOpened():
            return
        for idx, (pre_img, pre_mono, pre_ts) in enumerate(pre_frames):
            stamped = self._apply_watermark(pre_img, order_sn, channel, pre_ts)
            writer.write(stamped)
            if sid not in self._frame_state:
                self._frame_state[sid] = {
                    "started": pre_mono,
                    "last_time": pre_mono,
                    "count": 1,
                    "last_frame": stamped,
                    "order_sn": order_sn,
                    "channel": channel,
                }
            else:
                st = self._frame_state[sid]
                st["count"] += 1
                st["last_time"] = pre_mono
                st["last_frame"] = stamped
        with self._lock:
            if sid in self._session_health:
                self._session_health[sid]["written"] += len(pre_frames)

    def _close_writer(self, sid: int, key: str, filepath: str, callback: Optional[Callable] = None, stopped_at: float = 0):
        with self._lock:
            writer = self._writers.pop(sid, None)
            self._pending_starts.pop(sid, None)
            written_count = self._session_health.get(sid, {}).get("written", 0)

        state = self._frame_state.pop(sid, None)
        if writer:
            try:
                if state and stopped_at > state["last_time"]:
                    due = max(0, round((stopped_at - state["started"]) * self.fps) + 1 - state["count"])
                    remaining = min(self.fps * 2, due)
                    if due > remaining:
                        with self._lock:
                            if sid in self._session_health:
                                self._session_health[sid]["error"] = "Camera gián đoạn hơn 2 giây"
                    for _ in range(remaining):
                        writer.write(state["last_frame"])
                    written_count += remaining
                    with self._lock:
                        if sid in self._session_health:
                            self._session_health[sid]["written"] += remaining
            except Exception as e:
                log.error(f"[Video] Tail flush error {key}: {e}")
                with self._lock:
                    if sid in self._session_health:
                        self._session_health[sid]["error"] = str(e)
            finally:
                try:
                    if isinstance(writer, _FFmpegPipeWriter):
                        writer.finalize(has_frames=(written_count > 0))
                        if writer.error:
                            with self._lock:
                                if sid in self._session_health and not self._session_health[sid]["error"]:
                                    self._session_health[sid]["error"] = writer.error
                    else:
                        writer.release()
                except Exception as exc:
                    log.error(f"[Video] Release error {key}: {exc}")
                    with self._lock:
                        if sid in self._session_health:
                            self._session_health[sid]["error"] = str(exc)

        size = os.path.getsize(filepath) if (filepath and os.path.exists(filepath)) else 0
        if written_count == 0 and isinstance(writer, cv2.VideoWriter):
            if filepath and os.path.exists(filepath) and size == 0:
                try:
                    os.remove(filepath)
                except Exception:
                    pass
                size = 0
                filepath = None
        elif size == 0:
            if filepath and os.path.exists(filepath) and written_count > 0:
                try:
                    os.remove(filepath)
                except Exception:
                    pass
            size = 0
            filepath = None

        if size == 0:
            with self._lock:
                if sid in self._session_health:
                    self._session_health[sid]["error"] = (
                        self._session_health[sid]["error"] or "Không tạo được file video"
                    )

        if callback:
            try:
                callback(filepath, size)
            except Exception as e:
                log.error(f"[Video] Callback error {key}: {e}")

        with self._lock:
            self._session_health.pop(sid, None)
            if self._latest_health_sid.get(key) == sid:
                self._latest_health_sid.pop(key, None)
            if key not in self._active_sessions:
                self._recording.pop(key, None)

    def _writer_worker(self):
        while True:
            try:
                item = self._frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            cmd = None
            sid = None
            key = ""
            try:
                if item is None:
                    break
                cmd = item[0]
                sid = item[1]
                key = item[2]

                if cmd == "START":
                    _, _, _, order_sn, channel, filepath, pre_frames = item
                    if sid not in self._writers:
                        writer = self._open_writer(sid, filepath)
                        if writer.isOpened():
                            with self._lock:
                                self._writers[sid] = writer
                                self._pending_starts.pop(sid, None)
                            self._write_pre_roll_frames(sid, order_sn, channel, writer, pre_frames)
                            log.info(f"[Video] 🔴 Writer opened in background: {filepath}")
                        else:
                            log.error(f"[Video] ❌ Failed to open writer: {filepath}")
                            with self._lock:
                                if sid in self._session_health:
                                    self._session_health[sid]["error"] = "Không mở được bộ ghi video"

                elif cmd == "FRAME":
                    _, _, _, frame, captured_at, timestamp = item
                    with self._lock:
                        writer = self._writers.get(sid)
                        pending = self._pending_starts.get(sid)
                        meta = pending or self._frame_state.get(sid)
                    order_sn = meta["order_sn"] if meta else key.rsplit("_", 1)[0]
                    channel = meta["channel"] if meta else 1

                    if writer is None and pending:
                        writer = self._open_writer(sid, pending["filepath"])
                        if writer.isOpened():
                            with self._lock:
                                self._writers[sid] = writer
                                self._pending_starts.pop(sid, None)
                                if sid in self._session_health:
                                    self._session_health[sid]["error"] = ""
                        else:
                            writer = None

                    if writer and writer.isOpened():
                        self._write_timed_frame(sid, order_sn, channel, writer, frame, captured_at, timestamp)

                elif cmd == "STOP":
                    _, _, _, filepath, callback, stopped_at = item
                    self._close_writer(sid, key, filepath, callback, stopped_at)

            except Exception as e:
                log.error(f"[Video] Worker error: {e}")
                if sid is not None:
                    with self._lock:
                        if sid in self._session_health:
                            self._session_health[sid]["error"] = str(e)
            finally:
                if item is not None and cmd == "FRAME":
                    self._frame_slots.release()
                self._frame_queue.task_done()

    def recover_interrupted_recordings(self) -> int:
        """Finalize any .mp4.part.mp4 recordings left from sudden power loss into playable .mp4 files."""
        if not self.video_dir or not os.path.isdir(self.video_dir):
            return 0
        ffmpeg_exe = self._ffmpeg_exe or _resolve_ffmpeg_exe()
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        recovered = 0

        with self._lock:
            active_parts = {fp + ".part.mp4" for fp in self._current_filepaths.values() if fp}

        for root, _, files in os.walk(self.video_dir):
            for fname in files:
                if not fname.lower().endswith(".mp4.part.mp4"):
                    continue
                part_path = os.path.join(root, fname)
                if part_path in active_parts:
                    continue
                try:
                    size = os.path.getsize(part_path)
                except Exception:
                    continue

                if size <= 1024:
                    try:
                        os.remove(part_path)
                    except Exception:
                        pass
                    continue

                final_path = part_path[:-len(".part.mp4")]
                if os.path.exists(final_path) and os.path.getsize(final_path) > 0:
                    stem, ext = os.path.splitext(final_path)
                    final_path = f"{stem}_Recovered{ext}"

                tmp_out = final_path + ".recover.tmp.mp4"
                remuxed = False
                if ffmpeg_exe:
                    try:
                        res = subprocess.run(
                            [
                                ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                                "-i", part_path, "-c", "copy", "-movflags", "+faststart", tmp_out,
                            ],
                            capture_output=True,
                            text=True,
                            timeout=20,
                            creationflags=creation_flags,
                        )
                        if res.returncode == 0 and os.path.isfile(tmp_out) and os.path.getsize(tmp_out) > 0:
                            os.replace(tmp_out, final_path)
                            try:
                                os.remove(part_path)
                            except Exception:
                                pass
                            remuxed = True
                            recovered += 1
                    except Exception as exc:
                        log.warning(f"[Video] Crash recovery remux error '{part_path}': {exc}")
                    finally:
                        if os.path.exists(tmp_out):
                            try:
                                os.remove(tmp_out)
                            except Exception:
                                pass

                if not remuxed:
                    try:
                        os.replace(part_path, final_path)
                        recovered += 1
                    except Exception as exc:
                        log.error(f"[Video] Failed to rename crashed video '{part_path}': {exc}")

        if recovered > 0:
            log.info(f"[Video] 🛡️ Đã khôi phục {recovered} video quay dở do mất điện thành MP4 chuẩn.")
        return recovered

    def stop_all(self):
        """Stop all active recordings and terminate worker thread cleanly."""
        with self._lock:
            remaining = [
                (key, self._active_sessions.pop(key, None), self._current_filepaths.pop(key, None))
                for key in list(self._active_sessions.keys())
            ]
            for key, _, _ in remaining:
                self._recording[key] = False
            self._current_filepaths.clear()
        for key, sid, filepath in remaining:
            if sid is not None:
                self._frame_queue.put_nowait(("STOP", sid, key, filepath, None, time.monotonic()))
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
            cutoff = date.today() - timedelta(days=safe_days)
            if not os.path.exists(self.video_dir):
                return
            for folder_name in os.listdir(self.video_dir):
                folder_path = os.path.join(self.video_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                try:
                    folder_date = date.fromisoformat(folder_name)
                except ValueError:
                    continue

                if folder_date < cutoff:
                    delete_errors = []

                    def _on_rm_error(func, path, exc_info):
                        err_val = exc_info[1] if isinstance(exc_info, tuple) and len(exc_info) > 1 else exc_info
                        delete_errors.append((path, err_val))
                        log.error(f"[Video] ❌ Lỗi không thể xóa file/thư mục video cũ '{path}': {err_val}")

                    try:
                        shutil.rmtree(folder_path, ignore_errors=False, onerror=_on_rm_error)
                    except Exception as rm_exc:
                        delete_errors.append((folder_path, rm_exc))
                        log.error(f"[Video] ❌ Lỗi không thể xóa thư mục video cũ '{folder_path}': {rm_exc}")

                    if not delete_errors and not os.path.exists(folder_path):
                        log.info(f"[Video] 🗑️ Cleaned old folder: {folder_name} (older than {safe_days} days)")
                        if database:
                            database.remove_videos_in_folder(folder_path)
                    else:
                        log.error(
                            f"[Video] ⚠️ Giữ lại bản ghi SQLite cho các file chưa xóa được trong '{folder_name}' ({len(delete_errors)} lỗi)."
                        )
                        if database:
                            database.remove_videos_in_folder(folder_path)
            if database:
                database.cleanup_missing_videos()
        except Exception as e:
            log.error(f"[Video] Cleanup error: {e}")
