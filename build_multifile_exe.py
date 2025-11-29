#!/usr/bin/env python3
import os
import PyInstaller.__main__

print("\n==============================================")
print("🏗️  Building MULTI-FILE HMI OCR System")
print("==============================================\n")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(BASE_DIR, "main_desktop_app.py")
ICON_PATH = os.path.join(BASE_DIR, "app", "BX.ico")
ENV_FILE = os.path.join(BASE_DIR, ".env")

# Correct OS formatting
env_target = ".;."
if os.name == "nt":
    env_target = f"{ENV_FILE};."

print("🔨 Running PyInstaller...\n")

PyInstaller.__main__.run([
    MAIN_SCRIPT,                 # Main script FIRST (important)

    "--name=HMI_OCR_System",
    "--icon=" + ICON_PATH,
    "--onedir",                  # <---- MULTI-FILE (FAST LOADING)
    "--windowed",
    "--clean",
    "--noconsole",

    # Add environment file
    f"--add-data={ENV_FILE};.",

    # Required OCR/ML packages
    "--hidden-import=easyocr",
    "--hidden-import=torch",
    "--hidden-import=torchvision",
    "--collect-all=easyocr",
    "--collect-all=torch",
    "--collect-all=torchvision",

    # Add dependencies for OpenCV, pillow, numpy
    "--collect-all=cv2",
    "--collect-all=PIL",
    "--collect-all=numpy",

    "--log-level=WARN",
])

print("\n==============================================")
print("🎉 MULTI-FILE BUILD COMPLETE!")
print("==============================================")
print("📦 EXE located at: dist/HMI_OCR_System/")
print("🚀 FAST loading – No extraction time.\n")
