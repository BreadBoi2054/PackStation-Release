---
version: "1.0"
name: Obsidian Pro
description: High-contrast industrial telemetry theme for PackStation desktop packing operations, preserving 100% layout parity with the default Classic theme.
colors:
  bg_primary: "#090A0B"
  bg_secondary: "#111315"
  bg_card: "#16191D"
  bg_input: "#0D0F11"
  sidebar_bg: "#060708"
  sidebar_active: "#1D2127"
  sidebar_hover: "#13161A"
  accent: "#F97316"
  accent_hover: "#FB923C"
  accent_dark: "#C2410C"
  brand_title: "#F97316"
  success: "#10B981"
  success_bg: "#052E1F"
  warning: "#FBBF24"
  warning_bg: "#3B2506"
  error: "#F43F5E"
  error_bg: "#3F0B17"
  danger: "#F43F5E"
  danger_bg: "#3F0B17"
  recording: "#F43F5E"
  recording_pulse: "#E11D48"
  text_primary: "#F4F4F5"
  text_secondary: "#A1A1AA"
  text_muted: "#71717A"
  border: "#27272A"
  border_light: "#3F3F46"
  banner_bg: "#121519"
  banner_border: "#27272A"
  btn_qr: "#27272A"
  btn_qr_hover: "#3F3F46"
  btn_scan_net: "#27272A"
  btn_scan_net_hover: "#3F3F46"
  btn_imou: "#EA580C"
  btn_imou_hover: "#C2410C"
  btn_add: "#27272A"
  btn_add_hover: "#3F3F46"
  btn_primary_alt: "#27272A"
  btn_primary_alt_hover: "#3F3F46"
  btn_folder: "#27272A"
  btn_folder_hover: "#3F3F46"
  btn_export: "#10B981"
  btn_export_hover: "#059669"
  dup_bg: "#3B2506"
  dup_border: "#FBBF24"
  dup_text: "#FDE68A"
  dup_btn: "#EA580C"
  dup_btn_hover: "#C2410C"
typography:
  title:
    fontFamily: Segoe UI
    fontSize: 20px
    fontWeight: 700
    lineHeight: 1.2
  heading:
    fontFamily: Segoe UI
    fontSize: 16px
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: Segoe UI
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.4
  mono:
    fontFamily: Consolas
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.4
  status_code:
    fontFamily: Consolas
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.1
rounded:
  sharp: 2px
  classic: 8px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
components:
  card-telemetry:
    backgroundColor: "{colors.bg_card}"
    rounded: "{rounded.sharp}"
    padding: 12px
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#FFFFFF"
    rounded: "{rounded.sharp}"
    padding: 10px
---

# PackStation Design System

## Overview
PackStation supports two interchangeable visual themes controlled from **Settings -> Giao diện hiển thị**:
- **`classic` (Default):** Preserves the familiar deep-navy palette (`#0f0f1a` / `#16213e`), `8px` soft corners, and legacy multi-accent utility buttons.
- **`industrial_carbon` ("Obsidian Pro"):** Optional high-contrast industrial dark telemetry theme tailored for long warehouse packing sessions with strict single-accent discipline.

## Colors
- **Primary Canvas (`#090A0B`) & Surface (`#16191D`):** True obsidian zinc neutrals maximize contrast against bright RTSP video feeds and reduce glare inside dimly lit storage areas.
- **Singular Accent (`#F97316` Signal Safety Orange):** Reserved for primary navigation focus, active tracking code readouts, and primary actions—eliminating AI-purple and generic cyan clichés.
- **Telemetry States:** Emerald (`#10B981`) for connected cameras and completed exports, Amber (`#FBBF24`) for duplicate/warning alerts, and Laser Crimson (`#F43F5E`) for active recording and destructive actions.

## Typography
- **UI Sans (`Segoe UI`):** Native Windows ClearType hierarchy across headings (`16–20pt`), body (`12pt`), and metadata (`10pt`).
- **Tabular Monospace (`Consolas`):** Fixed-width tracking numbers (`24pt`), timestamps, and live scan logs prevent horizontal jitter during rapid camera scans.

## Layout
- Preserves 100% of the existing desktop structure (`180px` left navigation rail, live camera viewport + scan console on Camera page, searchable Orders workbench, Stats dashboard, and Settings cards) so switching themes requires zero relearning.

## Elevation & Depth
- `classic` separates panels via tonal contrast without borders (`card_border_width = 0`).
- `industrial_carbon` replaces drop shadows with crisp `1px` structural hairlines (`#27272A`) and stepped zinc surfaces (`#060708` -> `#090A0B` -> `#16191D`).

## Shapes
- `classic` maintains `8px` corner radii.
- `industrial_carbon` enforces strict `2px` technical edges across cards, inputs, and buttons (`border_radius = 2`) for an unmistakable hardware-console silhouette.

## Components
- **Secondary Utility Buttons:** Machined Zinc (`#27272A` / `#3F3F46`) keeps visual noise low so Signal Orange primary CTAs (`Lưu cài đặt`, `Kích hoạt Imou`) and Emerald export actions stand out immediately.
- **Order Selection Banner:** Flat `#121519` surface with `1px` `#27272A` frame and high-contrast `#F4F4F5` typography.

## Do's and Don'ts
- **Do** keep `classic` as the out-of-the-box default in `config.py` and allow instant switching in Settings.
- **Do** mutate `COLORS`, `FONTS`, `PADDING`, and `SIZES` in-place via `apply_theme()` so all UI modules stay synchronized.
- **Don't** introduce purple/violet glows or alter widget placement when switching between `classic` and `industrial_carbon`.
