"""Main application window for PackStation."""
import customtkinter as ctk
import cv2
import numpy as np
import threading
import time
import os
import sys
import subprocess
from datetime import datetime, date
from PIL import Image, ImageTk
from typing import Optional

from ui.theme import COLORS, FONTS, PADDING, SIZES
from core.camera_manager import CameraManager
from core.barcode_scanner import BarcodeScanner
from core.video_recorder import VideoRecorder
from core.zalo_export import export_for_zalo
from core.order_manager import OrderManager
from core.audio_manager import AudioManager
from core.logger import get_logger

log = get_logger()


class AppWindow(ctk.CTk):
    """Main application window with sidebar navigation."""

    def _find_asset(self, *parts) -> str:
        base = getattr(self, "config", None)
        base_dir = base.base_dir if base else ""
        candidates = [
            os.path.join(base_dir, "assets", *parts),
            os.path.join(base_dir, "_internal", "assets", *parts),
            os.path.join(os.path.dirname(sys.executable), "assets", *parts),
            os.path.join(os.path.dirname(sys.executable), "_internal", "assets", *parts),
            os.path.join(getattr(sys, "_MEIPASS", ""), "assets", *parts),
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c
        return os.path.join(base_dir, "assets", *parts)

    def __init__(self, config, db, i18n):
        super().__init__()
        self.config = config
        self.db = db
        self.i18n = i18n
        self._t = i18n.t

        # Window setup
        self.title(self._t("app.title"))
        self.geometry("1280x800")
        self.minsize(1024, 680)
        self.configure(fg_color=COLORS["bg_primary"])

        # Set icon if exists
        icon_path = self._find_asset("icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # Initialize core systems
        self.camera_mgr = CameraManager()
        self.audio = AudioManager(config.audio_dir, config.get("sound_enabled", True))
        self.recorder = VideoRecorder(config.video_dir, db=db)
        self.order_mgr = OrderManager(db, config, self.recorder, self.audio)
        self.barcode_scanner = BarcodeScanner(
            on_code=self._on_barcode_detected,
            interval_ms=config.get("auto_scan_interval_ms", 1000)
        )

        # Order manager callbacks
        self.order_mgr.on_order_started = self._on_order_started
        self.order_mgr.on_order_finishing = self._on_order_finishing
        self.order_mgr.on_order_ended = self._on_order_ended
        self.order_mgr.on_duplicate = self._on_duplicate
        self.order_mgr.on_log = self._on_log
        self.order_mgr.on_video_checked = self._on_video_checked

        # UI state
        self._current_page = "camera"
        self._page_frames = {}    # Cache created page frames for instant 0ms switching
        self._camera_images = {}  # Keep references to prevent GC
        self._cam_labels = {}     # Dynamic camera display labels
        self._cam_badges = {}     # Dynamic camera status badges
        self._cam_entries = []    # Dynamic camera settings entries
        self._update_timer = None
        self._status_timer = None
        self._log_messages = []
        self._last_rendered_frame_id = {}
        self._last_processed_frame_id = {}
        self._cam_badge_state = {}
        self._last_status_cache = {}
        import queue
        self._ui_queue = queue.Queue()
        self._ui_queue_timer = None
        self._process_ui_queue()

        # Build UI
        self._build_layout()
        self.bind("<F2>", lambda e: self._force_record_duplicate_order())
        self.bind_all("<Key>", self._on_global_key)
        self._init_cameras()

        # Start auto-scan if enabled
        if config.get("auto_scan_enabled") and self.barcode_scanner.available:
            self.barcode_scanner.start()

        # Start UI update loops
        self._start_update_loop()
        self._start_status_loop()

        # Pre-warm settings page during background idle time for 0ms instant click
        self.after(200, self._prewarm_pages)

        # Cleanup old videos on startup
        retention = config.get("video_retention_days", 30)
        threading.Thread(target=lambda: self.recorder.cleanup_old_videos(retention), daemon=True).start()

        # Auto-sync existing videos from disk to recover any orders missing from DB
        threading.Thread(target=self._auto_sync_videos, daemon=True).start()

    def _auto_sync_videos(self):
        try:
            res = self.db.sync_videos_from_folder(self.config.video_dir)
            if res.get("orders_created", 0) > 0 or res.get("videos_linked", 0) > 0:
                log.info(f"[Sync] 🔄 Khôi phục {res['orders_created']} đơn, {res['videos_linked']} video từ thư mục")
                self._safe_dispatch(lambda: self._refresh_orders_list() if hasattr(self, "_refresh_orders_list") and self._current_page == "orders" else None)
        except Exception as e:
            log.error(f"[Sync] Auto-sync error: {e}")

    def _build_layout(self):
        """Build the main layout: sidebar + content area."""
        # Main container
        self._main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._main_frame.pack(fill="both", expand=True)

        # Sidebar
        self._sidebar = ctk.CTkFrame(
            self._main_frame, width=SIZES["sidebar_width"],
            fg_color=COLORS["sidebar_bg"], corner_radius=0
        )
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        # App title & Brand logo in sidebar
        title_frame = ctk.CTkFrame(self._sidebar, fg_color="transparent")
        title_frame.pack(fill="x", padx=PADDING["md"], pady=(PADDING["md"], PADDING["xs"]))
        
        logo_path = self._find_asset("logo.png")
        if os.path.exists(logo_path):
            try:
                resample = getattr(Image, "Resampling", Image).LANCZOS
                pil_logo = Image.open(logo_path).resize((60, 60), resample)
                self._sidebar_logo_img = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(60, 60))
                ctk.CTkLabel(title_frame, image=self._sidebar_logo_img, text="").pack(anchor="w", pady=(0, 4))
            except Exception:
                ctk.CTkLabel(title_frame, text="📦", font=FONTS["icon_large"]).pack(anchor="w")
        else:
            ctk.CTkLabel(title_frame, text="📦", font=FONTS["icon_large"]).pack(anchor="w")

        ctk.CTkLabel(
            title_frame, text="BA DUY",
            font=("Segoe UI", 15, "bold"), text_color="#f59e0b"
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_frame, text="PackStation",
            font=("Segoe UI", 11), text_color=COLORS["text_secondary"]
        ).pack(anchor="w")


        # Nav buttons
        self._nav_buttons = {}
        nav_items = [
            ("camera", self._t("nav.camera")),
            ("orders", self._t("nav.orders")),
            ("stats", self._t("nav.stats")),
            ("settings", self._t("nav.settings")),
        ]
        nav_frame = ctk.CTkFrame(self._sidebar, fg_color="transparent")
        nav_frame.pack(fill="x", padx=PADDING["sm"], pady=PADDING["md"])

        for page_id, label in nav_items:
            btn = ctk.CTkButton(
                nav_frame, text=label, anchor="w",
                font=FONTS["body"], height=40,
                fg_color="transparent", text_color=COLORS["text_secondary"],
                hover_color=COLORS["sidebar_hover"],
                command=lambda p=page_id: self._navigate(p),
            )
            btn.pack(fill="x", pady=2)
            self._nav_buttons[page_id] = btn

        # Station selector at bottom of sidebar
        spacer = ctk.CTkFrame(self._sidebar, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        station_frame = ctk.CTkFrame(self._sidebar, fg_color=COLORS["bg_card"], corner_radius=8)
        station_frame.pack(fill="x", padx=PADDING["sm"], pady=PADDING["md"])
        ctk.CTkLabel(
            station_frame, text=self._t("scan.station", number=1),
            font=FONTS["small_bold"], text_color=COLORS["accent"]
        ).pack(padx=PADDING["sm"], pady=(PADDING["xs"], 0))
        self._station_status = ctk.CTkLabel(
            station_frame, text=self._t("scan.idle"),
            font=FONTS["small"], text_color=COLORS["text_muted"]
        )
        self._station_status.pack(padx=PADDING["sm"], pady=(0, PADDING["xs"]))

        # Content area
        self._content = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        self._content.pack(side="right", fill="both", expand=True)

        # Status bar at bottom
        self._status_bar = ctk.CTkFrame(
            self, height=SIZES["status_bar_height"],
            fg_color=COLORS["sidebar_bg"], corner_radius=0
        )
        self._status_bar.pack(side="bottom", fill="x", before=self._main_frame)
        self._status_bar.pack_propagate(False)

        self._status_label = ctk.CTkLabel(
            self._status_bar, text="",
            font=FONTS["small"], text_color=COLORS["text_muted"]
        )
        self._status_label.pack(side="left", padx=PADDING["md"])

        self._order_count_label = ctk.CTkLabel(
            self._status_bar, text="",
            font=FONTS["small_bold"], text_color=COLORS["accent"]
        )
        self._order_count_label.pack(side="right", padx=PADDING["md"])

        # Navigate to camera page
        self._navigate("camera")

    def _prewarm_pages(self):
        """Pre-warm heavy pages in background idle so clicking them is 100% instant."""
        try:
            if "settings" not in self._page_frames:
                frame = self._build_settings_page()
                frame.pack_forget()
                self._page_frames["settings"] = frame
        except Exception:
            pass

    def _grant_pin_and_navigate(self, page_id: str):
        self._pin_authenticated = True
        self._navigate(page_id)

    def _prompt_pin_dialog(self, title: str, on_success: Callable):
        """Prompt user for manager PIN code before granting access to sensitive feature."""
        if not self.config.is_pin_set():
            on_success()
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("380x240")
        dialog.configure(fg_color=COLORS["bg_primary"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.attributes("-topmost", True)

        ctk.CTkLabel(dialog, text=f"🔒 {title}", font=FONTS["heading"], text_color=COLORS["text_primary"]).pack(padx=PADDING["lg"], pady=(PADDING["lg"], 4))
        ctk.CTkLabel(dialog, text="Vui lòng nhập mã PIN quản lý để tiếp tục:", font=FONTS["small"], text_color=COLORS["text_muted"]).pack(padx=PADDING["lg"], pady=(0, PADDING["md"]))

        pin_entry = ctk.CTkEntry(dialog, font=FONTS["body"], show="*", width=200, fg_color=COLORS["bg_input"], border_color=COLORS["border"])
        pin_entry.pack(pady=PADDING["xs"])
        pin_entry.focus_set()

        err_label = ctk.CTkLabel(dialog, text="", font=FONTS["small"], text_color=COLORS["error"])
        err_label.pack(pady=(2, PADDING["sm"]))

        def _check():
            entered = pin_entry.get().strip()
            if self.config.verify_pin(entered):
                dialog.destroy()
                on_success()
            else:
                err_label.configure(text="❌ Mã PIN không chính xác!")
                pin_entry.delete(0, "end")

        pin_entry.bind("<Return>", lambda e: _check())

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=PADDING["lg"], pady=PADDING["sm"])

        ctk.CTkButton(btn_row, text="Hủy", font=FONTS["body"], fg_color="transparent", border_width=1, border_color=COLORS["border"], text_color=COLORS["text_secondary"], width=80, height=36, command=dialog.destroy).pack(side="left")
        ctk.CTkButton(btn_row, text="Xác nhận", font=FONTS["body_bold"], fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], height=36, command=_check).pack(side="right", fill="x", expand=True, padx=(PADDING["sm"], 0))

    def _navigate(self, page_id: str):
        """Switch to a different page using zero-lag cached frames."""
        if page_id == "settings" and self.config.is_pin_set() and not getattr(self, "_pin_authenticated", False):
            self._prompt_pin_dialog("Xác thực PIN Cài đặt", lambda: self._grant_pin_and_navigate("settings"))
            return

        if self._current_page == page_id and page_id in self._page_frames and self._page_frames[page_id].winfo_exists():
            return

        old_page = self._current_page
        self._current_page = page_id

        # Update nav button styles
        for pid, btn in self._nav_buttons.items():
            if pid == page_id:
                btn.configure(
                    fg_color=COLORS["sidebar_active"],
                    text_color=COLORS["accent"]
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=COLORS["text_secondary"]
                )

        # Hide current active page frame instantly without destroying widgets
        if old_page in self._page_frames and self._page_frames[old_page].winfo_exists():
            self._page_frames[old_page].pack_forget()

        # For pages with dynamic database content (stats), recreate on demand
        if page_id == "stats":
            if page_id in self._page_frames and self._page_frames[page_id].winfo_exists():
                self._page_frames[page_id].destroy()
            self._page_frames.pop(page_id, None)

        # Show or build target page
        if page_id in self._page_frames and self._page_frames[page_id].winfo_exists():
            self._page_frames[page_id].pack(fill="both", expand=True, padx=PADDING["md"], pady=PADDING["md"])
            if page_id == "orders":
                self._refresh_orders_list()
        else:
            pages = {
                "camera": self._build_camera_page,
                "orders": self._build_orders_page,
                "stats": self._build_stats_page,
                "settings": self._build_settings_page,
            }
            builder = pages.get(page_id)
            if builder:
                self._page_frames[page_id] = builder()

        # Page-specific focus or actions
        if page_id == "camera" and hasattr(self, "_scan_entry") and self._scan_entry.winfo_exists():
            self._scan_entry.focus_set()

    # ═══════════════════════════════════════════
    # CAMERA PAGE
    # ═══════════════════════════════════════════
    def _build_camera_page(self):
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.pack(fill="both", expand=True, padx=PADDING["md"], pady=PADDING["md"])

        # Top: Camera feeds - dynamic count
        camera_frame = ctk.CTkFrame(page, fg_color="transparent")
        camera_frame.pack(fill="both", expand=True)

        station = self.config.get_station(1)
        cams = self.config.get_station_cameras(1)
        valid_cams = [c for c in cams if c.strip()]
        count = max(len(valid_cams), 1)

        self._cam_labels.clear()
        self._cam_badges.clear()

        if not valid_cams:
            # 1 placeholder card
            card = ctk.CTkFrame(camera_frame, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
            card.pack(fill="both", expand=True)
            hdr = ctk.CTkFrame(card, fg_color="transparent")
            hdr.pack(fill="x", padx=PADDING["sm"], pady=(PADDING["sm"], 0))
            ctk.CTkLabel(hdr, text="📷 Cam 1", font=FONTS["body_bold"], text_color=COLORS["text_primary"]).pack(side="left")
            badge = ctk.CTkLabel(hdr, text=self._t("camera.live"), font=FONTS["small_bold"], text_color=COLORS["text_muted"])
            badge.pack(side="right")
            lbl = ctk.CTkLabel(card, text="📷 Chưa cấu hình camera\n\nVào ⚙️ Cài đặt → nhập RTSP URL hoặc dò mạng", font=FONTS["body"], text_color=COLORS["text_muted"])
            lbl.pack(fill="both", expand=True, padx=PADDING["sm"], pady=PADDING["sm"])
            self._cam_labels["cam1"] = lbl
            self._cam_badges["cam1"] = badge
        elif count == 1:
            card = ctk.CTkFrame(camera_frame, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
            card.pack(fill="both", expand=True)
            hdr = ctk.CTkFrame(card, fg_color="transparent")
            hdr.pack(fill="x", padx=PADDING["sm"], pady=(PADDING["sm"], 0))
            ctk.CTkLabel(hdr, text="📷 Cam 1", font=FONTS["body_bold"], text_color=COLORS["text_primary"]).pack(side="left")
            badge = ctk.CTkLabel(hdr, text=self._t("camera.live"), font=FONTS["small_bold"], text_color=COLORS["success"])
            badge.pack(side="right")
            lbl = ctk.CTkLabel(card, text=self._t("camera.not_connected"), font=FONTS["body"], text_color=COLORS["text_muted"])
            lbl.pack(fill="both", expand=True, padx=PADDING["sm"], pady=PADDING["sm"])
            self._cam_labels["cam1"] = lbl
            self._cam_badges["cam1"] = badge
        elif count <= 3:
            # Horizontal layout for 2 or 3 cameras
            for i in range(count):
                cam_key = f"cam{i+1}"
                pad_left = 0 if i == 0 else PADDING["xs"]
                pad_right = 0 if i == count - 1 else PADDING["xs"]
                card = ctk.CTkFrame(camera_frame, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
                card.pack(side="left", fill="both", expand=True, padx=(pad_left, pad_right))

                hdr = ctk.CTkFrame(card, fg_color="transparent")
                hdr.pack(fill="x", padx=PADDING["sm"], pady=(PADDING["sm"], 0))
                ctk.CTkLabel(hdr, text=f"📷 Cam {i+1}", font=FONTS["body_bold"], text_color=COLORS["text_primary"]).pack(side="left")
                badge = ctk.CTkLabel(hdr, text=self._t("camera.live"), font=FONTS["small_bold"], text_color=COLORS["success"])
                badge.pack(side="right")

                lbl = ctk.CTkLabel(card, text=self._t("camera.not_connected"), font=FONTS["body"], text_color=COLORS["text_muted"])
                lbl.pack(fill="both", expand=True, padx=PADDING["sm"], pady=PADDING["sm"])
                self._cam_labels[cam_key] = lbl
                self._cam_badges[cam_key] = badge
        else:
            # Grid layout for 4+ cameras
            cols = 2 if count <= 4 else 3
            camera_frame.grid_columnconfigure(list(range(cols)), weight=1)
            rows = (count + cols - 1) // cols
            camera_frame.grid_rowconfigure(list(range(rows)), weight=1)

            for i in range(count):
                cam_key = f"cam{i+1}"
                r = i // cols
                c = i % cols
                card = ctk.CTkFrame(camera_frame, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
                card.grid(row=r, column=c, sticky="nsew", padx=PADDING["xs"], pady=PADDING["xs"])

                hdr = ctk.CTkFrame(card, fg_color="transparent")
                hdr.pack(fill="x", padx=PADDING["sm"], pady=(PADDING["sm"], 0))
                ctk.CTkLabel(hdr, text=f"📷 Cam {i+1}", font=FONTS["body_bold"], text_color=COLORS["text_primary"]).pack(side="left")
                badge = ctk.CTkLabel(hdr, text=self._t("camera.live"), font=FONTS["small_bold"], text_color=COLORS["success"])
                badge.pack(side="right")

                lbl = ctk.CTkLabel(card, text=self._t("camera.not_connected"), font=FONTS["body"], text_color=COLORS["text_muted"])
                lbl.pack(fill="both", expand=True, padx=PADDING["sm"], pady=PADDING["sm"])
                self._cam_labels[cam_key] = lbl
                self._cam_badges[cam_key] = badge

        # Legacy backward-compatibility attributes
        self._cam1_label = self._cam_labels.get("cam1")
        self._cam1_badge = self._cam_badges.get("cam1")
        self._cam2_label = self._cam_labels.get("cam2")
        self._cam2_badge = self._cam_badges.get("cam2")
        self._cam3_label = self._cam_labels.get("cam3")
        self._cam3_badge = self._cam_badges.get("cam3")



        # Bottom: Scan area + history
        bottom_frame = ctk.CTkFrame(page, fg_color="transparent")
        bottom_frame.pack(fill="x", pady=(PADDING["md"], 0))

        # Current scan info
        scan_card = ctk.CTkFrame(bottom_frame, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
        scan_card.pack(fill="x", pady=(0, PADDING["sm"]))

        scan_inner = ctk.CTkFrame(scan_card, fg_color="transparent")
        scan_inner.pack(fill="x", padx=PADDING["lg"], pady=PADDING["md"])

        # Scan input
        input_frame = ctk.CTkFrame(scan_inner, fg_color="transparent")
        input_frame.pack(fill="x")

        self._scan_entry = ctk.CTkEntry(
            input_frame, placeholder_text=self._t("scan.placeholder"),
            font=FONTS["mono_large"], height=48,
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"]
        )
        self._scan_entry.pack(side="left", fill="x", expand=True, padx=(0, PADDING["sm"]))
        self._scan_entry.bind("<Return>", self._on_manual_scan)

        # Recording indicator
        self._record_indicator = ctk.CTkLabel(
            input_frame, text=self._t("scan.idle"),
            font=FONTS["body_bold"], text_color=COLORS["text_muted"]
        )
        self._record_indicator.pack(side="right")

        # Current order display
        self._current_order_label = ctk.CTkLabel(
            scan_inner, text="", font=FONTS["status_code"],
            text_color=COLORS["accent"]
        )
        self._current_order_label.pack(fill="x", pady=(PADDING["sm"], 0))

        # Duplicate order action banner (hidden by default)
        self._last_duplicate_order_sn = None
        self._dup_timer = None
        self._dup_frame = ctk.CTkFrame(scan_inner, fg_color="#451a03", corner_radius=SIZES["border_radius"], border_width=1, border_color="#d97706")

        dup_content = ctk.CTkFrame(self._dup_frame, fg_color="transparent")
        dup_content.pack(fill="x", padx=PADDING["md"], pady=PADDING["sm"])

        self._dup_label = ctk.CTkLabel(
            dup_content, text="⚠️ Đơn trùng:",
            font=FONTS["body_bold"], text_color="#fbbf24"
        )
        self._dup_label.pack(side="left", padx=(0, PADDING["md"]))

        self._dup_btn = ctk.CTkButton(
            dup_content, text="🔄 Quay lại đơn này (F2)",
            font=FONTS["body_bold"], height=36,
            fg_color="#d97706", hover_color="#b45309", text_color="#ffffff",
            command=self._force_record_duplicate_order
        )
        self._dup_btn.pack(side="right")

        # Log area
        log_card = ctk.CTkFrame(bottom_frame, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"], height=120)
        log_card.pack(fill="x")
        log_card.pack_propagate(False)

        log_header = ctk.CTkFrame(log_card, fg_color="transparent")
        log_header.pack(fill="x", padx=PADDING["md"], pady=(PADDING["sm"], 0))
        ctk.CTkLabel(log_header, text=self._t("history.title"), font=FONTS["body_bold"], text_color=COLORS["text_primary"]).pack(side="left")
        self._today_count_label = ctk.CTkLabel(log_header, text="", font=FONTS["small_bold"], text_color=COLORS["accent"])
        self._today_count_label.pack(side="right")

        self._log_text = ctk.CTkTextbox(
            log_card, font=FONTS["mono"], height=80,
            fg_color=COLORS["bg_secondary"], text_color=COLORS["text_secondary"],
            border_width=0, activate_scrollbars=True
        )
        self._log_text.pack(fill="both", expand=True, padx=PADDING["sm"], pady=PADDING["sm"])
        self._log_text.configure(state="disabled")

        # Focus scan entry
        self._scan_entry.focus_set()
        return page

    # ═══════════════════════════════════════════
    # ORDERS PAGE (WITH SEARCH & VIDEO EXPLORER LOCATOR)
    # ═══════════════════════════════════════════
    def _build_orders_page(self):
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.pack(fill="both", expand=True, padx=PADDING["md"], pady=PADDING["md"])

        self._selected_order = None
        self._orders_mode = "today"
        self._selected_row_widget = None

        # 1. Top Header with title, quick filters, count badge
        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x", pady=(0, PADDING["sm"]))

        ctk.CTkLabel(
            header, text="📋 " + self._t("nav.orders"),
            font=FONTS["heading"], text_color=COLORS["text_primary"]
        ).pack(side="left")

        self._orders_count_label = ctk.CTkLabel(
            header, text="", font=FONTS["small_bold"], text_color=COLORS["accent"]
        )
        self._orders_count_label.pack(side="left", padx=PADDING["md"])

        # Filter mode buttons
        filter_btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        filter_btn_frame.pack(side="right")

        self._filter_today_btn = ctk.CTkButton(
            filter_btn_frame, text="📅 Hôm nay", width=95, height=32,
            font=FONTS["small_bold"],
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=lambda: self._set_orders_mode("today")
        )
        self._filter_today_btn.pack(side="left", padx=(0, PADDING["xs"]))

        self._filter_date_var = ctk.StringVar(value="📅 Đơn theo ngày")
        self._filter_date_menu = ctk.CTkOptionMenu(
            filter_btn_frame,
            variable=self._filter_date_var,
            values=["📅 Đơn theo ngày"],
            width=190, height=32,
            font=FONTS["small_bold"],
            dropdown_font=FONTS["small"],
            fg_color=COLORS["bg_card"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["accent"],
            dropdown_fg_color=COLORS["bg_secondary"],
            dropdown_hover_color=COLORS["accent_hover"],
            command=self._on_filter_date_selected
        )
        self._filter_date_menu.pack(side="left")

        # 2. Search Card
        search_card = ctk.CTkFrame(page, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
        search_card.pack(fill="x", pady=(0, PADDING["sm"]))

        inner_search = ctk.CTkFrame(search_card, fg_color="transparent")
        inner_search.pack(fill="x", padx=PADDING["md"], pady=PADDING["sm"])

        self._order_search_entry = ctk.CTkEntry(
            inner_search,
            placeholder_text="🔍 Nhập mã vận đơn (Shopee, Lazada, TikTok...) hoặc ngày (YYYY-MM-DD) để tra nhanh...",
            font=FONTS["body"], height=38, fg_color=COLORS["bg_input"],
            border_color=COLORS["border"], text_color=COLORS["text_primary"]
        )
        self._order_search_entry.pack(side="left", fill="x", expand=True, padx=(0, PADDING["sm"]))
        self._order_search_entry.bind("<Return>", lambda e: self._refresh_orders_list())
        self._order_search_entry.bind("<KeyRelease>", self._on_search_key_release)

        ctk.CTkButton(
            inner_search, text="🔍 Tìm", font=FONTS["body_bold"],
            width=80, height=38, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._refresh_orders_list
        ).pack(side="left", padx=(0, PADDING["xs"]))

        ctk.CTkButton(
            inner_search, text="✕ Đặt lại", font=FONTS["body"],
            width=75, height=38, fg_color="transparent", border_width=1,
            border_color=COLORS["border"], text_color=COLORS["text_secondary"],
            command=self._clear_orders_search
        ).pack(side="left")

        ctk.CTkButton(
            inner_search, text="🔄 Quét khôi phục video", font=FONTS["body_bold"],
            height=38, fg_color="#059669", hover_color="#047857", text_color="#ffffff",
            command=self._manual_sync_videos
        ).pack(side="left", padx=(PADDING["sm"], 0))

        # 3. Selected Order Action Card (Banner)
        self._selected_order_bar = ctk.CTkFrame(
            page, fg_color="#1e293b", corner_radius=SIZES["border_radius"],
            border_width=1, border_color="#334155"
        )
        self._selected_order_bar.pack(fill="x", pady=(0, PADDING["sm"]))

        bar_inner = ctk.CTkFrame(self._selected_order_bar, fg_color="transparent")
        bar_inner.pack(fill="x", padx=PADDING["md"], pady=PADDING["sm"])

        left_info = ctk.CTkFrame(bar_inner, fg_color="transparent")
        left_info.pack(side="left", fill="x", expand=True)

        self._selected_order_title = ctk.CTkLabel(
            left_info,
            text="💡 Bấm vào mã đơn hàng bên dưới để chọn đơn, sau đó bấm nút để mở thẳng vị trí video trong thư mục.",
            font=FONTS["body_bold"], text_color=COLORS["text_primary"], anchor="w"
        )
        self._selected_order_title.pack(anchor="w")

        self._order_video_status = ctk.CTkLabel(
            left_info, text="", font=FONTS["small"], text_color=COLORS["text_secondary"], anchor="w"
        )
        self._order_video_status.pack(anchor="w", pady=(2, 0))

        bar_btns = ctk.CTkFrame(bar_inner, fg_color="transparent")
        bar_btns.pack(side="right", padx=(PADDING["md"], 0))

        self._open_folder_btn = ctk.CTkButton(
            bar_btns, text="📁 Mở video (Folder)",
            font=FONTS["body_bold"], height=38,
            fg_color="#0284c7", hover_color="#0369a1", text_color="#ffffff",
            state="disabled",
            command=lambda: self._open_order_video_in_folder(self._selected_order)
        )
        self._open_folder_btn.pack(side="left", padx=(0, PADDING["xs"]))

        self._zalo_export_btn = ctk.CTkButton(
            bar_btns, text="🎬 Xuất gửi Zalo", font=FONTS["body_bold"], height=38,
            fg_color="#059669", hover_color="#047857", text_color="#ffffff",
            state="disabled", command=self._export_selected_order_for_zalo
        )
        self._zalo_export_btn.pack(side="left", padx=(0, PADDING["xs"]))

        self._delete_order_btn = ctk.CTkButton(
            bar_btns, text="🗑️ Xóa đơn",
            font=FONTS["body_bold"], height=38,
            fg_color="#ef4444", hover_color="#dc2626", text_color="#ffffff",
            state="disabled",
            command=lambda: self._confirm_delete_order(self._selected_order)
        )
        self._delete_order_btn.pack(side="left")

        # 4. Orders List Scrollable Frame
        self._orders_list_frame = ctk.CTkScrollableFrame(page, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
        self._orders_list_frame.pack(fill="both", expand=True)

        # Initial populate
        self._refresh_orders_list()

        return page

    def _refresh_recorded_dates_menu(self):
        """Populate the date filter dropdown with dates having recorded orders."""
        if not hasattr(self, "_filter_date_menu") or not self._filter_date_menu.winfo_exists():
            return
        try:
            date_rows = self.db.get_recorded_dates()
            values = ["📅 Đơn theo ngày"]
            today = date.today().isoformat()
            for r in date_rows:
                d = r.get("order_date", "")
                cnt = r.get("cnt", 0)
                if not d:
                    continue
                if d == today:
                    values.append(f"📅 {d} (Hôm nay: {cnt} đơn)")
                else:
                    values.append(f"📅 {d} ({cnt} đơn)")

            values.append("📋 Tất cả các ngày")
            self._filter_date_menu.configure(values=values)
        except Exception as e:
            log.error(f"[Orders] Error refreshing date menu: {e}")

    def _on_filter_date_selected(self, selected: str):
        if not selected or selected == "📅 Đơn theo ngày":
            return
        if selected == "📋 Tất cả các ngày":
            self._set_orders_mode("all")
            if hasattr(self, "_filter_date_var"):
                self._filter_date_var.set("📋 Tất cả các ngày")
            return

        import re
        match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", selected)
        if match:
            target_date = match.group(1)
            self._set_orders_mode(f"date:{target_date}")
            if hasattr(self, "_filter_date_var"):
                self._filter_date_var.set(f"📅 Ngày {target_date}")

    def _set_orders_mode(self, mode: str):
        self._orders_mode = mode
        if hasattr(self, "_filter_today_btn"):
            if mode == "today":
                self._filter_today_btn.configure(fg_color=COLORS["accent"], font=FONTS["small_bold"])
                if hasattr(self, "_filter_date_menu"):
                    self._filter_date_menu.configure(fg_color=COLORS["bg_card"])
                    if hasattr(self, "_filter_date_var"):
                        self._filter_date_var.set("📅 Đơn theo ngày")
            elif mode.startswith("date:"):
                self._filter_today_btn.configure(fg_color=COLORS["bg_card"], font=FONTS["small"])
                if hasattr(self, "_filter_date_menu"):
                    self._filter_date_menu.configure(fg_color=COLORS["accent"])
            else:
                self._filter_today_btn.configure(fg_color=COLORS["bg_card"], font=FONTS["small"])
                if hasattr(self, "_filter_date_menu"):
                    self._filter_date_menu.configure(fg_color=COLORS["accent"])
        self._refresh_orders_list()

    def _clear_orders_search(self):
        if hasattr(self, "_order_search_entry"):
            self._order_search_entry.delete(0, "end")
        self._refresh_orders_list()

    def _manual_sync_videos(self):
        """Manually scan Videos/ directory on disk and restore all orders/videos into database."""
        if hasattr(self, "_selected_order_title") and self._selected_order_title.winfo_exists():
            self._selected_order_title.configure(
                text="⏳ Đang quét khôi phục toàn bộ video từ thư mục ổ đĩa...",
                text_color=COLORS["warning"]
            )

        def worker():
            res = self.db.sync_videos_from_folder(self.config.video_dir)
            msg = (
                f"✅ Đã quét xong: Khôi phục {res['orders_created']} đơn mới, "
                f"kết nối {res['videos_linked']} video (Tổng {res['total_files']} file .mp4)."
            )
            def done():
                if hasattr(self, "_selected_order_title") and self._selected_order_title.winfo_exists():
                    self._selected_order_title.configure(text=msg, text_color=COLORS["success"])
                self._refresh_orders_list()
            self._safe_dispatch(done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_search_key_release(self, event=None):
        """Live search as user types with 250ms debounce."""
        if hasattr(self, "_search_debounce_timer") and self._search_debounce_timer:
            try:
                self.after_cancel(self._search_debounce_timer)
            except Exception:
                pass
        self._search_debounce_timer = self.after(250, self._refresh_orders_list)

    def _refresh_orders_list(self):
        if not hasattr(self, "_orders_list_frame") or not self._orders_list_frame.winfo_exists():
            return

        self._refresh_recorded_dates_menu()

        keyword = self._order_search_entry.get().strip() if hasattr(self, "_order_search_entry") else ""
        if keyword:
            orders = self.db.search_orders(keyword)
            filter_desc = f"Tìm kiếm: '{keyword}'"
        else:
            mode = getattr(self, "_orders_mode", "today")
            if mode.startswith("date:"):
                target_date = mode.split(":", 1)[1]
                orders = self.db.get_orders_by_date(target_date)
                filter_desc = f"Ngày {target_date}"
            elif mode == "all":
                orders = self.db.get_all_orders(limit=200)
                filter_desc = "Tất cả các ngày"
            else:
                orders = self.db.get_today_orders()
                filter_desc = "Hôm nay"
                if not orders:
                    recent_dates = self.db.get_recorded_dates()
                    if recent_dates:
                        latest_date = recent_dates[0].get("order_date")
                        if latest_date:
                            orders = self.db.get_orders_by_date(latest_date)
                            filter_desc = f"Ngày {latest_date}"
                            self._orders_mode = f"date:{latest_date}"
                            if hasattr(self, "_filter_date_var"):
                                self._filter_date_var.set(f"📅 Ngày {latest_date}")
                    else:
                        all_recent = self.db.get_all_orders(limit=200)
                        if all_recent:
                            orders = all_recent
                            filter_desc = "Tất cả đơn gần nhất"

        if hasattr(self, "_orders_count_label") and self._orders_count_label.winfo_exists():
            self._orders_count_label.configure(text=f"({filter_desc}: {len(orders)} đơn)")

        self._render_orders_table(orders)

    def _render_orders_table(self, orders: list):
        for w in self._orders_list_frame.winfo_children():
            w.destroy()

        if not orders:
            ctk.CTkLabel(
                self._orders_list_frame,
                text="Không tìm thấy đơn hàng nào phù hợp.\nNhập mã khác hoặc chọn 'Hôm nay' / 'Tất cả gần đây'.",
                font=FONTS["body"], text_color=COLORS["text_muted"]
            ).pack(pady=PADDING["xl"])
            return

        # Header row
        hdr = ctk.CTkFrame(self._orders_list_frame, fg_color=COLORS["bg_secondary"], corner_radius=4)
        hdr.pack(fill="x", padx=PADDING["sm"], pady=(PADDING["sm"], PADDING["xs"]))

        cols = [
            ("Mã vận đơn", 170, "w"),
            ("Bàn", 45, "center"),
            ("Bắt đầu", 135, "center"),
            ("📅 Ngày xuất video", 150, "center"),
            ("Video đã lưu", 115, "center"),
            ("Trạng thái", 95, "center"),
            ("Thao tác", 150, "center"),
        ]
        for text, width, align in cols:
            lbl = ctk.CTkLabel(
                hdr, text=text, font=FONTS["small_bold"], text_color=COLORS["text_muted"],
                width=width, anchor=align
            )
            lbl.pack(side="left", padx=PADDING["xs"], pady=PADDING["xs"])

        # Paging for weak machines: render first 60 rows immediately, load more on demand
        batch = orders[:60]
        remaining = orders[60:]
        for raw_order in batch:
            self._render_single_order_row(raw_order)

        if remaining:
            self._create_load_more_button(remaining)

    def _create_load_more_button(self, remaining: list):
        more_btn = ctk.CTkButton(
            self._orders_list_frame,
            text=f"⬇️ Hiển thị thêm {len(remaining)} đơn hàng tiếp theo...",
            font=FONTS["body_bold"], height=36,
            fg_color=COLORS["bg_secondary"], hover_color=COLORS["border"],
            text_color=COLORS["accent"],
            command=lambda: self._append_more_orders(remaining)
        )
        more_btn.pack(fill="x", padx=PADDING["lg"], pady=PADDING["md"])

    def _append_more_orders(self, remaining: list):
        if not remaining or not hasattr(self, "_orders_list_frame"):
            return
        # Remove the more button
        for child in list(self._orders_list_frame.winfo_children())[-1:]:
            if isinstance(child, ctk.CTkButton):
                child.destroy()

        batch = remaining[:60]
        rest = remaining[60:]
        for raw_order in batch:
            self._render_single_order_row(raw_order)

        if rest:
            self._create_load_more_button(rest)

    def _render_single_order_row(self, raw_order):
        order = dict(raw_order) if raw_order else {}
        row = ctk.CTkFrame(self._orders_list_frame, fg_color="transparent", height=42, corner_radius=4)
        row.pack(fill="x", padx=PADDING["sm"], pady=1)
        row.pack_propagate(False)

        status = order.get("status", "")
        status_text = self._t(f"history.status_{status}")
        status_color = COLORS["success"] if status == "completed" else (COLORS["error"] if status == "cancelled" else COLORS["warning"])

        code_lbl = ctk.CTkLabel(
            row, text=order.get("order_sn", ""), font=FONTS["mono_bold"],
            text_color=COLORS["accent"], cursor="hand2", width=170, anchor="w"
        )
        code_lbl.pack(side="left", padx=PADDING["xs"])

        st_lbl = ctk.CTkLabel(
            row, text=str(order.get("scanner_id", 1)), font=FONTS["small"],
            text_color=COLORS["text_secondary"], width=45, anchor="center"
        )
        st_lbl.pack(side="left", padx=PADDING["xs"])

        start = order.get("start_time", "") or "---"
        start_lbl = ctk.CTkLabel(
            row, text=start, font=FONTS["small"],
            text_color=COLORS["text_secondary"], width=135, anchor="center"
        )
        start_lbl.pack(side="left", padx=PADDING["xs"])

        # 📅 Ngày xuất video: hiển thị chính xác ngày và giờ video xuất ra
        export_time = order.get("video_export_time") or order.get("end_time") or ""
        if status == "packing":
            export_display = "🔴 Đang quay..."
            export_color = "#f59e0b"
        elif export_time:
            export_display = export_time
            export_color = "#38bdf8"
        else:
            export_display = "---"
            export_color = COLORS["text_muted"]

        export_lbl = ctk.CTkLabel(
            row, text=export_display, font=FONTS["small_bold"] if export_time else FONTS["small"],
            text_color=export_color, width=150, anchor="center"
        )
        export_lbl.pack(side="left", padx=PADDING["xs"])

        # Video đã lưu & dung lượng
        v_count = order.get("video_count", 0)
        v_size = order.get("total_video_size", 0)
        if v_count > 0:
            sz_str = f" ({v_size/(1024*1024):.1f}MB)" if v_size and v_size >= 1024*1024 else (f" ({v_size/1024:.0f}KB)" if v_size else "")
            v_txt = f"🎬 {v_count} vid{sz_str}"
            v_color = COLORS["text_primary"]
        elif status == "packing":
            v_txt = "⏳ Đang ghi"
            v_color = "#f59e0b"
        else:
            v_txt = "0 video"
            v_color = COLORS["text_muted"]

        v_lbl = ctk.CTkLabel(
            row, text=v_txt, font=FONTS["small"],
            text_color=v_color, width=115, anchor="center"
        )
        v_lbl.pack(side="left", padx=PADDING["xs"])

        status_lbl = ctk.CTkLabel(
            row, text=status_text, font=FONTS["small_bold"],
            text_color=status_color, width=95, anchor="center"
        )
        status_lbl.pack(side="left", padx=PADDING["xs"])

        # Row Action Buttons: Mở video + Xóa đơn ngay cạnh mỗi đơn hàng
        btn_box = ctk.CTkFrame(row, fg_color="transparent", width=150)
        btn_box.pack(side="left", padx=PADDING["xs"])
        btn_box.pack_propagate(False)

        btn_title = f"📁 Video ({v_count})" if v_count > 1 else "📁 Mở video"
        row_btn = ctk.CTkButton(
            btn_box, text=btn_title, font=FONTS["small_bold"],
            width=80, height=28, fg_color="#0284c7", hover_color="#0369a1",
            command=lambda o=order, r=row: self._on_row_video_click(o, r)
        )
        row_btn.pack(side="left", padx=(0, PADDING["xs"]), pady=6)

        del_btn = ctk.CTkButton(
            btn_box, text="🗑️ Xóa", font=FONTS["small_bold"],
            width=55, height=28, fg_color="#ef4444", hover_color="#dc2626",
            command=lambda o=order: self._confirm_delete_order(o)
        )
        del_btn.pack(side="left", pady=6)

        # Bind clicks to select order
        for widget in (row, code_lbl, st_lbl, start_lbl, export_lbl, v_lbl, status_lbl):
            widget.bind("<Button-1>", lambda e, o=order, r=row: self._select_order(o, r))

    def _select_order(self, order, row_widget=None):
        if not order:
            return
        o = dict(order) if not isinstance(order, dict) else order
        self._selected_order = o

        # Highlight row
        if hasattr(self, "_selected_row_widget") and self._selected_row_widget and self._selected_row_widget.winfo_exists():
            try:
                self._selected_row_widget.configure(fg_color="transparent")
            except Exception:
                pass

        if row_widget and row_widget.winfo_exists():
            self._selected_row_widget = row_widget
            try:
                row_widget.configure(fg_color="#334155")
            except Exception:
                pass

        order_sn = o.get("order_sn", "")
        start = o.get("start_time", "") or "---"
        end = o.get("end_time", "") or "---"
        status = o.get("status", "")
        status_text = self._t(f"history.status_{status}")

        video_files = self._locate_order_video_files(o)
        video_checks = self.db.get_video_checks(order_id) if (order_id := o.get("id")) else []
        video_export_time = o.get("video_export_time") or (video_files[0]["export_time"] if video_files else end)
        if not video_export_time or video_export_time == "---":
            if status == "packing":
                export_display = "🔴 Đang ghi hình..."
            else:
                export_display = "Chưa xuất video"
        else:
            export_display = video_export_time

        if hasattr(self, "_selected_order_title") and self._selected_order_title.winfo_exists():
            self._selected_order_title.configure(
                text=f"📦 Đang chọn đơn: {order_sn}   |   📅 Ngày xuất video: {export_display}   |   Trạng thái: {status_text}"
            )

        if hasattr(self, "_open_folder_btn") and self._open_folder_btn.winfo_exists():
            self._open_folder_btn.configure(state="normal")
            if len(video_files) > 1:
                self._open_folder_btn.configure(text=f"📁 Mở thư mục ({len(video_files)} video)")
            else:
                self._open_folder_btn.configure(text="📁 Mở video (Explorer)")

        if hasattr(self, "_delete_order_btn") and self._delete_order_btn.winfo_exists():
            self._delete_order_btn.configure(state="normal")

        if hasattr(self, "_zalo_export_btn") and self._zalo_export_btn.winfo_exists():
            self._zalo_export_btn.configure(state="normal" if video_files and status != "packing" else "disabled")

        if hasattr(self, "_order_video_status") and self._order_video_status.winfo_exists():
            problems = [c for c in video_checks if c["status"] in ("missing", "corrupt", "degraded")]
            pending = [c for c in video_checks if c["status"] == "recording"]
            if problems:
                details = "; ".join(f"Cam {c['camera_channel']}: {c['message']}" for c in problems)
                self._order_video_status.configure(text=f"⚠️ Bằng chứng cần kiểm tra: {details}", text_color=COLORS["warning"])
            elif pending:
                message = "⏳ Đang ghi hình..." if status == "packing" else "⏳ Đang hoàn tất và kiểm tra video..."
                self._order_video_status.configure(text=message, text_color=COLORS["warning"])
            elif video_checks and len(video_checks) == len(video_files) and all(c["status"] == "ok" for c in video_checks):
                self._order_video_status.configure(text=f"✅ Đã kiểm tra đủ {len(video_files)} video, mở và đọc được khung hình.", text_color=COLORS["success"])
            elif video_files:
                v_parts = []
                for v in video_files:
                    v_parts.append(
                        f"🎬 Cam {v.get('channel', 1)}: {v.get('filename')} ({v.get('size_str')}) [Xuất: {v.get('export_time')}]"
                    )
                details = "   •   ".join(v_parts)
                self._order_video_status.configure(
                    text=f"✅ {len(video_files)} video sẵn sàng: {details}",
                    text_color="#38bdf8"
                )
            else:
                if status == "packing":
                    self._order_video_status.configure(
                        text="⏳ Đơn hàng đang được ghi hình trực tiếp...",
                        text_color="#fbbf24"
                    )
                else:
                    self._order_video_status.configure(
                        text=f"⚠️ Bắt đầu: {start} | Kết thúc: {end} | Không tìm thấy file video trên ổ đĩa.",
                        text_color=COLORS["text_secondary"]
                    )

    def _confirm_delete_order(self, order):
        """Confirm and permanently delete order record and associated video."""
        if not order:
            return
        o = dict(order) if not isinstance(order, dict) else order
        order_id = o.get("id")
        order_sn = o.get("order_sn", "")
        if not order_id:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("🗑️ Xác nhận xóa đơn hàng")
        dialog.geometry("460x240")
        dialog.configure(fg_color=COLORS["bg_primary"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.attributes("-topmost", True)

        try:
            dialog.update_idletasks()
            x = self.winfo_x() + (self.winfo_width() // 2) - 230
            y = self.winfo_y() + (self.winfo_height() // 2) - 120
            dialog.geometry(f"+{max(x, 50)}+{max(y, 50)}")
        except Exception:
            pass

        ctk.CTkLabel(
            dialog, text="🗑️ Xác nhận xóa đơn hàng",
            font=FONTS["heading"], text_color=COLORS["error"]
        ).pack(pady=(PADDING["md"], PADDING["xs"]))

        info_card = ctk.CTkFrame(dialog, fg_color=COLORS["bg_card"], corner_radius=6)
        info_card.pack(fill="x", padx=PADDING["lg"], pady=PADDING["sm"])

        ctk.CTkLabel(
            info_card,
            text=f"Bạn có chắc muốn xóa vĩnh viễn đơn: {order_sn}?\n(Thao tác này sẽ xóa đơn khỏi hệ thống và dọn dẹp file video)",
            font=FONTS["body"], text_color=COLORS["text_primary"],
            justify="center"
        ).pack(padx=PADDING["md"], pady=PADDING["sm"])

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=PADDING["lg"], pady=PADDING["md"])

        def _do_delete():
            dialog.destroy()
            try:
                self.db.delete_order(order_id, delete_video_files=True)
                if hasattr(self, "_selected_order") and self._selected_order and self._selected_order.get("id") == order_id:
                    self._selected_order = None
                    if hasattr(self, "_selected_order_title") and self._selected_order_title.winfo_exists():
                        self._selected_order_title.configure(
                            text="💡 Bấm vào mã đơn hàng bên dưới để chọn đơn, sau đó bấm nút để mở thẳng vị trí video trong thư mục."
                        )
                    if hasattr(self, "_order_video_status") and self._order_video_status.winfo_exists():
                        self._order_video_status.configure(text="")
                    if hasattr(self, "_open_folder_btn") and self._open_folder_btn.winfo_exists():
                        self._open_folder_btn.configure(state="disabled")
                    if hasattr(self, "_delete_order_btn") and self._delete_order_btn.winfo_exists():
                        self._delete_order_btn.configure(state="disabled")

                self._refresh_orders_list()
                self._update_status_bar()
                self._on_log(f"🗑️ Đã xóa đơn hàng: {order_sn}", 1)
            except Exception as e:
                log.error(f"[Orders] Delete error: {e}")
                self._on_log(f"❌ Lỗi khi xóa đơn {order_sn}: {e}", 1)

        ctk.CTkButton(
            btn_row, text="🗑️ Xóa vĩnh viễn", font=FONTS["body_bold"],
            height=36, fg_color="#ef4444", hover_color="#dc2626", text_color="#ffffff",
            command=_do_delete
        ).pack(side="left", fill="x", expand=True, padx=(0, PADDING["sm"]))

        ctk.CTkButton(
            btn_row, text="✕ Hủy bỏ", font=FONTS["body"],
            height=36, fg_color="#334155", hover_color="#475569", text_color="#ffffff",
            command=dialog.destroy
        ).pack(side="left", fill="x", expand=True)

    def _on_row_video_click(self, order, row_widget):
        self._select_order(order, row_widget)
        self._open_order_video_in_folder(order)

    def _open_order_video_in_folder(self, order):
        if not order:
            return

        filepath = self._locate_order_video_file(order)
        if filepath and os.path.isfile(filepath):
            norm = os.path.normpath(filepath)
            try:
                subprocess.Popen(["explorer", f"/select,{norm}"])
                msg = f"✅ Đã mở vị trí video: {os.path.basename(filepath)}"
                color = COLORS["success"]
            except Exception as e:
                log.error(f"[Orders] Explorer launch error: {e}")
                msg = f"⚠️ Lỗi mở Explorer: {e}"
                color = COLORS["warning"]
        else:
            msg = "❌ Không tìm thấy video: File video đã bị xóa hoặc di chuyển khỏi thư mục!"
            color = COLORS["error"]

        if hasattr(self, "_order_video_status") and self._order_video_status.winfo_exists():
            self._order_video_status.configure(text=msg, text_color=color)

    def _export_selected_order_for_zalo(self):
        order = getattr(self, "_selected_order", None)
        if not order:
            return
        videos = self._locate_order_video_files(order)
        if not videos:
            return
        self._zalo_export_btn.configure(state="disabled")
        self._order_video_status.configure(text=f"⏳ Đang xuất {len(videos)} video H.264 để gửi Zalo...", text_color=COLORS["warning"])
        output_dir = os.path.join(self.config.base_dir, "ZaloExports")

        def worker():
            try:
                exported = [export_for_zalo(v["filepath"], output_dir) for v in videos]
                def done():
                    self._zalo_export_btn.configure(state="normal")
                    self._order_video_status.configure(
                        text=f"✅ Đã xuất {len(exported)} video H.264 vào thư mục ZaloExports. File gốc được giữ nguyên.",
                        text_color=COLORS["success"]
                    )
                    subprocess.Popen(["explorer", "/select,", exported[0]])
                self.after(0, done)
            except Exception as exc:
                log.error(f"[Zalo] Export error: {exc}")
                def failed(message=str(exc)):
                    self._zalo_export_btn.configure(state="normal")
                    self._order_video_status.configure(text=f"❌ Xuất video thất bại: {message}", text_color=COLORS["error"])
                self.after(0, failed)

        threading.Thread(target=worker, daemon=True, name="ZaloExportWorker").start()

    def _locate_order_video_files(self, order) -> list:
        """
        Find all existing video files for an order, with camera channel, size, and export time.
        Returns list of dicts: [{"channel": 1, "filename": "...", "filepath": "...", "size_str": "...", "export_time": "..."}, ...]
        """
        if not order:
            return []
        o = dict(order) if not isinstance(order, dict) else order
        order_id = o.get("id")
        order_sn = o.get("order_sn", "")
        start_time = o.get("start_time", "")
        order_date = start_time[:10] if start_time else date.today().isoformat()

        found_files = {}  # filepath -> dict

        # 1. Check DB videos table
        if order_id:
            try:
                db_videos = self.db.get_order_videos(order_id)
                for raw_v in db_videos:
                    v = dict(raw_v) if not isinstance(raw_v, dict) else raw_v
                    fp = v.get("filepath", "")
                    if fp and fp not in found_files:
                        found_files[fp] = {
                            "channel": v.get("camera_channel", 1),
                            "filename": v.get("filename") or os.path.basename(fp),
                            "filepath": fp,
                            "size": v.get("file_size", 0),
                            "export_time": v.get("created_at") or o.get("end_time") or "",
                            "duration": v.get("duration_seconds", 0),
                        }
            except Exception as e:
                log.error(f"[Orders] DB video query error: {e}")

        # Also check by order_sn in DB
        try:
            sn_videos = self.db.get_videos_by_order_sn(order_sn)
            for raw_v in sn_videos:
                v = dict(raw_v) if not isinstance(raw_v, dict) else raw_v
                fp = v.get("filepath", "")
                if fp and fp not in found_files:
                    found_files[fp] = {
                        "channel": v.get("camera_channel", 1),
                        "filename": v.get("filename") or os.path.basename(fp),
                        "filepath": fp,
                        "size": v.get("file_size", 0),
                        "export_time": v.get("created_at") or o.get("end_time") or "",
                        "duration": v.get("duration_seconds", 0),
                    }
        except Exception:
            pass

        # 2. Check filesystem directory
        video_dir = self.config.get("video_dir", "Videos")
        if not os.path.isabs(video_dir):
            video_dir = os.path.join(self.config.base_dir, video_dir)

        search_dirs = [os.path.join(video_dir, order_date)]
        if os.path.isdir(video_dir):
            try:
                for item in os.listdir(video_dir):
                    sub = os.path.join(video_dir, item)
                    if os.path.isdir(sub) and sub not in search_dirs:
                        search_dirs.append(sub)
            except Exception:
                pass

        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            try:
                for fname in sorted(os.listdir(d)):
                    if fname.lower().endswith(".mp4"):
                        base_no_ext = os.path.splitext(fname)[0]
                        if (base_no_ext == order_sn or
                            base_no_ext.startswith(f"{order_sn}_Cam") or
                            base_no_ext.startswith(f"{order_sn}_Lan") or
                            base_no_ext.startswith(f"{order_sn}_")):
                            fp = os.path.join(d, fname)
                            if fp not in found_files and os.path.isfile(fp):
                                mtime = os.path.getmtime(fp)
                                mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                                ch = 2 if "Cam2" in fname else 1
                                found_files[fp] = {
                                    "channel": ch,
                                    "filename": fname,
                                    "filepath": fp,
                                    "size": os.path.getsize(fp),
                                    "export_time": mtime_str,
                                    "duration": 0,
                                }
            except Exception:
                pass

        # Format and verify existing files
        results = []
        for fp, info in found_files.items():
            if os.path.isfile(fp):
                sz = info.get("size") or os.path.getsize(fp)
                if sz < 1024 * 1024:
                    sz_str = f"{sz / 1024:.1f} KB"
                else:
                    sz_str = f"{sz / (1024 * 1024):.1f} MB"
                info["size_str"] = sz_str
                if not info.get("export_time"):
                    mtime = os.path.getmtime(fp)
                    info["export_time"] = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                results.append(info)

        # Sort by camera channel then filename
        results.sort(key=lambda x: (x.get("channel", 1), x.get("filename", "")))
        return results

    def _locate_order_video_file(self, order) -> Optional[str]:
        files = self._locate_order_video_files(order)
        if files:
            return files[-1]["filepath"]
        return None

    # ═══════════════════════════════════════════
    # STATS PAGE
    # ═══════════════════════════════════════════
    def _build_stats_page(self):
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.pack(fill="both", expand=True, padx=PADDING["md"], pady=PADDING["md"])

        ctk.CTkLabel(page, text=self._t("stats.title"), font=FONTS["heading"], text_color=COLORS["text_primary"]).pack(anchor="w", pady=(0, PADDING["md"]))

        today = date.today().isoformat()
        total = self.db.get_today_count()
        stats = self.db.get_stats_by_date(today)
        hourly = self.db.get_hourly_stats(today)

        # Summary cards
        summary = ctk.CTkFrame(page, fg_color="transparent")
        summary.pack(fill="x", pady=(0, PADDING["md"]))

        total_card = ctk.CTkFrame(summary, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
        total_card.pack(side="left", fill="x", expand=True, padx=(0, PADDING["sm"]))
        ctk.CTkLabel(total_card, text=str(total), font=("Segoe UI", 36, "bold"), text_color=COLORS["accent"]).pack(padx=PADDING["lg"], pady=(PADDING["md"], 0))
        ctk.CTkLabel(total_card, text=self._t("stats.today"), font=FONTS["body"], text_color=COLORS["text_secondary"]).pack(padx=PADDING["lg"], pady=(0, PADDING["md"]))

        # Per station cards
        for stat in stats:
            card = ctk.CTkFrame(summary, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
            card.pack(side="left", fill="x", expand=True, padx=PADDING["xs"])
            ctk.CTkLabel(card, text=str(stat["count"]), font=("Segoe UI", 28, "bold"), text_color=COLORS["success"]).pack(padx=PADDING["md"], pady=(PADDING["md"], 0))
            avg = f"{stat['avg_seconds']:.0f}s" if stat["avg_seconds"] else "---"
            ctk.CTkLabel(card, text=f"Bàn {stat['scanner_id']} | TB: {avg}", font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(padx=PADDING["md"], pady=(0, PADDING["md"]))

        # Hourly chart (text-based simple chart)
        chart_card = ctk.CTkFrame(page, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
        chart_card.pack(fill="both", expand=True)
        ctk.CTkLabel(chart_card, text=self._t("stats.hourly"), font=FONTS["body_bold"], text_color=COLORS["text_primary"]).pack(anchor="w", padx=PADDING["md"], pady=PADDING["sm"])

        if hourly:
            max_count = max(h["count"] for h in hourly) if hourly else 1
            chart_inner = ctk.CTkFrame(chart_card, fg_color="transparent")
            chart_inner.pack(fill="both", expand=True, padx=PADDING["md"], pady=(0, PADDING["md"]))
            for h in hourly:
                row = ctk.CTkFrame(chart_inner, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text=f"{h['hour']:02d}:00", font=FONTS["mono"], text_color=COLORS["text_muted"], width=60).pack(side="left")
                bar_width = max(5, int((h["count"] / max_count) * 300)) if max_count > 0 else 5
                bar = ctk.CTkFrame(row, fg_color=COLORS["accent"], height=18, width=bar_width, corner_radius=4)
                bar.pack(side="left", padx=PADDING["xs"])
                bar.pack_propagate(False)
                ctk.CTkLabel(row, text=str(h["count"]), font=FONTS["small_bold"], text_color=COLORS["text_primary"]).pack(side="left", padx=PADDING["xs"])
        else:
            ctk.CTkLabel(chart_card, text=self._t("stats.no_data"), font=FONTS["body"], text_color=COLORS["text_muted"]).pack(pady=PADDING["xl"])

        # Export button
        export_btn = ctk.CTkButton(
            page, text=self._t("stats.export_excel"), font=FONTS["body_bold"],
            height=40, fg_color=COLORS["success"], hover_color="#16a34a",
            command=self._export_excel
        )
        export_btn.pack(anchor="e", pady=PADDING["md"])
        return page

    def _export_excel(self):
        try:
            from openpyxl import Workbook
            today = date.today().isoformat()
            orders = self.db.get_orders_by_date(today)
            wb = Workbook()
            ws = wb.active
            ws.title = f"Đóng gói {today}"
            ws.append(["STT", "Mã vận đơn", "Bàn", "Bắt đầu", "Ngày xuất video", "Số video", "File video", "Trạng thái", "Người phụ trách"])
            for i, o in enumerate(orders, 1):
                export_time = o.get("video_export_time") or o.get("end_time") or ""
                v_count = o.get("video_count", 0)
                v_files = o.get("video_filenames") or ""
                ws.append([i, o["order_sn"], o["scanner_id"], o["start_time"], export_time, v_count, v_files, o["status"], o["operator"] or ""])
            filepath = os.path.join(self.config.base_dir, f"ThongKe_{today}.xlsx")
            wb.save(filepath)
            self._on_log(self._t("stats.export_success", file=filepath), 0)
        except ImportError:
            self._on_log("❌ Cần cài openpyxl: pip install openpyxl", 0)
        except Exception as e:
            self._on_log(f"❌ Export error: {e}", 0)

    # ═══════════════════════════════════════════
    # SETTINGS PAGE
    # ═══════════════════════════════════════════
    def _build_settings_page(self):
        page = ctk.CTkScrollableFrame(self._content, fg_color="transparent")
        page.pack(fill="both", expand=True, padx=PADDING["md"], pady=PADDING["md"])

        ctk.CTkLabel(page, text=self._t("settings.title"), font=FONTS["heading"], text_color=COLORS["text_primary"]).pack(anchor="w", pady=(0, PADDING["md"]))

        # ── Camera Quick Setup ──
        setup_card = ctk.CTkFrame(page, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
        setup_card.pack(fill="x", pady=PADDING["sm"])
        ctk.CTkLabel(setup_card, text="🔌 Kết nối Camera nhanh", font=FONTS["body_bold"], text_color=COLORS["accent"]).pack(anchor="w", padx=PADDING["md"], pady=(PADDING["md"], PADDING["sm"]))

        setup_inner = ctk.CTkFrame(setup_card, fg_color="transparent")
        setup_inner.pack(fill="x", padx=PADDING["md"], pady=(0, PADDING["md"]))

        setup_btns = ctk.CTkFrame(setup_inner, fg_color="transparent")
        setup_btns.pack(fill="x", pady=PADDING["xs"])

        ctk.CTkButton(
            setup_btns, text="📱 Quét QR Camera", font=FONTS["body_bold"],
            height=44, fg_color="#7c3aed", hover_color="#6d28d9",
            command=self._open_qr_scan_dialog
        ).pack(side="left", fill="x", expand=True, padx=(0, PADDING["xs"]))

        ctk.CTkButton(
            setup_btns, text="🔍 Dò Camera", font=FONTS["body_bold"],
            height=44, fg_color="#0891b2", hover_color="#0e7490",
            command=self._open_network_scan_dialog
        ).pack(side="left", fill="x", expand=True, padx=(PADDING["xs"], PADDING["xs"]))

        ctk.CTkButton(
            setup_btns, text="⚡ Kích hoạt Imou (37777)", font=FONTS["body_bold"],
            height=44, fg_color="#ea580c", hover_color="#c2410c",
            command=self._open_imou_sync_dialog
        ).pack(side="left", fill="x", expand=True, padx=(0, 0))


        self._setup_status = ctk.CTkLabel(
            setup_inner, text="💡 Quét mã QR dưới đít camera hoặc dò tự động trên mạng LAN",
            font=FONTS["small"], text_color=COLORS["text_muted"]
        )
        self._setup_status.pack(anchor="w", pady=(PADDING["xs"], 0))

        # ── Camera Settings (Dynamic) ──
        cam_card = ctk.CTkFrame(page, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
        cam_card.pack(fill="x", pady=PADDING["sm"])
        ctk.CTkLabel(cam_card, text="📷 " + self._t("settings.tab_camera") + " (Danh sách Camera)", font=FONTS["body_bold"], text_color=COLORS["accent"]).pack(anchor="w", padx=PADDING["md"], pady=(PADDING["md"], PADDING["sm"]))

        self._cam_inner = ctk.CTkFrame(cam_card, fg_color="transparent")
        self._cam_inner.pack(fill="x", padx=PADDING["md"], pady=(0, PADDING["md"]))

        self._cam_rows_frame = ctk.CTkFrame(self._cam_inner, fg_color="transparent")
        self._cam_rows_frame.pack(fill="x")

        # Initial camera entries
        station_cams = self.config.get_station_cameras(1)
        self._render_camera_rows(station_cams)

        cam_btn_bar = ctk.CTkFrame(self._cam_inner, fg_color="transparent")
        cam_btn_bar.pack(fill="x", pady=(PADDING["sm"], 0))

        ctk.CTkButton(
            cam_btn_bar, text="➕ Thêm Camera", font=FONTS["small_bold"],
            height=34, fg_color="#0d9488", hover_color="#0f766e",
            command=self._add_camera_row
        ).pack(side="left")

        ctk.CTkLabel(self._cam_inner, text=self._t("settings.camera_url_hint"), font=FONTS["small"], text_color=COLORS["text_muted"]).pack(anchor="w", pady=(PADDING["xs"], 0))
        ctk.CTkLabel(
            self._cam_inner,
            text="💡 Mẹo: Bấm nút '🔑 Mật khẩu' cạnh từng camera để nhập nhanh mã Safety Code dưới đáy camera mà không cần gõ thủ công URL.",
            font=FONTS["small"], text_color=COLORS["accent"]
        ).pack(anchor="w", pady=(2, 0))

        # ── Video Settings ──
        vid_card = ctk.CTkFrame(page, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
        vid_card.pack(fill="x", pady=PADDING["sm"])
        ctk.CTkLabel(vid_card, text="🎬 " + self._t("settings.tab_video"), font=FONTS["body_bold"], text_color=COLORS["accent"]).pack(anchor="w", padx=PADDING["md"], pady=(PADDING["md"], PADDING["sm"]))

        vid_inner = ctk.CTkFrame(vid_card, fg_color="transparent")
        vid_inner.pack(fill="x", padx=PADDING["md"], pady=(0, PADDING["md"]))

        ctk.CTkLabel(vid_inner, text=self._t("settings.video_dir"), font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(anchor="w")
        vdir_frame = ctk.CTkFrame(vid_inner, fg_color="transparent")
        vdir_frame.pack(fill="x", pady=(0, PADDING["sm"]))
        self._video_dir_entry = ctk.CTkEntry(vdir_frame, font=FONTS["body"], fg_color=COLORS["bg_input"], border_color=COLORS["border"], text_color=COLORS["text_primary"])
        self._video_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, PADDING["xs"]))
        self._video_dir_entry.insert(0, self.config.video_dir)
        ctk.CTkButton(vdir_frame, text="📁", width=40, command=self._choose_video_dir).pack(side="right")

        self._auto_record_var = ctk.BooleanVar(value=self.config.get("auto_record", True))
        ctk.CTkCheckBox(vid_inner, text=self._t("settings.auto_record"), variable=self._auto_record_var, font=FONTS["body"], text_color=COLORS["text_primary"]).pack(anchor="w", pady=PADDING["xs"])

        # Max Recording Duration
        max_rec_frame = ctk.CTkFrame(vid_inner, fg_color="transparent")
        max_rec_frame.pack(fill="x", pady=(PADDING["sm"], 0))
        ctk.CTkLabel(max_rec_frame, text="⏱️ Thời gian ghi hình tối đa mỗi đơn (phút):", font=FONTS["body"], text_color=COLORS["text_primary"]).pack(side="left")
        self._max_record_entry = ctk.CTkEntry(max_rec_frame, width=90, font=FONTS["body_bold"], fg_color=COLORS["bg_input"], border_color=COLORS["border"], text_color=COLORS["text_primary"])
        self._max_record_entry.pack(side="right")
        self._max_record_entry.insert(0, str(self.config.get("max_record_duration_minutes", 10)))
        ctk.CTkLabel(
            vid_inner,
            text="💡 Tự động dừng quay và lưu video nếu đóng gói quá số phút này (tránh quên quét mã dừng làm đầy ổ cứng). Đặt 0 để không giới hạn.",
            font=FONTS["small"], text_color=COLORS["text_muted"]
        ).pack(anchor="w", pady=(2, PADDING["xs"]))

        # Video Retention Days
        retention_frame = ctk.CTkFrame(vid_inner, fg_color="transparent")
        retention_frame.pack(fill="x", pady=(PADDING["xs"], 0))
        ctk.CTkLabel(retention_frame, text="📅 Số ngày lưu trữ video (tối thiểu 7 ngày):", font=FONTS["body"], text_color=COLORS["text_primary"]).pack(side="left")
        self._retention_entry = ctk.CTkEntry(retention_frame, width=90, font=FONTS["body_bold"], fg_color=COLORS["bg_input"], border_color=COLORS["border"], text_color=COLORS["text_primary"])
        self._retention_entry.pack(side="right")
        current_retention = max(7, int(self.config.get("video_retention_days", 30)))
        self._retention_entry.insert(0, str(current_retention))
        ctk.CTkLabel(
            vid_inner,
            text="💡 Video cũ hơn số ngày cài đặt sẽ tự động được xóa vĩnh viễn định kỳ để nhẹ máy (mặc định: 30 ngày, tối thiểu: 7 ngày).",
            font=FONTS["small"], text_color=COLORS["text_muted"]
        ).pack(anchor="w", pady=(2, 0))

        # ── System Settings ──
        sys_card = ctk.CTkFrame(page, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
        sys_card.pack(fill="x", pady=PADDING["sm"])
        ctk.CTkLabel(sys_card, text="💻 " + self._t("settings.tab_system"), font=FONTS["body_bold"], text_color=COLORS["accent"]).pack(anchor="w", padx=PADDING["md"], pady=(PADDING["md"], PADDING["sm"]))

        sys_inner = ctk.CTkFrame(sys_card, fg_color="transparent")
        sys_inner.pack(fill="x", padx=PADDING["md"], pady=(0, PADDING["md"]))

        self._sound_var = ctk.BooleanVar(value=self.config.get("sound_enabled", True))
        ctk.CTkCheckBox(sys_inner, text=self._t("settings.sound_enabled"), variable=self._sound_var, font=FONTS["body"], text_color=COLORS["text_primary"]).pack(anchor="w", pady=PADDING["xs"])

        self._auto_scan_var = ctk.BooleanVar(value=self.config.get("auto_scan_enabled", True))
        ctk.CTkCheckBox(sys_inner, text=self._t("settings.auto_scan"), variable=self._auto_scan_var, font=FONTS["body"], text_color=COLORS["text_primary"]).pack(anchor="w", pady=PADDING["xs"])

        from core.startup_manager import is_startup_enabled
        self._startup_var = ctk.BooleanVar(value=is_startup_enabled())
        ctk.CTkCheckBox(sys_inner, text=self._t("settings.startup_windows"), variable=self._startup_var, font=FONTS["body"], text_color=COLORS["text_primary"]).pack(anchor="w", pady=PADDING["xs"])

        # ── PIN Protection Card ──
        pin_card = ctk.CTkFrame(page, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
        pin_card.pack(fill="x", pady=PADDING["sm"])
        pin_header = ctk.CTkFrame(pin_card, fg_color="transparent")
        pin_header.pack(fill="x", padx=PADDING["md"], pady=(PADDING["md"], PADDING["sm"]))
        ctk.CTkLabel(pin_header, text="🔐 " + self._t("settings.pin_title"), font=FONTS["body_bold"], text_color=COLORS["accent"]).pack(side="left")
        self._pin_status_label = ctk.CTkLabel(
            pin_header,
            text=self._t("settings.pin_set") if self.config.is_pin_set() else self._t("settings.pin_not_set"),
            font=FONTS["small_bold"],
            text_color=COLORS["success"] if self.config.is_pin_set() else COLORS["warning"]
        )
        self._pin_status_label.pack(side="right")

        pin_inner = ctk.CTkFrame(pin_card, fg_color="transparent")
        pin_inner.pack(fill="x", padx=PADDING["md"], pady=(0, PADDING["md"]))

        pin_grid = ctk.CTkFrame(pin_inner, fg_color="transparent")
        pin_grid.pack(fill="x", pady=PADDING["xs"])

        ctk.CTkLabel(pin_grid, text=self._t("settings.pin_new"), font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(side="left", padx=(0, PADDING["xs"]))
        self._pin_new_entry = ctk.CTkEntry(pin_grid, font=FONTS["body"], show="*", width=120, fg_color=COLORS["bg_input"], border_color=COLORS["border"])
        self._pin_new_entry.pack(side="left", padx=(0, PADDING["md"]))

        ctk.CTkLabel(pin_grid, text=self._t("settings.pin_confirm"), font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(side="left", padx=(0, PADDING["xs"]))
        self._pin_confirm_entry = ctk.CTkEntry(pin_grid, font=FONTS["body"], show="*", width=120, fg_color=COLORS["bg_input"], border_color=COLORS["border"])
        self._pin_confirm_entry.pack(side="left", padx=(0, PADDING["md"]))

        def _update_pin_action():
            p1 = self._pin_new_entry.get().strip()
            p2 = self._pin_confirm_entry.get().strip()
            if not p1 and not p2:
                self.config.set_pin("")
                self._pin_status_label.configure(text=self._t("settings.pin_not_set"), text_color=COLORS["warning"])
                self._on_log("✅ Đã hủy bảo vệ bằng mã PIN", 0)
                return
            if p1 != p2:
                self._on_log("❌ Mã PIN xác nhận không khớp!", 0)
                return
            self.config.set_pin(p1)
            self._pin_new_entry.delete(0, "end")
            self._pin_confirm_entry.delete(0, "end")
            self._pin_status_label.configure(text=self._t("settings.pin_set"), text_color=COLORS["success"])
            self._on_log("✅ Đã cập nhật mã PIN bảo mật thành công", 0)

        ctk.CTkButton(
            pin_grid, text="Cập nhật PIN", font=FONTS["small_bold"],
            width=110, height=32, fg_color="#2563eb", hover_color="#1d4ed8",
            command=_update_pin_action
        ).pack(side="left")

        # ── Software Update Card (GitHub) ──
        from core.updater import CURRENT_VERSION
        upd_card = ctk.CTkFrame(page, fg_color=COLORS["bg_card"], corner_radius=SIZES["border_radius"])
        upd_card.pack(fill="x", pady=PADDING["sm"])

        upd_header = ctk.CTkFrame(upd_card, fg_color="transparent")
        upd_header.pack(fill="x", padx=PADDING["md"], pady=(PADDING["md"], PADDING["xs"]))
        ctk.CTkLabel(
            upd_header,
            text="🚀 Cập nhật phần mềm (GitHub Release)",
            font=FONTS["body_bold"],
            text_color=COLORS["accent"],
        ).pack(side="left")
        ctk.CTkLabel(
            upd_header,
            text=f"Phiên bản hiện tại: {CURRENT_VERSION}",
            font=FONTS["small_bold"],
            text_color=COLORS["success"],
        ).pack(side="right")

        upd_inner = ctk.CTkFrame(upd_card, fg_color="transparent")
        upd_inner.pack(fill="x", padx=PADDING["md"], pady=(0, PADDING["md"]))

        self._update_status_label = ctk.CTkLabel(
            upd_inner,
            text="💡 Kiểm tra và tải bản cập nhật mới nhất trực tiếp từ GitHub (giữ nguyên 100% dữ liệu đơn hàng, video và cấu hình máy).",
            font=FONTS["small"],
            text_color=COLORS["text_secondary"],
            justify="left",
            wraplength=680,
        )
        self._update_status_label.pack(anchor="w", pady=(0, PADDING["xs"]))

        self._update_progress_bar = ctk.CTkProgressBar(upd_inner, height=10, progress_color=COLORS["accent"])
        self._update_progress_bar.set(0)

        upd_btn_row = ctk.CTkFrame(upd_inner, fg_color="transparent")
        upd_btn_row.pack(fill="x", pady=(PADDING["xs"], 0))

        self._check_update_btn = ctk.CTkButton(
            upd_btn_row,
            text="🔄 Kiểm tra cập nhật",
            font=FONTS["small_bold"],
            width=160,
            height=34,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._on_check_for_update,
        )
        self._check_update_btn.pack(side="left", padx=(0, PADDING["sm"]))

        self._apply_update_btn = ctk.CTkButton(
            upd_btn_row,
            text="⬇️ Tải & Cập nhật ngay",
            font=FONTS["small_bold"],
            width=190,
            height=34,
            fg_color=COLORS["success"],
            hover_color="#15803d",
            command=self._on_apply_update,
        )
        self._pending_update_info = None

        # Save button
        ctk.CTkButton(
            page, text=self._t("settings.save"), font=FONTS["body_bold"],
            height=44, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._save_settings
        ).pack(fill="x", pady=PADDING["md"])
        return page

    def _render_camera_rows(self, cam_urls=None):
        """Render dynamic camera input rows."""
        if cam_urls is None:
            cam_urls = [e.get().strip() for e in self._cam_entries]

        for w in self._cam_rows_frame.winfo_children():
            w.destroy()

        self._cam_entries = []
        if not cam_urls:
            cam_urls = [""]

        for idx, url in enumerate(cam_urls):
            row_frame = ctk.CTkFrame(self._cam_rows_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=(0, PADDING["sm"]))

            header = ctk.CTkFrame(row_frame, fg_color="transparent")
            header.pack(fill="x", pady=(0, 2))

            ctk.CTkLabel(
                header, text=f"Camera {idx + 1} - RTSP URL:",
                font=FONTS["small_bold"], text_color=COLORS["text_secondary"]
            ).pack(side="left")

            if len(cam_urls) > 1:
                ctk.CTkButton(
                    header, text="🗑️ Xóa", font=FONTS["small"],
                    width=55, height=22, fg_color="transparent",
                    hover_color="#ef4444", text_color=COLORS["text_muted"],
                    command=lambda i=idx: self._remove_camera_row(i)
                ).pack(side="right")

            input_box = ctk.CTkFrame(row_frame, fg_color="transparent")
            input_box.pack(fill="x")

            entry = ctk.CTkEntry(
                input_box, font=FONTS["body"],
                fg_color=COLORS["bg_input"], border_color=COLORS["border"],
                text_color=COLORS["text_primary"]
            )
            entry.pack(side="left", fill="x", expand=True, padx=(0, PADDING["xs"]))
            entry.insert(0, url)
            self._cam_entries.append(entry)

            ctk.CTkButton(
                input_box, text="🔑 Mật khẩu", font=FONTS["small_bold"],
                width=100, height=32, fg_color="#2563eb", hover_color="#1d4ed8",
                command=lambda i=idx: self._open_edit_camera_password_dialog(i)
            ).pack(side="right")

        # Backward compatibility pointers
        self._cam1_entry = self._cam_entries[0] if len(self._cam_entries) > 0 else None
        self._cam2_entry = self._cam_entries[1] if len(self._cam_entries) > 1 else None
        self._cam3_entry = self._cam_entries[2] if len(self._cam_entries) > 2 else None

    @staticmethod
    def _parse_rtsp_url(url: str):
        """Extract username, password, and host_path from an RTSP URL."""
        username = "admin"
        password = ""
        host_path = ""

        if not url:
            return username, password, host_path

        u = url.strip()
        if u.lower().startswith("rtsp://"):
            body = u[7:]
        else:
            body = u

        if "@" in body:
            last_at = body.rfind("@")
            creds = body[:last_at]
            host_path = body[last_at + 1:]
            if ":" in creds:
                username, password = creds.split(":", 1)
            else:
                username = creds
                password = ""
        else:
            host_path = body
            username = "admin"
            password = ""

        return username, password, host_path

    @staticmethod
    def _update_rtsp_password(url: str, new_password: str, username: str = "admin", default_channel: int = 1) -> str:
        """Update or insert credentials in RTSP URL without breaking stream path."""
        user = username.strip() or "admin"
        new_pwd = new_password.strip()

        if not url or not url.strip():
            if new_pwd:
                return f"rtsp://{user}:{new_pwd}@192.168.1.108:554/cam/realmonitor?channel={default_channel}&subtype=0"
            return f"rtsp://{user}@192.168.1.108:554/cam/realmonitor?channel={default_channel}&subtype=0"

        u = url.strip()
        if u.lower().startswith("rtsp://"):
            body = u[7:]
        else:
            body = u

        if "@" in body:
            last_at = body.rfind("@")
            host_path = body[last_at + 1:]
        else:
            host_path = body

        if new_pwd:
            return f"rtsp://{user}:{new_pwd}@{host_path}"
        else:
            return f"rtsp://{user}@{host_path}"

    def _open_edit_camera_password_dialog(self, index: int):
        """Open a friendly dialog for non-tech users to easily update camera password/Safety Code."""
        if index >= len(self._cam_entries):
            return

        entry = self._cam_entries[index]
        current_url = entry.get().strip()

        username, current_pwd, host_path = self._parse_rtsp_url(current_url)

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"🔑 Mật khẩu Camera {index + 1}")
        dialog.geometry("500x380")
        dialog.configure(fg_color=COLORS["bg_primary"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.attributes("-topmost", True)

        ctk.CTkLabel(
            dialog, text=f"🔑 Mật khẩu Camera {index + 1}",
            font=FONTS["heading"], text_color=COLORS["text_primary"]
        ).pack(padx=PADDING["lg"], pady=(PADDING["lg"], 4))

        ctk.CTkLabel(
            dialog,
            text="Nhập mã an toàn (Safety Code dưới đáy camera) hoặc mật khẩu.\n"
                 "Hệ thống sẽ tự động cập nhật trực tiếp vào thanh RTSP URL cho bạn.",
            font=FONTS["small"], text_color=COLORS["text_muted"], justify="center"
        ).pack(padx=PADDING["lg"], pady=(0, PADDING["md"]))

        form = ctk.CTkFrame(dialog, fg_color=COLORS["bg_card"], corner_radius=8)
        form.pack(fill="x", padx=PADDING["lg"], pady=PADDING["xs"])

        # Password row (Safety Code)
        pwd_label_row = ctk.CTkFrame(form, fg_color="transparent")
        pwd_label_row.pack(fill="x", padx=PADDING["md"], pady=(PADDING["md"], 4))
        ctk.CTkLabel(pwd_label_row, text="Mật khẩu / Mã an toàn (Safety Code):", font=FONTS["small_bold"], text_color=COLORS["text_secondary"]).pack(side="left")

        pwd_row = ctk.CTkFrame(form, fg_color="transparent")
        pwd_row.pack(fill="x", padx=PADDING["md"], pady=(0, PADDING["md"]))
        pwd_entry = ctk.CTkEntry(
            pwd_row, font=FONTS["body"],
            placeholder_text="VD: L2!Pj2gY hoặc admin123...",
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            show="*"
        )
        pwd_entry.pack(side="left", fill="x", expand=True, padx=(0, PADDING["xs"]))
        if current_pwd:
            pwd_entry.insert(0, current_pwd)

        show_pwd_var = ctk.BooleanVar(value=False)
        def _toggle_pwd_visibility():
            if show_pwd_var.get():
                pwd_entry.configure(show="")
                toggle_btn.configure(text="🔒")
            else:
                pwd_entry.configure(show="*")
                toggle_btn.configure(text="👁️")

        toggle_btn = ctk.CTkButton(
            pwd_row, text="👁️", width=36, height=32,
            fg_color=COLORS["bg_secondary"], text_color=COLORS["text_primary"],
            command=lambda: [show_pwd_var.set(not show_pwd_var.get()), _toggle_pwd_visibility()]
        )
        toggle_btn.pack(side="right")

        apply_all_var = ctk.BooleanVar(value=False)
        total_cams = len(self._cam_entries)
        if total_cams > 1:
            ctk.CTkCheckBox(
                form, text=f"Áp dụng cho tất cả {total_cams} camera",
                variable=apply_all_var, font=FONTS["small"],
                text_color=COLORS["accent"]
            ).pack(anchor="w", padx=PADDING["md"], pady=(0, PADDING["md"]))

        # Preview box (Masked credentials)
        preview_box = ctk.CTkFrame(dialog, fg_color=COLORS["bg_secondary"], corner_radius=6)
        preview_box.pack(fill="x", padx=PADDING["lg"], pady=PADDING["xs"])
        preview_label = ctk.CTkLabel(
            preview_box,
            text=f"RTSP hiện tại: {self.config.mask_rtsp_url(current_url) if current_url else '(Đang trống)'}",
            font=FONTS["small"], text_color=COLORS["text_muted"], wraplength=440, justify="left"
        )
        preview_label.pack(padx=PADDING["sm"], pady=PADDING["xs"])

        def apply_password():
            new_user = username or "admin"
            new_pwd = pwd_entry.get().strip()

            target_indices = range(len(self._cam_entries)) if apply_all_var.get() else [index]

            for idx in target_indices:
                ent = self._cam_entries[idx]
                url_to_update = ent.get().strip()
                updated_url = self._update_rtsp_password(url_to_update, new_pwd, new_user, default_channel=idx + 1)
                ent.delete(0, "end")
                ent.insert(0, updated_url)

            # Auto save to config
            all_urls = [e.get().strip() for e in self._cam_entries]
            self.config.set_station_cameras(all_urls, 1)

            if hasattr(self, "_setup_status") and self._setup_status.winfo_exists():
                msg = "✅ Đã lưu mật khẩu cho TẤT CẢ camera!" if apply_all_var.get() else f"✅ Đã lưu mật khẩu cho Camera {index + 1}!"
                self._setup_status.configure(text=msg, text_color=COLORS["success"])

            dialog.destroy()

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=PADDING["lg"], pady=PADDING["md"])

        ctk.CTkButton(
            btn_row, text="Hủy", font=FONTS["body"],
            fg_color="transparent", border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"], width=90, height=36,
            command=dialog.destroy
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="✅ Lưu mật khẩu", font=FONTS["body_bold"],
            fg_color="#16a34a", hover_color="#15803d", height=36,
            command=apply_password
        ).pack(side="right", fill="x", expand=True, padx=(PADDING["sm"], 0))

    def _add_camera_row(self, url=""):
        """Add a new camera entry row."""
        current_urls = [e.get().strip() for e in self._cam_entries]
        current_urls.append(url)
        self._render_camera_rows(current_urls)

    def _remove_camera_row(self, index: int):
        """Remove a camera entry row by index."""
        current_urls = [e.get().strip() for e in self._cam_entries]
        if 0 <= index < len(current_urls):
            current_urls.pop(index)
        self._render_camera_rows(current_urls)

    def set_camera_url(self, index: int, url: str):
        """Helper to set camera URL at index, expanding rows if needed."""
        current_urls = [e.get().strip() for e in self._cam_entries] if self._cam_entries else self.config.get_station_cameras(1)
        while len(current_urls) <= index:
            current_urls.append("")
        current_urls[index] = url.strip()
        if hasattr(self, "_cam_rows_frame") and self._cam_rows_frame.winfo_exists():
            self._render_camera_rows(current_urls)
        self.config.set_station_cameras(current_urls, 1)

        # Invalidate cached camera page so it reflects new camera configuration
        if "camera" in self._page_frames:
            if self._page_frames["camera"].winfo_exists():
                self._page_frames["camera"].destroy()
            self._page_frames.pop("camera", None)

    def _choose_video_dir(self):
        from tkinter import filedialog
        path = filedialog.askdirectory()
        if path:
            self._video_dir_entry.delete(0, "end")
            self._video_dir_entry.insert(0, path)

    def _save_settings(self):
        urls = [e.get().strip() for e in self._cam_entries]
        self.config.set_station_cameras(urls, 1)

        self.config.set("video_dir", self._video_dir_entry.get().strip())
        self.config.set("auto_record", self._auto_record_var.get())

        # Save max recording duration (minutes)
        if hasattr(self, "_max_record_entry"):
            try:
                max_rec = int(self._max_record_entry.get().strip())
                max_rec = max(0, max_rec)
            except (ValueError, TypeError):
                max_rec = 10
            self._max_record_entry.delete(0, "end")
            self._max_record_entry.insert(0, str(max_rec))
            self.config.set("max_record_duration_minutes", max_rec)

        # Save video retention days (minimum 7 days)
        if hasattr(self, "_retention_entry"):
            try:
                ret_days = int(self._retention_entry.get().strip())
                ret_days = max(7, ret_days)
            except (ValueError, TypeError):
                ret_days = 30
            self._retention_entry.delete(0, "end")
            self._retention_entry.insert(0, str(ret_days))
            self.config.set("video_retention_days", ret_days)

            # Trigger video cleanup immediately in background with new retention limit
            threading.Thread(target=lambda: self.recorder.cleanup_old_videos(ret_days), daemon=True).start()

        self.config.set("sound_enabled", self._sound_var.get())
        self.config.set("auto_scan_enabled", self._auto_scan_var.get())

        from core.startup_manager import set_startup
        set_startup(self._startup_var.get())
        self.config.set("startup_with_windows", self._startup_var.get())

        self.config.save()
        self.audio.enabled = self._sound_var.get()

        # Invalidate cached camera page so it reflects new camera streams
        if "camera" in self._page_frames:
            if self._page_frames["camera"].winfo_exists():
                self._page_frames["camera"].destroy()
            self._page_frames.pop("camera", None)

        # Reinit cameras with new settings
        self._init_cameras()

        self._on_log(self._t("settings.saved"), 0)

    # ═══════════════════════════════════════════
    # QR CAMERA SCAN DIALOG
    # ═══════════════════════════════════════════
    def _open_qr_scan_dialog(self):
        """Open dialog to scan QR code from camera body."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("📱 Quét QR Camera")
        dialog.geometry("520x620")
        dialog.configure(fg_color=COLORS["bg_primary"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.attributes("-topmost", True)

        # Header
        ctk.CTkLabel(
            dialog, text="📱 Quét mã QR trên thân camera",
            font=FONTS["heading"], text_color=COLORS["text_primary"]
        ).pack(padx=PADDING["lg"], pady=(PADDING["lg"], PADDING["sm"]))

        ctk.CTkLabel(
            dialog, text="Dùng webcam để quét hoặc nhập thông tin thủ công",
            font=FONTS["small"], text_color=COLORS["text_muted"]
        ).pack(padx=PADDING["lg"])

        # Webcam preview for scanning
        cam_frame = ctk.CTkFrame(dialog, fg_color=COLORS["bg_card"], corner_radius=8, height=240)
        cam_frame.pack(fill="x", padx=PADDING["lg"], pady=PADDING["md"])
        cam_frame.pack_propagate(False)

        cam_label = ctk.CTkLabel(cam_frame, text="📷 Đang mở webcam...", font=FONTS["body"], text_color=COLORS["text_muted"])
        cam_label.pack(fill="both", expand=True)

        qr_status = ctk.CTkLabel(dialog, text="", font=FONTS["body_bold"], text_color=COLORS["success"])
        qr_status.pack(padx=PADDING["lg"])

        # Manual input section
        manual_frame = ctk.CTkFrame(dialog, fg_color=COLORS["bg_card"], corner_radius=8)
        manual_frame.pack(fill="x", padx=PADDING["lg"], pady=PADDING["sm"])

        ctk.CTkLabel(manual_frame, text="Thông tin camera:", font=FONTS["body_bold"], text_color=COLORS["accent"]).pack(anchor="w", padx=PADDING["md"], pady=(PADDING["md"], PADDING["xs"]))

        fields = ctk.CTkFrame(manual_frame, fg_color="transparent")
        fields.pack(fill="x", padx=PADDING["md"], pady=(0, PADDING["xs"]))

        ctk.CTkLabel(fields, text="IP Camera:", font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(anchor="w")
        ip_entry = ctk.CTkEntry(fields, placeholder_text="192.168.1.108", font=FONTS["body"], fg_color=COLORS["bg_input"], border_color=COLORS["border"])
        ip_entry.pack(fill="x", pady=(0, PADDING["xs"]))

        ctk.CTkLabel(fields, text="Mật khẩu (SC / Safety Code):", font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(anchor="w")
        pwd_entry = ctk.CTkEntry(fields, placeholder_text="admin hoặc mật khẩu camera", font=FONTS["body"], fg_color=COLORS["bg_input"], border_color=COLORS["border"])
        pwd_entry.pack(fill="x", pady=(0, PADDING["xs"]))

        # Target camera selector & Dual-lens option
        t_row = ctk.CTkFrame(fields, fg_color="transparent")
        t_row.pack(fill="x", pady=(PADDING["xs"], 0))
        ctk.CTkLabel(t_row, text="Gán vào:", font=FONTS["small_bold"], text_color=COLORS["text_primary"]).pack(side="left")

        current_cam_count = max(len(self._cam_entries), 1)
        target_options = [f"Cam {i+1}" for i in range(current_cam_count)] + ["➕ Thêm camera mới"]
        target_cam_menu = ctk.CTkOptionMenu(t_row, values=target_options, font=FONTS["small_bold"], width=150)
        target_cam_menu.set(target_options[0])
        target_cam_menu.pack(side="right")

        dual_lens_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            fields, text="Camera 2 mắt (Gán cả Cam này + Cam tiếp theo)",
            variable=dual_lens_var, font=FONTS["small"], text_color=COLORS["text_secondary"]
        ).pack(anchor="w", pady=(PADDING["xs"], PADDING["xs"]))

        # Buttons
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=PADDING["lg"], pady=PADDING["md"])

        def _get_target_idx():
            choice = target_cam_menu.get()
            if choice == "➕ Thêm camera mới":
                return len(self._cam_entries)
            try:
                return int(choice.replace("Cam ", "")) - 1
            except ValueError:
                return 0

        def apply_camera():
            from core.camera_discovery import CameraInfo
            ip = ip_entry.get().strip()
            pwd = pwd_entry.get().strip()
            if not ip:
                qr_status.configure(text="⚠️ Nhập IP camera!", text_color=COLORS["warning"])
                return
            cam = CameraInfo(ip=ip, password=pwd, username="admin")
            rtsp1 = cam.build_rtsp_url(channel=1, subtype=0)
            rtsp2 = cam.build_rtsp_url(channel=2, subtype=0)
            idx = _get_target_idx()

            if dual_lens_var.get():
                self.set_camera_url(idx, rtsp1)
                self.set_camera_url(idx + 1, rtsp2)
                qr_status.configure(text=f"✅ Đã gán {ip} vào Cam {idx+1} và Cam {idx+2}", text_color=COLORS["success"])
            else:
                self.set_camera_url(idx, rtsp1)
                qr_status.configure(text=f"✅ Đã gán {ip} vào Cam {idx+1}", text_color=COLORS["success"])
            stop_scan()

        def sync_imou():
            ip = ip_entry.get().strip()
            pwd = pwd_entry.get().strip()
            if not ip or not pwd:
                qr_status.configure(text="⚠️ Cần nhập cả IP và Mật khẩu!", text_color=COLORS["warning"])
                return
            qr_status.configure(text="⏳ Đang bắt tay cổng 37777 (NetSDK)...", text_color=COLORS["warning"])

            def worker():
                from core.dahua_sdk import DahuaNetSDK
                sdk = DahuaNetSDK()
                res = sdk.test_and_configure_camera(ip, pwd)
                if res["success"]:
                    idx = _get_target_idx()
                    if dual_lens_var.get():
                        self.set_camera_url(idx, res["rtsp_url_ch1"])
                        self.set_camera_url(idx + 1, res["rtsp_url_ch2"])
                        msg = f"Đã gán vào Cam {idx+1} và Cam {idx+2}"
                    else:
                        self.set_camera_url(idx, res["rtsp_url_ch1"])
                        msg = f"Đã gán vào Cam {idx+1}"
                    dialog.after(0, lambda: (
                        qr_status.configure(text=f"✅ {res['message']} ({msg})", text_color=COLORS["success"]),
                        stop_scan()
                    ))
                else:
                    dialog.after(0, lambda: qr_status.configure(text=f"{res['message']}", text_color=COLORS["error"]))

            threading.Thread(target=worker, daemon=True).start()

        ctk.CTkButton(
            btn_frame, text="⚡ Kích hoạt Imou", font=FONTS["body_bold"],
            height=40, fg_color="#ea580c", hover_color="#c2410c",
            command=sync_imou
        ).pack(side="left", fill="x", expand=True, padx=(0, PADDING["xs"]))

        ctk.CTkButton(
            btn_frame, text="✅ Áp dụng", font=FONTS["body_bold"],
            height=40, fg_color=COLORS["success"], hover_color="#16a34a",
            command=apply_camera
        ).pack(side="left", fill="x", expand=True, padx=(0, PADDING["xs"]))

        ctk.CTkButton(
            btn_frame, text="Đóng", font=FONTS["body"],
            height=40, fg_color=COLORS["border"], hover_color=COLORS["border_light"],
            command=lambda: (stop_scan(), dialog.destroy())
        ).pack(side="right", fill="x", expand=True, padx=(PADDING["xs"], 0))


        # Webcam QR scanning loop
        scanning = {"active": True, "cap": None}

        def start_scan():
            try:
                cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                scanning["cap"] = cap
                if not cap.isOpened():
                    cam_label.configure(text="❌ Không tìm thấy webcam\nNhập IP thủ công bên dưới")
                    return
                scan_frame()
            except Exception as e:
                cam_label.configure(text=f"❌ Lỗi webcam: {e}")

        def scan_frame():
            if not scanning["active"] or not scanning["cap"]:
                return
            cap = scanning["cap"]
            ret, frame = cap.read()
            if ret and frame is not None:
                # Show preview
                try:
                    h, w = frame.shape[:2]
                    scale = min(480 / w, 220 / h)
                    nw, nh = int(w * scale), int(h * scale)
                    resized = cv2.resize(frame, (nw, nh))
                    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(rgb)
                    photo = ctk.CTkImage(light_image=img, dark_image=img, size=(nw, nh))
                    cam_label.configure(image=photo, text="")
                    cam_label._qr_photo = photo
                except Exception:
                    pass

                # Try decode QR (pyzbar + OpenCV dual engine)
                qr_text = ""
                try:
                    from pyzbar.pyzbar import decode as pyzbar_decode
                    decoded = pyzbar_decode(frame)
                    if decoded:
                        qr_text = decoded[0].data.decode("utf-8", errors="replace").strip()
                except Exception:
                    pass

                if not qr_text:
                    try:
                        detector = cv2.QRCodeDetector()
                        val, pts, _ = detector.detectAndDecode(frame)
                        if val and val.strip():
                            qr_text = val.strip()
                    except Exception:
                        pass

                if qr_text:
                    from core.camera_discovery import parse_camera_qr
                    cam_info = parse_camera_qr(qr_text)
                    qr_status.configure(text=f"✅ QR: {qr_text[:60]}", text_color=COLORS["success"])
                    if cam_info.ip:
                        ip_entry.delete(0, "end")
                        ip_entry.insert(0, cam_info.ip)
                    if cam_info.password:
                        pwd_entry.delete(0, "end")
                        pwd_entry.insert(0, cam_info.password)
                    if cam_info.serial:
                        qr_status.configure(text=f"✅ Camera: {cam_info.brand} SN:{cam_info.serial}", text_color=COLORS["success"])
                    if cam_info.rtsp_url:
                        idx = _get_target_idx()
                        self.set_camera_url(idx, cam_info.rtsp_url)
                        qr_status.configure(text=f"✅ Đã gán RTSP vào Cam {idx+1}!", text_color=COLORS["success"])

            if scanning["active"]:
                dialog.after(100, scan_frame)

        def stop_scan():
            scanning["active"] = False
            if scanning["cap"]:
                scanning["cap"].release()
                scanning["cap"] = None

        dialog.protocol("WM_DELETE_WINDOW", lambda: (stop_scan(), dialog.destroy()))
        dialog.after(500, start_scan)

    # ═══════════════════════════════════════════
    # NETWORK CAMERA DISCOVERY DIALOG
    # ═══════════════════════════════════════════
    def _open_network_scan_dialog(self):
        """Open dialog to discover cameras on the local network."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("🔍 Dò Camera trên mạng")
        dialog.geometry("550x500")
        dialog.configure(fg_color=COLORS["bg_primary"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.attributes("-topmost", True)

        ctk.CTkLabel(
            dialog, text="🔍 Tìm Camera trên mạng LAN",
            font=FONTS["heading"], text_color=COLORS["text_primary"]
        ).pack(padx=PADDING["lg"], pady=(PADDING["lg"], PADDING["sm"]))

        status_label = ctk.CTkLabel(
            dialog, text="Nhấn 'Bắt đầu dò' để quét mạng...",
            font=FONTS["body"], text_color=COLORS["text_muted"]
        )
        status_label.pack(padx=PADDING["lg"])

        # Results list
        results_frame = ctk.CTkScrollableFrame(dialog, fg_color=COLORS["bg_card"], corner_radius=8, height=280)
        results_frame.pack(fill="both", expand=True, padx=PADDING["lg"], pady=PADDING["md"])

        # Password & Target Frame
        ctrl_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        ctrl_frame.pack(fill="x", padx=PADDING["lg"], pady=(0, PADDING["xs"]))

        ctk.CTkLabel(ctrl_frame, text="Mật khẩu:", font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(side="left")
        net_pwd_entry = ctk.CTkEntry(ctrl_frame, placeholder_text="admin", font=FONTS["body"], width=110, fg_color=COLORS["bg_input"], border_color=COLORS["border"])
        net_pwd_entry.pack(side="left", padx=(PADDING["xs"], PADDING["sm"]))

        ctk.CTkLabel(ctrl_frame, text="Gán vào:", font=FONTS["small_bold"], text_color=COLORS["text_secondary"]).pack(side="left")
        current_cam_count = max(len(self._cam_entries), 1)
        target_options = [f"Cam {i+1}" for i in range(current_cam_count)] + ["➕ Thêm camera mới"]
        target_cam_menu = ctk.CTkOptionMenu(ctrl_frame, values=target_options, font=FONTS["small_bold"], width=120)
        target_cam_menu.set(target_options[0])
        target_cam_menu.pack(side="left", padx=(PADDING["xs"], PADDING["sm"]))

        dual_lens_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            ctrl_frame, text="Cam 2 mắt", variable=dual_lens_var,
            font=FONTS["small"], text_color=COLORS["text_secondary"]
        ).pack(side="left")

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=PADDING["lg"], pady=PADDING["md"])

        def start_discovery():
            for w in results_frame.winfo_children():
                w.destroy()
            status_label.configure(text="⏳ Đang quét mạng... (5-10 giây)", text_color=COLORS["warning"])
            scan_btn.configure(state="disabled")

            def scan_thread():
                from core.camera_discovery import scan_network_cameras, CameraInfo
                found = []

                def on_found(cam: CameraInfo):
                    found.append(cam)
                    dialog.after(0, lambda c=cam: add_result_row(c))

                cameras = scan_network_cameras(timeout=5.0, on_found=on_found)
                dialog.after(0, lambda: status_label.configure(
                    text=f"✅ Tìm thấy {len(cameras)} camera" if cameras else "❌ Không tìm thấy camera nào",
                    text_color=COLORS["success"] if cameras else COLORS["error"]
                ))
                dialog.after(0, lambda: scan_btn.configure(state="normal"))

            threading.Thread(target=scan_thread, daemon=True).start()

        def add_result_row(cam):
            from core.camera_discovery import CameraInfo
            row = ctk.CTkFrame(results_frame, fg_color=COLORS["bg_secondary"], corner_radius=6)
            row.pack(fill="x", pady=PADDING["xs"])

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(fill="x", padx=PADDING["sm"], pady=PADDING["sm"])

            brand_text = f"  ({cam.brand})" if cam.brand else ""
            ctk.CTkLabel(info, text=f"📷 {cam.ip}{brand_text}", font=FONTS["body_bold"], text_color=COLORS["text_primary"]).pack(side="left")

            def use_camera():
                pwd = net_pwd_entry.get().strip() or "admin"
                cam.password = pwd
                rtsp1 = cam.build_rtsp_url(channel=1, subtype=0)
                rtsp2 = cam.build_rtsp_url(channel=2, subtype=0)

                choice = target_cam_menu.get()
                if choice == "➕ Thêm camera mới":
                    idx = len(self._cam_entries)
                else:
                    try:
                        idx = int(choice.replace("Cam ", "")) - 1
                    except ValueError:
                        idx = 0

                if dual_lens_var.get():
                    self.set_camera_url(idx, rtsp1)
                    self.set_camera_url(idx + 1, rtsp2)
                    status_label.configure(text=f"✅ Đã gán {cam.ip} vào Cam {idx+1} và Cam {idx+2}", text_color=COLORS["success"])
                else:
                    self.set_camera_url(idx, rtsp1)
                    status_label.configure(text=f"✅ Đã gán {cam.ip} vào Cam {idx+1}", text_color=COLORS["success"])

            ctk.CTkButton(
                info, text="Chọn", font=FONTS["small_bold"],
                width=70, height=30, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                command=use_camera
            ).pack(side="right")

        scan_btn = ctk.CTkButton(
            btn_frame, text="🔍 Bắt đầu dò", font=FONTS["body_bold"],
            height=40, fg_color="#0891b2", hover_color="#0e7490",
            command=start_discovery
        )
        scan_btn.pack(side="left", fill="x", expand=True, padx=(0, PADDING["xs"]))

        ctk.CTkButton(
            btn_frame, text="Đóng", font=FONTS["body"],
            height=40, fg_color=COLORS["border"], hover_color=COLORS["border_light"],
            command=dialog.destroy
        ).pack(side="right", fill="x", expand=True, padx=(PADDING["xs"], 0))

    # ═══════════════════════════════════════════
    # DAHUA / IMOU DIRECT NETSDK DIALOG
    # ═══════════════════════════════════════════
    def _open_imou_sync_dialog(self):
        """Direct connection & optimization for Dahua/Imou cameras via port 37777."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("⚡ Kết nối Dahua / Imou (Cổng 37777)")
        dialog.geometry("520x460")
        dialog.configure(fg_color=COLORS["bg_primary"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.attributes("-topmost", True)

        ctk.CTkLabel(
            dialog, text="⚡ Kết nối trực tiếp Dahua / Imou",
            font=FONTS["heading"], text_color=COLORS["text_primary"]
        ).pack(padx=PADDING["lg"], pady=(PADDING["lg"], PADDING["xs"]))

        ctk.CTkLabel(
            dialog, text="Giao thức Dahua độc quyền (cổng 37777) - Không cần bật trước ONVIF/RTSP",
            font=FONTS["small"], text_color=COLORS["text_muted"]
        ).pack(padx=PADDING["lg"], pady=(0, PADDING["md"]))

        form_frame = ctk.CTkFrame(dialog, fg_color=COLORS["bg_card"], corner_radius=8)
        form_frame.pack(fill="x", padx=PADDING["lg"], pady=PADDING["sm"])

        ctk.CTkLabel(form_frame, text="IP Camera trong mạng LAN:", font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(anchor="w", padx=PADDING["md"], pady=(PADDING["md"], 0))
        ip_entry = ctk.CTkEntry(form_frame, placeholder_text="192.168.1.108", font=FONTS["body"], fg_color=COLORS["bg_input"], border_color=COLORS["border"])
        ip_entry.pack(fill="x", padx=PADDING["md"], pady=(PADDING["xs"], PADDING["sm"]))

        ctk.CTkLabel(form_frame, text="Mật khẩu Camera (Mật khẩu Imou Life hoặc Safety Code):", font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(anchor="w", padx=PADDING["md"], pady=(0, 0))
        pwd_entry = ctk.CTkEntry(form_frame, placeholder_text="Nhập mật khẩu (VD: L2!Pj2gY)...", font=FONTS["body"], fg_color=COLORS["bg_input"], border_color=COLORS["border"])
        pwd_entry.pack(fill="x", padx=PADDING["md"], pady=(PADDING["xs"], PADDING["sm"]))

        target_box = ctk.CTkFrame(form_frame, fg_color="transparent")
        target_box.pack(fill="x", padx=PADDING["md"], pady=(0, PADDING["md"]))

        ctk.CTkLabel(target_box, text="Gán vào:", font=FONTS["small_bold"], text_color=COLORS["text_secondary"]).pack(side="left")
        current_cam_count = max(len(self._cam_entries), 1)
        target_options = [f"Cam {i+1}" for i in range(current_cam_count)] + ["➕ Thêm camera mới"]
        target_cam_menu = ctk.CTkOptionMenu(target_box, values=target_options, font=FONTS["small_bold"], width=130)
        target_cam_menu.set(target_options[0])
        target_cam_menu.pack(side="left", padx=(PADDING["xs"], PADDING["md"]))

        dual_lens_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            target_box, text="Cam 2 mắt", variable=dual_lens_var,
            font=FONTS["small"], text_color=COLORS["text_secondary"]
        ).pack(side="left")

        status_box = ctk.CTkFrame(dialog, fg_color=COLORS["bg_secondary"], corner_radius=6)
        status_box.pack(fill="x", padx=PADDING["lg"], pady=PADDING["sm"])
        status_label = ctk.CTkLabel(
            status_box, text="Sẵn sàng kiểm tra và kích hoạt camera.",
            font=FONTS["small"], text_color=COLORS["text_muted"], wraplength=460
        )
        status_label.pack(padx=PADDING["md"], pady=PADDING["sm"])

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=PADDING["lg"], pady=PADDING["md"])

        def start_sync():
            ip = ip_entry.get().strip()
            pwd = pwd_entry.get().strip()
            if not ip or not pwd:
                status_label.configure(text="⚠️ Vui lòng nhập đầy đủ IP và Mật khẩu camera!", text_color=COLORS["warning"])
                return

            status_label.configure(text="⏳ Đang bắt tay camera qua NetSDK (cổng 37777)...", text_color=COLORS["warning"])
            sync_btn.configure(state="disabled")

            def worker():
                from core.dahua_sdk import DahuaNetSDK
                sdk = DahuaNetSDK()
                res = sdk.test_and_configure_camera(ip, pwd)
                if res["success"]:
                    choice = target_cam_menu.get()
                    if choice == "➕ Thêm camera mới":
                        idx = len(self._cam_entries)
                    else:
                        try:
                            idx = int(choice.replace("Cam ", "")) - 1
                        except ValueError:
                            idx = 0

                    if dual_lens_var.get():
                        self.set_camera_url(idx, res["rtsp_url_ch1"])
                        self.set_camera_url(idx + 1, res["rtsp_url_ch2"])
                        msg = f"Đã gán vào Cam {idx+1} và Cam {idx+2}"
                    else:
                        self.set_camera_url(idx, res["rtsp_url_ch1"])
                        msg = f"Đã gán vào Cam {idx+1}"

                    dialog.after(0, lambda: (
                        status_label.configure(
                            text=f"{res['message']}\n✅ {msg}",
                            text_color=COLORS["success"]
                        ),
                        sync_btn.configure(state="normal", text="✅ Thành công")
                    ))
                else:
                    dialog.after(0, lambda: (
                        status_label.configure(
                            text=f"{res['message']}",
                            text_color=COLORS["error"]
                        ),
                        sync_btn.configure(state="normal", text="⚡ Thử lại")
                    ))

            threading.Thread(target=worker, daemon=True).start()

        sync_btn = ctk.CTkButton(
            btn_frame, text="⚡ Kết nối & Kích hoạt", font=FONTS["body_bold"],
            height=40, fg_color="#ea580c", hover_color="#c2410c",
            command=start_sync
        )
        sync_btn.pack(side="left", fill="x", expand=True, padx=(0, PADDING["xs"]))

        ctk.CTkButton(
            btn_frame, text="Đóng", font=FONTS["body"],
            height=40, fg_color=COLORS["border"], hover_color=COLORS["border_light"],
            command=dialog.destroy
        ).pack(side="right", fill="x", expand=True, padx=(PADDING["xs"], 0))

    # ═══════════════════════════════════════════
    # CAMERA SYSTEM
    # ═══════════════════════════════════════════

    def _init_cameras(self):
        """Initialize camera streams from config."""
        self.camera_mgr.stop_all()
        cams = self.config.get_station_cameras(1)
        for idx, src in enumerate(cams):
            src_str = str(src).strip()
            if src_str:
                source = int(src_str) if src_str.isdigit() else src_str
                self.camera_mgr.add_camera(
                    f"cam{idx+1}", source, f"Cam {idx+1}",
                    on_frame=lambda frame, _label, channel=idx+1: self._record_camera_frame(frame, channel),
                )

        self.camera_mgr.start_all()

    def _record_camera_frame(self, frame, channel: int):
        """Queue camera frames for recording independently of UI rendering."""
        try:
            active = self.order_mgr.get_active_order(1)
            if active:
                self.recorder.write_frame(active["order_sn"], frame, channel)
        except Exception as exc:
            log.error(f"[Video] Could not queue Cam {channel} frame: {exc}")

    def _start_update_loop(self):
        """Periodic UI update for camera frames — adaptive FPS for weak machines."""
        t0 = time.perf_counter()
        self._update_cameras()
        render_ms = (time.perf_counter() - t0) * 1000

        # Intelligent adaptive interval for weak factory machines:
        # If user is NOT on camera page AND no recording is active -> slow down to 350ms (saves 90% CPU!)
        is_rec = any(self.recorder._recording.values()) if hasattr(self, "recorder") else False
        if self._current_page != "camera" and not is_rec:
            interval = 350
        elif render_ms > 80:
            interval = 200  # 5 FPS — machine is struggling, reduce load
        else:
            interval = 100  # 10 FPS — smooth enough for monitoring
        self._update_timer = self.after(interval, self._start_update_loop)

    def _start_status_loop(self):
        """Slower status bar update (every 1s) and timeout auto-stop monitor."""
        self._update_status_bar()
        self.order_mgr.check_timeouts()

        # Periodic memory cleanup every 5 minutes (300 cycles) for 24/7 factory shifts
        self._status_cycle_count = getattr(self, "_status_cycle_count", 0) + 1
        if self._status_cycle_count % 300 == 0:
            import gc
            gc.collect()

        if self._current_page == "camera":
            focused = self.focus_get()
            if not isinstance(focused, ctk.CTkEntry) and hasattr(self, "_scan_entry") and self._scan_entry.winfo_exists():
                try:
                    self._scan_entry.focus_set()
                except Exception:
                    pass
        self._status_timer = self.after(1000, self._start_status_loop)

    def _update_cameras(self):
        """Update camera frame displays and feed background pipelines."""
        for key, cam_thread in list(self.camera_mgr.streams.items()):
            frame, frame_id = cam_thread.get_frame_with_id()
            if frame is not None:
                # Downstream pipelines only need processing when a fresh new frame arrived
                if frame_id != self._last_processed_frame_id.get(key, -1):
                    self._last_processed_frame_id[key] = frame_id

                    # 1. Background Barcode Scanner (always active from Cam 1)
                    if key == "cam1":
                        self.barcode_scanner.set_frame(frame)

            # Only perform expensive UI resizing & image rendering when viewing camera page
            if self._current_page != "camera":
                continue

            label = self._cam_labels.get(key)
            badge = self._cam_badges.get(key)
            if not label or not badge:
                continue

            if frame is not None:
                # 0ms duplicate frame skip: if this frame was already drawn to UI, skip 100% of CV calculations
                if frame_id == self._last_rendered_frame_id.get(key, -1):
                    continue
                self._last_rendered_frame_id[key] = frame_id

                try:
                    display_width = max(160, label.winfo_width() - 10)
                    display_height = max(120, label.winfo_height() - 10)
                    h, w = frame.shape[:2]
                    scale = min(display_width / w, display_height / h)
                    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))

                    # Skip CTkImage recreation if dimensions barely changed (< 5px)
                    last_size = self._camera_images.get(f"{key}_size", (0, 0))
                    if abs(new_w - last_size[0]) < 5 and abs(new_h - last_size[1]) < 5 and f"{key}_size" in self._camera_images:
                        new_w, new_h = last_size

                    if new_w > 0 and new_h > 0:
                        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
                        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(rgb)
                        photo = ctk.CTkImage(light_image=img, dark_image=img, size=(new_w, new_h))
                        label.configure(image=photo, text="")
                        self._camera_images[key] = photo
                        self._camera_images[f"{key}_size"] = (new_w, new_h)

                        # Update badge color ONLY when status transitions
                        if self._cam_badge_state.get(key) != "connected":
                            badge.configure(text_color=COLORS["success"])
                            self._cam_badge_state[key] = "connected"
                except Exception:
                    pass
            else:
                if not self.camera_mgr.is_connected(key):
                    if self._cam_badge_state.get(key) != "disconnected":
                        badge.configure(text_color=COLORS["text_muted"])
                        self._cam_badge_state[key] = "disconnected"

    def _update_status_bar(self):
        """Update the status bar with current info."""
        total_cams = len(self.camera_mgr.streams)
        connected_cams = [k for k in self.camera_mgr.streams if self.camera_mgr.is_connected(k)]
        count = self.db.get_today_count()

        if total_cams == 0:
            cam_status = self._t("status.camera_off")
            cam_color = COLORS["text_muted"]
        elif len(connected_cams) > 0:
            cam_status = f"Đã kết nối {len(connected_cams)}/{total_cams} Cam"
            cam_color = COLORS["success"]
        else:
            cam_status = self._t("status.camera_off")
            cam_color = COLORS["text_muted"]

        status_text = f"📷 {cam_status}"
        if self._last_status_cache.get("status_bar") != (status_text, cam_color):
            self._status_label.configure(text=status_text, text_color=cam_color)
            self._last_status_cache["status_bar"] = (status_text, cam_color)

        orders_text = self._t("status.orders_today", count=count)
        disk_free = self.recorder.get_disk_free_gb() if hasattr(self, "recorder") else 999.0
        if disk_free < 2.0:
            disk_str = f"  |  ⚠️ Ổ đĩa: Còn {disk_free:.1f} GB"
        else:
            disk_str = f"  |  💾 Ổ đĩa trống: {disk_free:.1f} GB"
        full_orders_text = f"{orders_text}{disk_str}"

        if self._last_status_cache.get("orders_today") != full_orders_text:
            self._order_count_label.configure(text=full_orders_text)
            self._last_status_cache["orders_today"] = full_orders_text

        # Update recording indicator on camera page
        if hasattr(self, "_record_indicator") and self._record_indicator.winfo_exists():
            active = self.order_mgr.get_active_order(1)
            is_finishing = self.order_mgr.is_finishing(1)
            if is_finishing and active:
                rec_text = "⏳ Quay thêm 8s..."
                rec_color = COLORS["warning"]
                order_text = f"{active['order_sn']} (⏳ hoàn tất trong 8s)"
                st_text = "⏳ Quay thêm 8s..."
                st_color = COLORS["warning"]
            elif active:
                rec_text = self._t("scan.recording")
                rec_color = COLORS["recording"]
                order_text = active["order_sn"]
                st_text = self._t("scan.recording")
                st_color = COLORS["recording"]
                for ch in active.get("channels", [1]):
                    health = self.recorder.get_recording_health(active["order_sn"], ch)
                    if not self.camera_mgr.is_connected(f"cam{ch}"):
                        warning = f"Cam {ch} mất kết nối"
                    elif health.get("error"):
                        warning = f"Cam {ch}: {health['error']}"
                    elif health.get("dropped", 0):
                        warning = f"Cam {ch} mất {health['dropped']} khung hình"
                    elif health.get("written", 0) == 0 and time.time() - active.get("start_timestamp", time.time()) > 3:
                        warning = f"Cam {ch} chưa ghi được khung hình"
                    else:
                        continue
                    rec_text = st_text = f"⚠️ {warning}"
                    rec_color = st_color = COLORS["warning"]
                    break
            else:
                rec_text = self._t("scan.idle")
                rec_color = COLORS["text_muted"]
                order_text = ""
                st_text = self._t("scan.idle")
                st_color = COLORS["text_muted"]

            if self._last_status_cache.get("rec_state") != (rec_text, rec_color, order_text, st_text, st_color):
                self._record_indicator.configure(text=rec_text, text_color=rec_color)
                if hasattr(self, "_current_order_label") and self._current_order_label.winfo_exists():
                    self._current_order_label.configure(text=order_text)
                if hasattr(self, "_station_status") and self._station_status.winfo_exists():
                    self._station_status.configure(text=st_text, text_color=st_color)
                self._last_status_cache["rec_state"] = (rec_text, rec_color, order_text, st_text, st_color)

        if hasattr(self, "_today_count_label") and self._today_count_label.winfo_exists():
            self._today_count_label.configure(text=self._t("history.total", count=count))

    # ═══════════════════════════════════════════
    # EVENT HANDLERS
    # ═══════════════════════════════════════════
    def _refocus_scan_entry(self):
        if self._current_page == "camera" and hasattr(self, "_scan_entry") and self._scan_entry.winfo_exists():
            try:
                self._scan_entry.focus_set()
            except Exception:
                pass

    def _on_global_key(self, event):
        """Global key interceptor so barcode scanners work even if click focus was elsewhere."""
        if event.keysym in ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"):
            return

        focused = self.focus_get()
        if focused and isinstance(focused, ctk.CTkEntry) and focused != getattr(self, "_scan_entry", None):
            return

        if self._current_page != "camera":
            return

        if event.keysym in ("Return", "KP_Enter"):
            self._on_manual_scan()
            return

        if event.char and event.char.isprintable() and hasattr(self, "_scan_entry") and self._scan_entry.winfo_exists():
            if focused != self._scan_entry:
                self._scan_entry.focus_set()
                self._scan_entry.insert("end", event.char)

    def _on_manual_scan(self, event=None):
        """Handle manual barcode entry asynchronously without UI blocking."""
        code = self._scan_entry.get().strip()
        if code:
            self._scan_entry.delete(0, "end")
            threading.Thread(
                target=self.order_mgr.process_scan,
                args=(code, 1, "MANUAL"),
                daemon=True,
                name="ManualScanWorker"
            ).start()

    def _on_barcode_detected(self, code: str, code_type: str):
        """Called when auto-scan detects a barcode from camera."""
        threading.Thread(
            target=self.order_mgr.process_scan,
            args=(code, 1, code_type),
            daemon=True,
            name="AutoScanWorker"
        ).start()

    def _safe_dispatch(self, fn):
        """Safely dispatch callable to main UI thread from any background thread."""
        if hasattr(self, "_ui_queue"):
            self._ui_queue.put(fn)
        else:
            try:
                fn()
            except Exception:
                pass

    def _process_ui_queue(self):
        """Process callbacks dispatched from background threads without Tcl cross-thread errors."""
        has_work = False
        try:
            while hasattr(self, "_ui_queue") and not self._ui_queue.empty():
                fn = self._ui_queue.get_nowait()
                has_work = True
                try:
                    fn()
                except Exception as e:
                    log.error(f"[UI] Callback error: {e}")
        except Exception:
            pass
        # Adaptive polling: fast (25ms) when active, slow (120ms) when idle to preserve CPU on weak machines
        interval = 25 if has_work else 120
        self._ui_queue_timer = self.after(interval, self._process_ui_queue)

    def _on_order_started(self, order_sn: str, scanner_id: int, order_id: int):
        def _ui():
            self._update_status_bar()
            self._refocus_scan_entry()
            if hasattr(self, "_dup_frame") and self._dup_frame.winfo_exists():
                self._dup_frame.pack_forget()
            if self._current_page == "orders" and hasattr(self, "_refresh_orders_list"):
                self._refresh_orders_list()
        self._safe_dispatch(_ui)

    def _on_order_finishing(self, order_sn: str, scanner_id: int, delay_seconds: float):
        def _ui():
            self._update_status_bar()
        self._safe_dispatch(_ui)

    def _on_order_ended(self, order_sn: str, scanner_id: int, status: str):
        def _ui():
            self._update_status_bar()
            self._refocus_scan_entry()
            if self._current_page == "orders" and hasattr(self, "_refresh_orders_list"):
                self._refresh_orders_list()
        self._safe_dispatch(_ui)

    def _on_video_checked(self, order_id: int):
        def _ui():
            selected = getattr(self, "_selected_order", None)
            if selected and selected.get("id") == order_id and self._current_page == "orders":
                self._select_order(selected)
            if self._current_page == "orders" and hasattr(self, "_refresh_orders_list"):
                self._refresh_orders_list()
        self._safe_dispatch(_ui)

    def _on_duplicate(self, order_sn: str, scanner_id: int):
        """Display duplicate order alert banner with immediate re-record action button."""
        def _ui():
            self._last_duplicate_order_sn = order_sn
            if hasattr(self, "_dup_label") and hasattr(self, "_dup_frame"):
                self._dup_label.configure(text=f"⚠️ Đơn trùng: {order_sn} (đã quay trước đó)")
                self._dup_frame.pack(fill="x", pady=(PADDING["xs"], 0))
                if hasattr(self, "_dup_timer") and self._dup_timer:
                    try:
                        self.after_cancel(self._dup_timer)
                    except Exception:
                        pass
                self._dup_timer = self.after(12000, lambda: self._dup_frame.pack_forget() if (hasattr(self, "_dup_frame") and self._dup_frame.winfo_exists()) else None)
        self._safe_dispatch(_ui)

    def _force_record_duplicate_order(self):
        """Force re-record the last duplicate order (bypasses cooldown and saves to _Lan2)."""
        if hasattr(self, "_last_duplicate_order_sn") and self._last_duplicate_order_sn:
            sn = self._last_duplicate_order_sn
            self._last_duplicate_order_sn = None
            if hasattr(self, "_dup_frame") and self._dup_frame.winfo_exists():
                self._dup_frame.pack_forget()
            threading.Thread(
                target=self.order_mgr.force_start_order,
                args=(sn, 1),
                daemon=True,
                name="ForceRecordWorker"
            ).start()

    def _on_log(self, message: str, scanner_id: int):
        """Add message to log display safely from background thread."""
        def _ui_update():
            now = datetime.now().strftime("%H:%M:%S")
            entry = f"[{now}] {message}"
            self._log_messages.insert(0, entry)
            self._log_messages = self._log_messages[:200]  # Keep last 200

            if hasattr(self, "_log_text"):
                try:
                    self._log_text.configure(state="normal")
                    self._log_text.insert("0.0", entry + "\n")
                    self._log_text.configure(state="disabled")
                except Exception:
                    pass
        self._safe_dispatch(_ui_update)

    # ═══════════════════════════════════════════
    # AUTO-UPDATER (GITHUB)
    # ═══════════════════════════════════════════
    def _is_any_order_packing(self) -> bool:
        """Return True if any station has an active or finishing order."""
        if not hasattr(self, "order_mgr") or not self.order_mgr:
            return False
        active = getattr(self.order_mgr, "_active_orders", {})
        finishing = getattr(self.order_mgr, "_finishing_orders", set())
        return bool(active or finishing)

    def _on_check_for_update(self):
        """Check GitHub Releases for a newer version in a background thread."""
        if self._is_any_order_packing():
            self._update_status_label.configure(
                text="⚠️ Đang có đơn hàng ghi hình! Vui lòng hoàn tất đơn trước khi kiểm tra hoặc cập nhật.",
                text_color=COLORS["warning"],
            )
            return

        self._check_update_btn.configure(state="disabled", text="⏳ Đang kiểm tra...")
        self._apply_update_btn.pack_forget()
        self._update_status_label.configure(
            text="🔍 Đang kết nối tới GitHub để kiểm tra phiên bản mới...",
            text_color=COLORS["text_secondary"],
        )

        def _worker():
            from core.updater import check_for_update
            info = check_for_update()

            def _ui():
                self._check_update_btn.configure(state="normal", text="🔄 Kiểm tra cập nhật")
                if info.get("error"):
                    self._update_status_label.configure(
                        text=f"❌ {info['error']}",
                        text_color=COLORS["danger"],
                    )
                    return

                self._pending_update_info = info
                latest_ver = info.get("latest_version", "")
                if info.get("has_update"):
                    notes = (info.get("release_notes") or "").strip()
                    short_notes = notes[:220] + ("..." if len(notes) > 220 else "")
                    msg = f"🎉 Đã có phiên bản mới: {latest_ver}"
                    if short_notes:
                        msg += f"\n📋 Nội dung: {short_notes}"
                    self._update_status_label.configure(
                        text=msg,
                        text_color=COLORS["success"],
                    )
                    self._apply_update_btn.configure(text=f"⬇️ Tải & Cập nhật ({latest_ver})")
                    self._apply_update_btn.pack(side="left")
                else:
                    git_dir = os.path.join(self.config.base_dir, ".git")
                    if not getattr(sys, "frozen", False) and os.path.isdir(git_dir):
                        self._update_status_label.configure(
                            text=f"✅ Bạn đang ở bản Release mới nhất ({latest_ver}). Bạn cũng có thể kéo code mới nhất trực tiếp từ nhánh main (git pull).",
                            text_color=COLORS["success"],
                        )
                        self._apply_update_btn.configure(text="⬇️ Đồng bộ từ Git (git pull)")
                        self._apply_update_btn.pack(side="left")
                    else:
                        self._update_status_label.configure(
                            text=f"✅ Bạn đang sử dụng phiên bản mới nhất ({latest_ver}).",
                            text_color=COLORS["success"],
                        )

            self._safe_dispatch(_ui)

        threading.Thread(target=_worker, daemon=True, name="CheckUpdateWorker").start()

    def _on_apply_update(self):
        """Download and apply the update safely (either via GitHub Release ZIP or git pull)."""
        if self._is_any_order_packing():
            self._update_status_label.configure(
                text="⛔ Không thể cập nhật khi đang quay video đóng gói! Vui lòng kết thúc đơn hàng trước.",
                text_color=COLORS["danger"],
            )
            return

        info = self._pending_update_info or {}
        is_frozen = getattr(sys, "frozen", False)
        git_dir = os.path.join(self.config.base_dir, ".git")

        self._check_update_btn.configure(state="disabled")
        self._apply_update_btn.configure(state="disabled", text="⏳ Đang cập nhật...")
        self._update_progress_bar.pack(fill="x", pady=(0, PADDING["xs"]))
        self._update_progress_bar.set(0.05)

        def _worker():
            from core.updater import (
                create_and_run_updater_script,
                download_and_stage_update,
                update_via_git_pull,
            )

            # Case 1: Running from source with .git and either no new release binary or user clicked git pull
            if not is_frozen and os.path.isdir(git_dir) and not info.get("has_update"):
                res = update_via_git_pull(self.config.base_dir)

                def _ui_git():
                    self._check_update_btn.configure(state="normal")
                    self._apply_update_btn.configure(state="normal", text="⬇️ Đồng bộ từ Git (git pull)")
                    self._update_progress_bar.set(1.0 if res["ok"] else 0)
                    if res["ok"]:
                        out = res.get("output") or "Already up to date."
                        self._update_status_label.configure(
                            text=f"✅ Đã cập nhật từ Git thành công ({out}). Vui lòng khởi động lại ứng dụng để áp dụng thay đổi.",
                            text_color=COLORS["success"],
                        )
                        self._on_log("✅ Cập nhật mã nguồn từ Git thành công!", 0)
                    else:
                        self._update_status_label.configure(
                            text=f"❌ Lỗi git pull: {res['error']}",
                            text_color=COLORS["danger"],
                        )

                self._safe_dispatch(_ui_git)
                return

            # Case 2: Download Release ZIP package and stage update
            download_url = info.get("download_url", "")
            if not download_url:
                def _ui_no_url():
                    self._check_update_btn.configure(state="normal")
                    self._apply_update_btn.configure(state="normal")
                    self._update_status_label.configure(
                        text="❌ Không tìm thấy gói tải về (.zip) trong bản Release này.",
                        text_color=COLORS["danger"],
                    )
                self._safe_dispatch(_ui_no_url)
                return

            def _progress(pct: int, total: int, msg: str):
                def _ui_prog():
                    self._update_progress_bar.set(max(0.0, min(1.0, pct / float(total or 100))))
                    self._update_status_label.configure(text=f"⏳ {msg}", text_color=COLORS["accent"])
                self._safe_dispatch(_ui_prog)

            stage_res = download_and_stage_update(
                download_url=download_url,
                target_dir=self.config.base_dir,
                progress_callback=_progress,
            )

            if not stage_res.get("ok"):
                def _ui_err():
                    self._check_update_btn.configure(state="normal")
                    self._apply_update_btn.configure(state="normal", text="⬇️ Thử cập nhật lại")
                    self._update_status_label.configure(
                        text=f"❌ Lỗi cập nhật: {stage_res.get('error')}",
                        text_color=COLORS["danger"],
                    )
                self._safe_dispatch(_ui_err)
                return

            def _ui_finish_and_restart():
                self._update_status_label.configure(
                    text="✅ Tải hoàn tất! Đang áp dụng bản cập nhật và tự khởi động lại...",
                    text_color=COLORS["success"],
                )
                self._on_log("🚀 Đang khởi động lại để hoàn tất cập nhật...", 0)
                staged_dir = stage_res["staged_dir"]
                self.cleanup()
                create_and_run_updater_script(
                    staged_source_dir=staged_dir,
                    target_dir=self.config.base_dir,
                    exe_name="PackStation.exe",
                    launch_after=True,
                )
                self.destroy()

            self._safe_dispatch(_ui_finish_and_restart)

        threading.Thread(target=_worker, daemon=True, name="ApplyUpdateWorker").start()

    # ═══════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════
    def cleanup(self):
        """Clean shutdown of all systems."""
        # Gracefully finalize any active orders before stopping video recorder and DB
        if hasattr(self, "order_mgr") and self.order_mgr:
            try:
                for scanner_id in list(self.order_mgr._active_orders.keys()):
                    self.order_mgr._end_current_order(scanner_id, "completed")
            except Exception as e:
                log.error(f"[Cleanup] End active order error: {e}")

        if hasattr(self, "_ui_queue_timer") and self._ui_queue_timer:
            try:
                self.after_cancel(self._ui_queue_timer)
            except Exception:
                pass
        if self._update_timer:
            self.after_cancel(self._update_timer)
        if self._status_timer:
            self.after_cancel(self._status_timer)
        self.barcode_scanner.stop()
        self.camera_mgr.stop_all()
        self.recorder.stop_all()
        self.db.close()
        log.info("[App] ✅ Cleanup complete")
