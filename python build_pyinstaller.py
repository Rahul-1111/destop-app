from cx_Freeze import setup, Executable
import sys
import os

# Build options - optimized for your project structure
build_exe_options = {
    "packages": [
        "PyQt5", "PyQt5.QtCore", "PyQt5.QtWidgets", "PyQt5.QtGui", "PyQt5.sip",
        "cv2", "numpy", "easyocr", "PIL", "skimage",
        "sqlalchemy", "sqlalchemy.orm", "pandas", 
        "pydantic", "pydantic_settings", "pydantic_core",
        "qrcode", "reportlab", "reportlab.pdfgen", "reportlab.lib",
        "typing_extensions", "annotated_types", "fastapi",
        "uvicorn", "starlette"
    ],
    "include_files": [
        ("app/", "app/"),
        ("data/", "data/"),
        (".env", ".env"),
        # Add more resources if needed
    ],
    "excludes": [
        "tkinter", "unittest", "email", "http", "urllib", 
        "xml", "test", "distutils", "multiprocessing",
        "matplotlib", "jupyter", "IPython", "notebook",
        "sphinx", "pytest", "setuptools"
    ],
    "optimize": 2, 
    "build_exe": "dist/HMI_OCR_System",
    "silent": True,
    "include_msvcrt": True,
    "zip_include_packages": [
        "numpy", "pandas", "PIL", "cv2"
    ],
    "bin_excludes": [
        "QtWebEngineCore.dll", "QtQml.dll", "QtQuick.dll",
        "Qt5WebEngine.dll", "Qt5Qml.dll", "Qt5Quick.dll"
    ]
}

base = None
if sys.platform == "win32":
    base = "Win32GUI"

executables = [
    Executable(
        "main_desktop_app.py",
        base=base,
        target_name="HMI_OCR_System.exe",
        icon=None,
        shortcut_name="HMI OCR System",
        shortcut_dir="DesktopFolder",
        copyright="© 2025 HMI OCR System"
    )
]

setup(
    name="HMI Balance Machine OCR System",
    version="1.0.0",
    description="Desktop application for HMI balance machine OCR readings with camera integration",
    author="Shubham",
    author_email="rana779848@gmail.com",
    url="https://github.com/your-repo",
    options={"build_exe": build_exe_options},
    executables=executables
)

if __name__ == "__main__":
    print("=" * 60)
    print("🏗️  HMI OCR System - Build Script")
    print("=" * 60)
    print("📁 Project Structure Detected:")
    print(f"   ✅ App folder: {'Found' if os.path.exists('app') else 'Missing'}")
    print(f"   ✅ Data folder: {'Found' if os.path.exists('data') else 'Missing'}")
    print(f"   ✅ .env file: {'Found' if os.path.exists('.env') else 'Missing'}")
    print(f"   ✅ Main script: {'Found' if os.path.exists('main_desktop_app.py') else 'Missing'}")
    print()
    print("🚀 To build executable, run:")
    print("   python build_exe.py build")
    print()
    print("📦 Output will be in: dist/HMI_OCR_System/")
    print("🎯 Executable: dist/HMI_OCR_System/HMI_OCR_System.exe")
    print("=" * 60)
