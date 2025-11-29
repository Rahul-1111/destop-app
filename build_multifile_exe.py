#!/usr/bin/env python3
"""
build_exe.py – Final working version for HMI OCR System
Includes EasyOCR, Torch, TorchVision, Models, .env, Icons, UI.
"""

import os
import PyInstaller.__main__

APP_NAME = "HMI_OCR_System"
ICON_PATH = "app/BX.ico"
ENV_FILE = ".env"
ENTRY_FILE = "main_desktop_app.py"

print("=" * 80)
print("🏗️  Building HMI OCR System with PyInstaller")
print("=" * 80)

# Check icon
if os.path.exists(ICON_PATH):
    print(f"✅ Icon found: {ICON_PATH}")
else:
    print("❌ Icon not found, continuing without icon...")

# Check .env
if os.path.exists(ENV_FILE):
    print(f"📌 Adding .env → {ENV_FILE};.")
else:
    print("⚠️ No .env file found")

# ---- BUILD COMMAND ----
PyInstaller.__main__.run([
    ENTRY_FILE,
    "--name", APP_NAME,
    "--onefile",
    "--noconsole",
    "--icon", ICON_PATH,

    # Bundle project folders
    "--add-data", "app;app",
    "--add-data", f"{ENV_FILE};.",

    # Hidden imports (required for EasyOCR)
    "--hidden-import=easyocr",
    "--hidden-import=torch",
    "--hidden-import=torchvision",
    "--hidden-import=serial",
    "--hidden-import=cv2",
    "--hidden-import=numpy",
    "--hidden-import=PIL",

    # Optimize output
    "--clean",
    "--collect-all", "easyocr",
    "--collect-all", "torch",
    "--collect-all", "torchvision",
])

print("\n" + "=" * 80)
print("✅ Build complete!")
print("=" * 80)
print(f"📦 EXE located at: dist\\{APP_NAME}\\{APP_NAME}.exe\n")
print("💡 Deployment Tips:")
print("   • Copy the entire dist/HMI_OCR_System folder to the target PC")
print("   • No internet needed (EasyOCR model is included)")
print("   • Install VC++ Redistributable 2015-2022")
