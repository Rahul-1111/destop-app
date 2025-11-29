#!/usr/bin/env python3
import os
import PyInstaller.__main__

print("\n==============================================")
print("🚀 Building SINGLE-FILE HMI OCR EXE")
print("==============================================\n")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(BASE_DIR, "main_desktop_app.py")
ICON_PATH = os.path.join(BASE_DIR, "app", "BX.ico")
ENV_FILE = os.path.join(BASE_DIR, ".env")

# Prepare add-data formatting depending on OS
env_target = ".;"
if os.name == "nt":
    env_target = f"{ENV_FILE};."

print("\n🔨 Running PyInstaller...\n")

PyInstaller.__main__.run([
    MAIN_SCRIPT,                     # <---- MAIN SCRIPT *FIRST* (mandatory)
    "--name=HMI_OCR_System",
    "--icon=" + ICON_PATH,
    "--onefile",                     # <---- SINGLE EXE
    "--windowed",
    "--clean",
    "--noconsole",

    # Include .env
    f"--add-data={ENV_FILE};.",

    # OCR & ML packages
    "--hidden-import=easyocr",
    "--hidden-import=torch",
    "--hidden-import=torchvision",
    "--collect-all=easyocr",
    "--collect-all=torch",
    "--collect-all=torchvision",

    # OpenCV, numpy, PIL
    "--collect-all=cv2",
    "--collect-all=PIL",
    "--collect-all=numpy",

    "--log-level=WARN",
])

print("\n==============================================")
print("🎉 SINGLE-FILE BUILD COMPLETE!")
print("==============================================")
print("📦 EXE created: dist/HMI_OCR_System.exe\n")
print("⚠️ NOTICE: File size may be large (600–900 MB).")
print("⚠️ Copy EXE only → runs on any Windows PC.\n")
