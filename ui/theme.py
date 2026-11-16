"""Theme and styling constants for PackStation UI."""

THEMES = {
    "classic": {
        "label": "Giao diện Cũ (Mặc định)",
        "colors": {
            "bg_primary": "#0f0f1a",
            "bg_secondary": "#1a1a2e",
            "bg_card": "#16213e",
            "bg_input": "#1a1a2e",
            "accent": "#0ea5e9",
            "accent_hover": "#38bdf8",
            "accent_dark": "#0369a1",
            "brand_title": "#f59e0b",
            "success": "#22c55e",
            "success_bg": "#052e16",
            "warning": "#f59e0b",
            "warning_bg": "#422006",
            "error": "#ef4444",
            "error_bg": "#450a0a",
            "danger": "#ef4444",
            "danger_bg": "#450a0a",
            "text_primary": "#e2e8f0",
            "text_secondary": "#94a3b8",
            "text_muted": "#64748b",
            "border": "#334155",
            "border_light": "#475569",
            "recording": "#ef4444",
            "recording_pulse": "#dc2626",
            "sidebar_bg": "#0d1117",
            "sidebar_active": "#1a1a2e",
            "sidebar_hover": "#161b22",
            "banner_bg": "#1e293b",
            "banner_border": "#334155",
            "btn_qr": "#7c3aed",
            "btn_qr_hover": "#6d28d9",
            "btn_scan_net": "#0891b2",
            "btn_scan_net_hover": "#0e7490",
            "btn_imou": "#ea580c",
            "btn_imou_hover": "#c2410c",
            "btn_add": "#0d9488",
            "btn_add_hover": "#0f766e",
            "btn_primary_alt": "#2563eb",
            "btn_primary_alt_hover": "#1d4ed8",
            "btn_folder": "#0284c7",
            "btn_folder_hover": "#0369a1",
            "btn_export": "#059669",
            "btn_export_hover": "#047857",
            "dup_bg": "#451a03",
            "dup_border": "#d97706",
            "dup_text": "#fbbf24",
            "dup_btn": "#d97706",
            "dup_btn_hover": "#b45309",
        },
        "fonts": {
            "title": ("Segoe UI", 20, "bold"),
            "subtitle": ("Segoe UI", 14),
            "heading": ("Segoe UI", 16, "bold"),
            "body": ("Segoe UI", 12),
            "body_bold": ("Segoe UI", 12, "bold"),
            "small": ("Segoe UI", 10),
            "small_bold": ("Segoe UI", 10, "bold"),
            "mono": ("Consolas", 11),
            "mono_bold": ("Consolas", 11, "bold"),
            "mono_large": ("Consolas", 16, "bold"),
            "icon": ("Segoe UI Emoji", 14),
            "icon_large": ("Segoe UI Emoji", 20),
            "status_code": ("Consolas", 24, "bold"),
        },
        "sizes": {
            "sidebar_width": 180,
            "camera_min_height": 280,
            "status_bar_height": 32,
            "border_radius": 8,
            "card_border_width": 0,
        },
    },
    "industrial_carbon": {
        "label": "Giao diện Mới (Obsidian Pro)",
        "colors": {
            "bg_primary": "#090A0B",
            "bg_secondary": "#111315",
            "bg_card": "#16191D",
            "bg_input": "#0D0F11",
            "accent": "#F97316",
            "accent_hover": "#FB923C",
            "accent_dark": "#C2410C",
            "brand_title": "#F97316",
            "success": "#10B981",
            "success_bg": "#052E1F",
            "warning": "#FBBF24",
            "warning_bg": "#3B2506",
            "error": "#F43F5E",
            "error_bg": "#3F0B17",
            "danger": "#F43F5E",
            "danger_bg": "#3F0B17",
            "text_primary": "#F4F4F5",
            "text_secondary": "#A1A1AA",
            "text_muted": "#71717A",
            "border": "#27272A",
            "border_light": "#3F3F46",
            "recording": "#F43F5E",
            "recording_pulse": "#E11D48",
            "sidebar_bg": "#060708",
            "sidebar_active": "#1D2127",
            "sidebar_hover": "#13161A",
            "banner_bg": "#121519",
            "banner_border": "#27272A",
            "btn_qr": "#27272A",
            "btn_qr_hover": "#3F3F46",
            "btn_scan_net": "#27272A",
            "btn_scan_net_hover": "#3F3F46",
            "btn_imou": "#EA580C",
            "btn_imou_hover": "#C2410C",
            "btn_add": "#27272A",
            "btn_add_hover": "#3F3F46",
            "btn_primary_alt": "#27272A",
            "btn_primary_alt_hover": "#3F3F46",
            "btn_folder": "#27272A",
            "btn_folder_hover": "#3F3F46",
            "btn_export": "#10B981",
            "btn_export_hover": "#059669",
            "dup_bg": "#3B2506",
            "dup_border": "#FBBF24",
            "dup_text": "#FDE68A",
            "dup_btn": "#EA580C",
            "dup_btn_hover": "#C2410C",
        },
        "fonts": {
            "title": ("Segoe UI", 20, "bold"),
            "subtitle": ("Segoe UI", 14),
            "heading": ("Segoe UI", 16, "bold"),
            "body": ("Segoe UI", 12),
            "body_bold": ("Segoe UI", 12, "bold"),
            "small": ("Segoe UI", 10),
            "small_bold": ("Segoe UI", 10, "bold"),
            "mono": ("Consolas", 11),
            "mono_bold": ("Consolas", 11, "bold"),
            "mono_large": ("Consolas", 16, "bold"),
            "icon": ("Segoe UI Emoji", 14),
            "icon_large": ("Segoe UI Emoji", 20),
            "status_code": ("Consolas", 24, "bold"),
        },
        "sizes": {
            "sidebar_width": 180,
            "camera_min_height": 280,
            "status_bar_height": 32,
            "border_radius": 2,
            "card_border_width": 1,
        },
    },
}

COLORS = {}
FONTS = {}
SIZES = {}
PADDING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
}

_CURRENT_THEME = "classic"


def apply_theme(theme_name: str = "classic") -> str:
    """Switch active theme in-place so all existing imported dict references stay valid."""
    global _CURRENT_THEME
    key = theme_name if theme_name in THEMES else "classic"
    spec = THEMES[key]
    COLORS.clear()
    COLORS.update(spec["colors"])
    FONTS.clear()
    FONTS.update(spec["fonts"])
    SIZES.clear()
    SIZES.update(spec["sizes"])
    _CURRENT_THEME = key
    return key


def get_current_theme() -> str:
    return _CURRENT_THEME


apply_theme("classic")
