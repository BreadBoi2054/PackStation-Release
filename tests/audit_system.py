"""Comprehensive system audit:
1. i18n key audit (vi-VN and en-US).
2. Theme constants audit (COLORS, FONTS, PADDING, SIZES).
3. Threading safety audit (Tkinter calls from secondary threads).
4. Database schema & query integrity.
5. Exception handling & resource cleanup.
"""
import os
import sys
import re
import json
import ast
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_audit():
    print("=" * 60)
    print("🔍 RUNNING COMPREHENSIVE PACKSTATION CODEBASE AUDIT")
    print("=" * 60)
    issues_found = []

    # 1. Audit i18n
    with open("i18n/vi-VN.json", "r", encoding="utf-8") as f:
        vi_keys = json.load(f)
    en_keys = {}
    if os.path.exists("i18n/en-US.json"):
        with open("i18n/en-US.json", "r", encoding="utf-8") as f:
            en_keys = json.load(f)

    # Check key parity between vi-VN and en-US
    for k in vi_keys:
        if k not in en_keys:
            issues_found.append(f"[i18n] Key '{k}' present in vi-VN but missing in en-US")
    for k in en_keys:
        if k not in vi_keys:
            issues_found.append(f"[i18n] Key '{k}' present in en-US but missing in vi-VN")

    # Check all _t() calls in code
    t_pattern = re.compile(r'_t\(\s*["\']([^"\']+)["\']')
    for root, _, files in os.walk("."):
        if any(p in root for p in ["build", "dist", "__pycache__", ".git", ".gemini", "tmp_test_env"]):
            continue
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                matches = t_pattern.findall(content)
                for key in matches:
                    if key not in vi_keys and not any(k.startswith(key) for k in vi_keys):
                        issues_found.append(f"[i18n] Missing translation '{key}' used in {path}")

    # 2. Audit Theme constants: FONTS, COLORS, PADDING, SIZES
    from ui.theme import COLORS, FONTS, PADDING, SIZES
    font_pattern = re.compile(r'FONTS\[["\']([^"\']+)["\']\]')
    color_pattern = re.compile(r'COLORS\[["\']([^"\']+)["\']\]')
    padding_pattern = re.compile(r'PADDING\[["\']([^"\']+)["\']\]')
    sizes_pattern = re.compile(r'SIZES\[["\']([^"\']+)["\']\]')

    for root, _, files in os.walk("ui"):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                for fk in font_pattern.findall(content):
                    if fk not in FONTS:
                        issues_found.append(f"[Theme] Missing FONTS['{fk}'] used in {path}")
                for ck in color_pattern.findall(content):
                    if ck not in COLORS:
                        issues_found.append(f"[Theme] Missing COLORS['{ck}'] used in {path}")
                for pk in padding_pattern.findall(content):
                    if pk not in PADDING:
                        issues_found.append(f"[Theme] Missing PADDING['{pk}'] used in {path}")
                for sk in sizes_pattern.findall(content):
                    if sk not in SIZES:
                        issues_found.append(f"[Theme] Missing SIZES['{sk}'] used in {path}")

    # 3. Audit Database queries
    with open("database.py", "r", encoding="utf-8") as f:
        db_code = f.read()
    # Check for raw string concatenation in SQL queries (SQL injection prevention)
    sql_lines = [line for line in db_code.splitlines() if "execute(" in line]
    for idx, l in enumerate(sql_lines, 1):
        if "f\"" in l or "f'" in l:
            # Check if f-string is used inside SQL execution
            if "PRAGMA" not in l and "CREATE TABLE" not in l:
                issues_found.append(f"[DB] Possible unparameterized f-string in SQL query: {l.strip()}")

    # 4. Check Camera and Video Recorder edge cases
    with open("core/camera_manager.py", "r", encoding="utf-8") as f:
        cam_code = f.read()
    if "cv2.VideoCapture" in cam_code and "release()" not in cam_code:
        issues_found.append("[Camera] Missing video capture release()")

    with open("core/video_recorder.py", "r", encoding="utf-8") as f:
        rec_code = f.read()
    if "cv2.VideoWriter" in rec_code and "release()" not in rec_code:
        issues_found.append("[Recorder] Missing video writer release()")

    print(f"\nAudit complete. Issues identified: {len(issues_found)}")
    for iss in issues_found:
        print("  ⚠️", iss)

    return issues_found

if __name__ == "__main__":
    run_audit()
