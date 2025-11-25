import sys
import os
import threading
import time
from datetime import datetime
from typing import Optional
from uuid import uuid4
import serial

# PyQt5 imports
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import cv2
import numpy as np
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QTableWidgetItem

# Remove logging completely
import logging
logging.disable(logging.CRITICAL)
import warnings
warnings.filterwarnings("ignore")

# Your existing services (unchanged)
# --- Existing imports ---
from app.services.camera_service import camera_service
from app.services.ocr_service import ocr_service
from app.services.data_service import data_service
from app.core.database import create_tables, SessionLocal, Part
from app.schemas.readings import BalanceReadingCreate
from app.utils.qr_utils import print_balance_readings, _load_state, _save_state, get_current_serial_and_part

class QRScanDialog(QDialog):
    def __init__(self, expected_value: str, timeout: int = 60, parent=None):
        super().__init__(parent)
        self.expected_value = expected_value.strip()
        self.scanned_value = ""
        self.success = False
        self.timeout = timeout
        self.setWindowTitle("Scan QR to Confirm")
        self.resize(400, 150)

        layout = QVBoxLayout()

        # Main instruction label
        label = QLabel(f"Please 🔍 scan the QR")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 18px; font-weight: bold; color: navy;")  # <-- popup color here
        layout.addWidget(label)

        # Scan box
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("🔍 Scan here...")
        self.input_edit.setStyleSheet("font-size: 20px; color: darkgreen; background: #eeeeee;")  # <-- scan box color
        self.input_edit.textChanged.connect(self.check_scan)
        layout.addWidget(self.input_edit)

        # Status label for result
        self.status_label = QLabel(f"⏳ Waiting for scan (timeout {timeout}s)...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px; color: orange; font-weight: bold;")  # <-- status color default
        layout.addWidget(self.status_label)

        self.setLayout(layout)
        self.input_edit.setFocus()

    def check_scan(self):
        text = self.input_edit.text().strip()
        if not text:
            return
        self.scanned_value = text

        # For robust comparison, ignore case and leading/trailing spaces
        expected_clean = self.expected_value.strip().upper()
        scanned_clean = text.strip().upper()

        if expected_clean == scanned_clean:
            self.success = True
            self.status_label.setText("✅ Scan matched! Saving data...")
            self.accept()
        else:
            self.status_label.setText("❌ Scan mismatch!")
            QTimer.singleShot(100000, self.reject)

    def check_timeout(self):
        if not self.success:
            self.status_label.setText("⌛ Scan timeout!")
            QTimer.singleShot(100000, self.reject)

class CameraThread(QThread):
    """Separate thread for camera operations to prevent UI blocking"""
    frame_ready = pyqtSignal(np.ndarray)

    def __init__(self):
        super().__init__()
        self.running = False

    def run(self):
        self.running = True
        while self.running:
            frame = camera_service.get_current_frame()
            if frame is not None:
                self.frame_ready.emit(frame)
            self.msleep(33)  # ~30 FPS

    def stop(self):
        self.running = False

class PartManagementDialog(QDialog):
    """Dialog for adding/editing/deleting parts"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Part Management")
        self.setModal(True)
        self.resize(1300, 400)
        self.current_theme = getattr(parent, 'current_theme', 'Modern Industrial Dark')
        self.setup_ui()
        self.load_parts()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        # Apply enhanced stylesheet
        self.setStyleSheet(self.get_enhanced_stylesheet())

        # Parts table
        self.parts_table = QTableWidget()
        self.parts_table.setColumnCount(10)
        self.parts_table.setHorizontalHeaderLabels([
            "Code", "Name", "A1 Min", "A1 Max", "A2 Min", "A2 Max",
            "W1 Min", "W1 Max", "W2 Min", "W2 Max"
        ])
        layout.addWidget(self.parts_table)

        # Buttons
        button_layout = QHBoxLayout()
        self.add_btn = QPushButton("➕ Add Part")
        self.edit_btn = QPushButton("✏️ Edit Part")
        self.delete_btn = QPushButton("🗑️ Delete Part")
        self.close_btn = QPushButton("❎ Close")

        self.add_btn.clicked.connect(self.add_part)
        self.edit_btn.clicked.connect(self.edit_part)
        self.delete_btn.clicked.connect(self.delete_part)
        self.close_btn.clicked.connect(self.accept)

        button_layout.addWidget(self.add_btn)
        button_layout.addWidget(self.edit_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.close_btn)
        layout.addLayout(button_layout)

    def get_enhanced_stylesheet(self):
        """Enhanced stylesheet matching main app theme"""
        if self.current_theme == "Modern Industrial Dark":
            return """
            QDialog {
                background-color: #1E2D3A;
                color: #FFFFFF;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            
            QTableWidget {
                background: rgba(55,71,79,220);
                alternate-background-color: rgba(42,63,79,180);
                gridline-color: #546E7A;
                color: white;
                border: 2px solid #546E7A;
                border-radius: 8px;
                selection-background-color: #4A90E2;
            }
            
            QHeaderView::section {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4A90E2, stop:1 #357ABD);
                color: white;
                border: 1px solid #357ABD;
                padding: 8px;
                font-weight: bold;
            }
            
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4A90E2, stop:1 #357ABD);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: bold;
                min-height: 20px;
            }
            
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #66B3FF, stop:1 #4A90E2);
            }
            """
        elif self.current_theme == "Industrial Orange":
            return """
            QDialog {
                background-color: #2C3E50;
                color: #ECF0F1;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            
            QTableWidget {
                background: rgba(58,82,107,220);
                alternate-background-color: rgba(52,73,94,180);
                gridline-color: #4A6578;
                color: #ECF0F1;
                selection-background-color: #E67E22;
            }
            
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #E67E22, stop:1 #D35400);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: bold;
            }
            
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F39C12, stop:1 #E67E22);
            }
            """

    def load_parts(self):
        """Load parts from database"""
        db = SessionLocal()
        try:
            parts = data_service.get_all_parts(db)
            self.parts_table.setRowCount(len(parts))
            for row, part in enumerate(parts):
                self.parts_table.setItem(row, 0, QTableWidgetItem(part.part_code or ""))
                self.parts_table.setItem(row, 1, QTableWidgetItem(part.part_name or ""))
                self.parts_table.setItem(row, 2, QTableWidgetItem(str(part.angle1_min or "")))
                self.parts_table.setItem(row, 3, QTableWidgetItem(str(part.angle1_max or "")))
                self.parts_table.setItem(row, 4, QTableWidgetItem(str(part.angle2_min or "")))
                self.parts_table.setItem(row, 5, QTableWidgetItem(str(part.angle2_max or "")))
                self.parts_table.setItem(row, 6, QTableWidgetItem(f"{part.weight1_min:.3f}" if part.weight1_min is not None else ""))
                self.parts_table.setItem(row, 7, QTableWidgetItem(f"{part.weight1_max:.3f}" if part.weight1_max is not None else ""))
                self.parts_table.setItem(row, 8, QTableWidgetItem(f"{part.weight2_min:.3f}" if part.weight2_min is not None else ""))
                self.parts_table.setItem(row, 9, QTableWidgetItem(f"{part.weight2_max:.3f}" if part.weight2_max is not None else ""))

        finally:
            db.close()

    def add_part(self):
        """Add new part"""
        dialog = PartEditDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.load_parts()

    def edit_part(self):
        """Edit selected part"""
        row = self.parts_table.currentRow()
        if row >= 0:
            part_code = self.parts_table.item(row, 0).text()
            dialog = PartEditDialog(self, part_code)
            if dialog.exec_() == QDialog.Accepted:
                self.load_parts()

    def delete_part(self):
        """Delete selected part"""
        row = self.parts_table.currentRow()
        if row >= 0:
            part_code = self.parts_table.item(row, 0).text()
            reply = QMessageBox.question(self, "Delete Part",
                                       f"Are you sure you want to delete part {part_code}?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                db = SessionLocal()
                try:
                    part = db.query(Part).filter(Part.part_code == part_code).first()
                    if part:
                        db.delete(part)
                        db.commit()
                        self.load_parts()
                finally:
                    db.close()

class PartEditDialog(QDialog):
    """Dialog for editing part details"""

    def __init__(self, parent=None, part_code=None):
        super().__init__(parent)
        self.part_code = part_code
        self.setWindowTitle("Edit Part" if part_code else "Add Part")
        self.setModal(True)
        self.resize(400, 300)
        self.current_theme = getattr(parent, 'current_theme', 'Modern Industrial Dark')
        self.setup_ui()
        if part_code:
            self.load_part_data()

class PartEditDialog(QDialog):
    """Dialog for editing part details"""

    def __init__(self, parent=None, part_code=None):
        super().__init__(parent)
        self.part_code = part_code
        self.setWindowTitle("Edit Part" if part_code else "Add Part")
        self.setModal(True)
        self.resize(400, 300)
        self.current_theme = getattr(parent, 'current_theme', 'Modern Industrial Dark')

        self.setup_ui()

        if part_code:
            self.load_part_data()

    def setup_ui(self):
        layout = QFormLayout(self)
        self.setStyleSheet(self.get_enhanced_stylesheet())

        self.code_edit = QLineEdit()
        self.name_edit = QLineEdit()
        self.a1_min_edit = QLineEdit()
        self.a1_max_edit = QLineEdit()
        self.a2_min_edit = QLineEdit()
        self.a2_max_edit = QLineEdit()
        self.w1_min_edit = QLineEdit()
        self.w1_max_edit = QLineEdit()
        self.w2_min_edit = QLineEdit()
        self.w2_max_edit = QLineEdit()

        layout.addRow("🏷️ Part Code:", self.code_edit)
        layout.addRow("📛 Part Name:", self.name_edit)
        layout.addRow("↖️ Angle L Min:", self.a1_min_edit)
        layout.addRow("↖️ Angle L Max:", self.a1_max_edit)
        layout.addRow("↗️ Angle R Min:", self.a2_min_edit)
        layout.addRow("↗️ Angle R Max:", self.a2_max_edit)
        layout.addRow("⚖️ Weight L Min:", self.w1_min_edit)
        layout.addRow("⚖️ Weight L Max:", self.w1_max_edit)
        layout.addRow("⚖️ Weight R Min:", self.w2_min_edit)
        layout.addRow("⚖️ Weight R Max:", self.w2_max_edit)

        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("💾 Save")
        self.cancel_btn = QPushButton("❎ Cancel")

        self.save_btn.clicked.connect(self.save_part)
        self.cancel_btn.clicked.connect(self.reject)

        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addRow(button_layout)


    def get_enhanced_stylesheet(self):
        """Enhanced stylesheet matching main app theme"""
        if self.current_theme == "Modern Industrial Dark":
            return """
            QDialog {
                background-color: #1E2D3A;
                color: #FFFFFF;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            
            QLineEdit {
                background: rgba(55,71,79,220);
                color: white;
                border: 2px solid #546E7A;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
            }
            
            QLineEdit:focus {
                border-color: #4A90E2;
            }
            
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4A90E2, stop:1 #357ABD);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: bold;
            }
            
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #66B3FF, stop:1 #4A90E2);
            }
            
            QLabel {
                color: #FFFFFF;
            }
            """
        else:  # Fallback
            return """
            QDialog {
                background-color: #2E2E2E;
                color: #FFFFFF;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            
            QLineEdit {
                background-color: #3A3A3A;
                color: #FFFFFF;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 5px;
            }
            
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4A90E2, stop:1 #357ABD);
                color: white;
                border-radius: 5px;
                padding: 8px;
                font-size: 14px;
            }
            """

    def load_part_data(self):
        """Load existing part data"""
        db = SessionLocal()
        try:
            part = db.query(Part).filter(Part.part_code == self.part_code).first()
            if part:
                self.code_edit.setText(part.part_code or "")
                self.name_edit.setText(part.part_name or "")
                self.a1_min_edit.setText(str(part.angle1_min or ""))
                self.a1_max_edit.setText(str(part.angle1_max or ""))
                self.a2_min_edit.setText(str(part.angle2_min or ""))
                self.a2_max_edit.setText(str(part.angle2_max or ""))
                self.w1_min_edit.setText(f"{part.weight1_min:.3f}" if part.weight1_min is not None else "")
                self.w1_max_edit.setText(f"{part.weight1_max:.3f}" if part.weight1_max is not None else "")
                self.w2_min_edit.setText(f"{part.weight2_min:.3f}" if part.weight2_min is not None else "")
                self.w2_max_edit.setText(f"{part.weight2_max:.3f}" if part.weight2_max is not None else "")
        finally:
            db.close()

    def save_part(self):
        """Save part data"""
        try:
            def safe_float(text):
                return float(text) if text.strip() else None

            db = SessionLocal()
            try:
                if self.part_code:  # Edit existing
                    part = db.query(Part).filter(Part.part_code == self.part_code).first()
                    if part:
                        part.part_name = self.name_edit.text()
                        part.angle1_min = safe_float(self.a1_min_edit.text())
                        part.angle1_max = safe_float(self.a1_max_edit.text())
                        part.angle2_min = safe_float(self.a2_min_edit.text())
                        part.angle2_max = safe_float(self.a2_max_edit.text())
                        part.weight1_min = safe_float(self.w1_min_edit.text())
                        part.weight1_max = safe_float(self.w1_max_edit.text())
                        part.weight2_min = safe_float(self.w2_min_edit.text())
                        part.weight2_max = safe_float(self.w2_max_edit.text())
                else:  # Add new
                    data_service.add_part(
                        db,
                        self.code_edit.text(),
                        self.name_edit.text(),
                        safe_float(self.a1_min_edit.text()),
                        safe_float(self.a1_max_edit.text()),
                        safe_float(self.a2_min_edit.text()),
                        safe_float(self.a2_max_edit.text()),
                        safe_float(self.w1_min_edit.text()),
                        safe_float(self.w1_max_edit.text()),
                        safe_float(self.w2_min_edit.text()),
                        safe_float(self.w2_max_edit.text())
                    )

                db.commit()
                self.accept()
            finally:
                db.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save part: {str(e)}")

class HMIDesktopApp(QMainWindow):
    """ENHANCED Main Desktop Application with Beautiful Industrial Themes and HW Support"""
    hw_capture_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.current_part = None
        self.camera_thread = None
        self.HW_serial = None
        self.HW_running = False
        
        # ENHANCED THEME SYSTEM - ONLY 3 THEMES
        self.is_dark_mode = True
        self.current_theme = "Modern Industrial Dark"
        
        self.init_services()
        self.init_ui()
        self.start_camera_thread()
        self.start_HW_thread()  # Start HW serial listening
        self.show_roi = False
        self.load_parts()
        self.load_last_part()
        self.hw_capture_signal.connect(self.capture_reading)

    def init_services(self):
        """Initialize database and services"""
        try:
            create_tables()
            camera_service.start_camera()
        except Exception as e:
            QMessageBox.critical(self, "Initialization Error", f"Failed to initialize services: {str(e)}")

    def listen_HW(self):
        """Listen for HW serial commands - Pin 2 sends 'PBON'"""
        try:
            self.HW_serial = serial.Serial('COM3', 115200, timeout=1)
            self.HW_running = True
            print("✅ HW connected on COM3")
            
            while self.HW_running:
                try:
                    line = self.HW_serial.readline().decode().strip()
                    if "CYCLE END" in line:  # Pin 2 button pressed
                        self.hw_capture_signal.emit()  
                        print("📸 HW capture triggered!")
                except serial.SerialException:
                    print("Serial connection lost")
                    break
                except Exception as e:
                    print(f"HW read error: {e}")
        except Exception as e:
            print(f"HW not connected: {e}")
            self.HW_serial = None

    def send_HW_result(self, result_type):
        """Send pass/fail/no_frame result to HW
        result_type: 'PASS', 'FAIL', or 'NO_FRAME'
        """
        try:
            if self.HW_serial and self.HW_serial.is_open:
                if result_type == 'PASS':
                    self.HW_serial.write(b'OK\n')  # Pin 6 (pass)
                    self.HW_serial.write(b'DECLAMP\n')
                    print("✅ Sent PASS signal to HW (Pin 6)")
                elif result_type == 'FAIL':
                    self.HW_serial.write(b'FAIL\n')  # Pin 7 (fail)
                    print("❌ Sent FAIL signal to HW (Pin 7)")
                    self.HW_serial.write(b'DECLAMP\n')
                elif result_type == 'NO_FRAME':
                    self.HW_serial.write(b'NO_FRAME\n')  # Pin 8 (no frame)
                    print("📷 Sent NO_FRAME signal to HW (Pin 8)")
                self.HW_serial.flush()
        except Exception as e:
            print(f"HW send error: {e}")

    def start_HW_thread(self):
        """Start HW listening thread"""
        HW_thread = threading.Thread(target=self.listen_HW, daemon=True)
        HW_thread.start()

    def init_ui(self):
        """Setup main user interface with enhanced styling"""
        self.setWindowTitle("HMI Balance Machine OCR System - Professional Edition with HW")
        self.setGeometry(100, 100, 1400, 900)
        
        # Apply enhanced professional stylesheet
        self.setStyleSheet(self.get_enhanced_stylesheet())

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout with enhanced spacing
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(20)

        # Left panel - Camera and controls
        left_panel = QVBoxLayout()

        # Camera feed with enhanced styling
        self.camera_label = QLabel("📷 Camera Feed")
        self.camera_label.setFixedSize(1080, 800)
        self.camera_label.setScaledContents(True)
        self.camera_label.setStyleSheet("""
            QLabel {
                border: 3px solid #4A90E2;
                border-radius: 12px;
                background-color: rgba(30,45,58,100);
            }
        """)
        left_panel.addWidget(self.camera_label)

        # Enhanced camera controls
        camera_controls = QHBoxLayout()
        camera_controls.setSpacing(15)
        self.roi_view_btn = QPushButton("🔍 Show ROI")
        
        self.roi_view_btn.clicked.connect(self.toggle_roi_view)
        
        camera_controls.addWidget(self.roi_view_btn)
        camera_controls.addStretch()
        left_panel.addLayout(camera_controls)

        # Right panel - Controls and data
        right_panel = QVBoxLayout()
        right_panel.setSpacing(5)

        # Enhanced Part selection section
        part_group = QGroupBox("🔧 Part Selection")
        part_layout = QVBoxLayout(part_group)
        part_layout.setSpacing(10)

        self.part_combo = QComboBox()
        self.part_combo.setMinimumHeight(45)
        self.part_combo.currentTextChanged.connect(self.on_part_selected)

        part_buttons = QHBoxLayout()
        part_buttons.setSpacing(10)
        self.manage_parts_btn = QPushButton("⚙️ Manage Parts")
        self.refresh_parts_btn = QPushButton("🔄 Refresh")

        self.manage_parts_btn.clicked.connect(self.open_part_management)
        self.refresh_parts_btn.clicked.connect(self.load_parts)

        part_buttons.addWidget(self.manage_parts_btn)
        part_buttons.addWidget(self.refresh_parts_btn)

        part_layout.addWidget(QLabel("Select Active Part:"))
        part_layout.addWidget(self.part_combo)
        part_layout.addLayout(part_buttons)
        right_panel.addWidget(part_group)

        # Enhanced Capture section with HW info
        capture_group = QGroupBox("📸 Capture Reading (Manual + HW)")
        capture_layout = QVBoxLayout(capture_group)
        
        # HW status
        self.HW_status_label = QLabel("🔌 HW: Checking connection...")
        capture_layout.addWidget(self.HW_status_label)
        
        self.capture_btn = QPushButton("🎯 CAPTURE READING")
        self.capture_btn.setObjectName("capture_btn")
        self.capture_btn.setMinimumHeight(65)
        self.capture_btn.clicked.connect(self.capture_reading)

        capture_layout.addWidget(self.capture_btn)
        right_panel.addWidget(capture_group)

        # Enhanced Results section - Initialize with 2x2 table
        results_group = QGroupBox("📊 Last Reading Results")
        results_layout = QVBoxLayout(results_group)
        
        # Initialize table as 2x2 from the start
        self.results_table = QTableWidget(2, 2)
        self.results_table.setHorizontalHeaderLabels(["Left", "Right"])
        self.results_table.setVerticalHeaderLabels(["Weight", "Angle"])
        self.results_table.setColumnWidth(0, 230)
        self.results_table.setColumnWidth(1, 230)
        self.results_table.setRowHeight(0, 72)
        self.results_table.setRowHeight(1, 72)
        
        # Initialize cells with N/A and big font
        big_bold_font = QFont()
        big_bold_font.setPointSize(24)
        big_bold_font.setBold(True)
        
        for row in range(2):
            for col in range(2):
                item = QTableWidgetItem("N/A")
                item.setFont(big_bold_font)
                self.results_table.setItem(row, col, item)
        
        self.results_table.setMinimumHeight(200)
        results_layout.addWidget(self.results_table)
        right_panel.addWidget(results_group)

        # Enhanced Status section
        status_group = QGroupBox("📡 System Status")
        status_layout = QVBoxLayout(status_group)
        
        self.status_label = QLabel("✅ Ready")
        self.last_qr_label = QLabel("🖨️ QR Print: Not attempted")
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.last_qr_label)
        right_panel.addWidget(status_group)

        # Enhanced Data management
        data_group = QGroupBox("💾 Data Management")
        data_layout = QVBoxLayout(data_group)
        data_layout.setSpacing(10)
        
        self.export_btn = QPushButton("📤 Export to CSV")
        self.view_data_btn = QPushButton("📋 View All Data")
        
        self.export_btn.clicked.connect(self.export_data)
        self.view_data_btn.clicked.connect(self.view_all_data)
        
        data_layout.addWidget(self.export_btn)
        data_layout.addWidget(self.view_data_btn)
        right_panel.addWidget(data_group)

        right_panel.addStretch()

        # Add panels to main layout
        main_layout.addLayout(left_panel, 2)
        main_layout.addLayout(right_panel, 1)

        # Setup enhanced menu bar
        self.setup_enhanced_menu_bar()

        # Setup enhanced status bar
        self.statusbar = self.statusBar()
        self.statusbar.showMessage("🚀 Application started successfully")

        # Check HW connection status after UI setup
        QTimer.singleShot(2000, self.update_HW_status)

    def update_HW_status(self):
        """Update HW connection status"""
        if self.HW_serial and self.HW_serial.is_open:
            self.HW_status_label.setText("🔌 HW: ✅ Connected (Push button to capture)")
            self.HW_status_label.setStyleSheet("color: green;")
        else:
            self.HW_status_label.setText("🔌 HW: ❌ Not connected (Manual only)")
            self.HW_status_label.setStyleSheet("color: orange;")

    def get_enhanced_stylesheet(self):
        """ENHANCED PROFESSIONAL STYLESHEET with ONLY 2 Industrial Themes"""
        # THEME 1: MODERN INDUSTRIAL DARK (Default Professional Theme)
        if self.current_theme == "Modern Industrial Dark":
            return """
            /* Modern Industrial Dark - Professional Excellence */
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1E2D3A, stop:1 #263238);
                color: #FFFFFF;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
            }
            
            QGroupBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(42,63,79,200), stop:1 rgba(55,71,79,220));
                border: 2px solid #4A90E2;
                border-radius: 12px;
                margin-top: 15px;
                padding-top: 20px;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 600;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 5px 15px;
                left: 15px;
                color: #4A90E2;
                background: rgba(30,45,58,200);
                border-radius: 6px;
                font-weight: bold;
                font-size: 16px;
            }
            
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4A90E2, stop:1 #357ABD);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 20px;
                font-size: 14px;
                font-weight: bold;
                min-height: 25px;
            }
            
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #66B3FF, stop:1 #4A90E2);
            }
            
            QPushButton:pressed {
                background: #357ABD;
            }
            
            QPushButton#capture_btn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #28A745, stop:1 #218838);
                font-size: 18px;
                font-weight: bold;
                min-height: 40px;
                border-radius: 10px;
            }
            
            QPushButton#capture_btn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #34C759, stop:1 #28A745);
            }
            
            QComboBox {
                background: rgba(55,71,79,220);
                color: white;
                border: 2px solid #546E7A;
                border-radius: 8px;
                padding: 10px 15px;
                font-size: 14px;
                min-height: 25px;
            }
            
            QComboBox:hover {
                border-color: #4A90E2;
            }
            
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            
            QComboBox::down-arrow {
                image: none;
                border-left: 6px solid transparent;
                border-right: 6px solid transparent;
                border-top: 8px solid white;
                margin-right: 8px;
            }
            
            QComboBox QAbstractItemView {
                background: #37474F;
                color: white;
                border: 2px solid #4A90E2;
                border-radius: 8px;
                selection-background-color: #4A90E2;
            }
            
            QTableWidget {
                background: rgba(55,71,79,220);
                alternate-background-color: rgba(42,63,79,180);
                gridline-color: #546E7A;
                color: white;
                border: 2px solid #546E7A;
                border-radius: 8px;
                selection-background-color: #4A90E2;
            }
            
            QHeaderView::section {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4A90E2, stop:1 #357ABD);
                color: white;
                border: 1px solid #357ABD;
                padding: 8px;
                font-weight: bold;
                font-size: 13px;
            }
            
            QLabel {
                color: #FFFFFF;
                font-size: 14px;
            }
            
            QStatusBar {
                background: #1E2D3A;
                color: #B0BEC5;
                border-top: 2px solid #4A90E2;
                padding: 5px;
                font-weight: bold;
            }
            
            QMenuBar {
                background: #1E2D3A;
                color: white;
                border-bottom: 2px solid #4A90E2;
            }
            
            QMenuBar::item {
                background: transparent;
                padding: 8px 15px;
                margin: 2px;
                border-radius: 4px;
            }
            
            QMenuBar::item:selected {
                background: #4A90E2;
            }
            
            QMenu {
                background: #37474F;
                color: white;
                border: 2px solid #4A90E2;
                border-radius: 8px;
            }
            
            QMenu::item {
                padding: 8px 20px;
                margin: 2px;
            }
            
            QMenu::item:selected {
                background: #4A90E2;
                border-radius: 4px;
            }
            
            QLineEdit {
                background: rgba(55,71,79,220);
                color: white;
                border: 2px solid #546E7A;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
            }
            
            QLineEdit:focus {
                border-color: #4A90E2;
            }
            """

        # THEME 2: INDUSTRIAL ORANGE
        elif self.current_theme == "Industrial Orange":
            return """
            /* Industrial Orange - Steel & Fire */
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2C3E50, stop:1 #34495E);
                color: #ECF0F1;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            
            QGroupBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(52,73,94,220), stop:1 rgba(58,82,107,240));
                border: 2px solid #E67E22;
                border-radius: 12px;
                margin-top: 15px;
                padding-top: 20px;
                color: #ECF0F1;
                font-weight: 600;
            }
            
            QGroupBox::title {
                color: #E67E22;
                font-weight: bold;
                font-size: 16px;
                left: 15px;
                background: rgba(44,62,80,220);
                padding: 5px 15px;
                padding-top: 40px;
                border-radius: 6px;
            }
            
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #E67E22, stop:1 #D35400);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 20px;
                font-weight: bold;
            }
            
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F39C12, stop:1 #E67E22);
            }
            
            QPushButton#capture_btn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #27AE60, stop:1 #229954);
                font-size: 18px;
                min-height: 40px;
            }
            
            QComboBox {
                background: rgba(58,82,107,220);
                color: #ECF0F1;
                border: 2px solid #4A6578;
                border-radius: 8px;
                padding: 10px 15px;
            }
            
            QComboBox:hover {
                border-color: #E67E22;
            }
            
            QTableWidget {
                background: rgba(58,82,107,220);
                alternate-background-color: rgba(52,73,94,180);
                gridline-color: #4A6578;
                color: #ECF0F1;
                selection-background-color: #E67E22;
            }
            
            QStatusBar {
                background: #2C3E50;
                color: #BDC3C7;
                border-top: 2px solid #E67E22;
                padding: 5px;
                font-weight: bold;
            }
            
            QMenuBar {
                background: #2C3E50;
                color: #ECF0F1;
                border-bottom: 2px solid #E67E22;
            }
            
            QMenuBar::item:selected {
                background: #E67E22;
            }
            """

        # FALLBACK (should not happen with cleaned version)
        else:
            return self.get_original_dark_theme()

    def get_original_dark_theme(self):
        """Fallback theme"""
        return """
        QMainWindow {
            background-color: #1E1E1E;
            font-family: 'Segoe UI', Arial, sans-serif;
        }
        
        QLabel {
            color: #FFFFFF;
        }
        
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4A90E2, stop:1 #357ABD);
            color: white;
            border-radius: 5px;
            padding: 8px;
            font-size: 14px;
            font-weight: bold;
        }
        """

    def setup_enhanced_menu_bar(self):
        """ENHANCED Menu Bar with ONLY 2 Professional Themes"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu('📁 File')
        export_action = QAction('📤 Export Data', self)
        export_action.setShortcut('Ctrl+E')
        export_action.triggered.connect(self.export_data)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        exit_action = QAction('❌ Exit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Tools menu
        tools_menu = menubar.addMenu('🔧 Tools')
        parts_action = QAction('⚙️ Manage Parts', self)
        parts_action.triggered.connect(self.open_part_management)
        tools_menu.addAction(parts_action)

        # Enhanced View menu with ONLY 3 Professional Themes
        view_menu = menubar.addMenu('👁️ View')
        fullscreen_action = QAction('🖥️ Fullscreen', self)
        fullscreen_action.setShortcut('F11')
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fullscreen_action)

        # PROFESSIONAL THEME SELECTION SUBMENU - ONLY 2 THEMES
        theme_menu = view_menu.addMenu('🎨 Professional Themes')
        themes = [
            ("🏭 Modern Industrial Dark", "Modern Industrial Dark"),
            ("🔥 Industrial Orange", "Industrial Orange"),
        ]

        for display_name, theme_name in themes:
            action = QAction(display_name, self)
            action.triggered.connect(lambda checked, name=theme_name: self.change_theme(name))
            theme_menu.addAction(action)

        view_menu.addSeparator()

        # Keep existing toggle for compatibility
        theme_action = QAction('🌓 Toggle Dark/Light Mode', self)
        theme_action.setShortcut('Ctrl+T')
        theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(theme_action)

    def change_theme(self, theme_name):
        """Change to specific professional theme"""
        self.current_theme = theme_name
        self.setStyleSheet(self.get_enhanced_stylesheet())
        self.statusbar.showMessage(f"✨ Theme changed to: {theme_name}")

    def toggle_theme(self):
        """Enhanced theme toggle (cycles through the 2 themes)"""
        themes = ["Modern Industrial Dark", "Industrial Orange"]
        current_index = themes.index(self.current_theme) if self.current_theme in themes else 0
        next_index = (current_index + 1) % len(themes)
        self.current_theme = themes[next_index]
        self.setStyleSheet(self.get_enhanced_stylesheet())
        self.statusbar.showMessage(f"🌓 Switched to {self.current_theme}")

    def show_about(self):
        """Show enhanced about dialog"""
        QMessageBox.about(self, "About HMI System",
                         """🏭 HMI Balance Machine OCR System - Professional Edition
                         
Version: 2.0.1 (with HW Support)

Enhanced with 2 Beautiful Industrial Themes

Features:
• Modern Industrial Dark
• Industrial Orange
• HW Push Button Support
• Real-time Camera OCR
• Part Management System

Developed for Industrial Excellence ⚡
HW Support: Push button triggers capture""")

    # All your existing methods remain the same...

    def start_camera_thread(self):
        """Start camera display thread"""
        if not self.camera_thread or not self.camera_thread.isRunning():
            self.camera_thread = CameraThread()
            self.camera_thread.frame_ready.connect(self.update_camera_display)
            self.camera_thread.start()

    def update_camera_display(self, frame):
        """Update camera display with new frame"""
        try:
            from app.core.config import settings
            display_frame = frame.copy()
            
            if self.show_roi:
                roi_configs = [
                    ("angle1", settings.ROI_ANGLE1_X, settings.ROI_ANGLE1_Y, settings.ROI_ANGLE1_W, settings.ROI_ANGLE1_H),
                    ("angle2", settings.ROI_ANGLE2_X, settings.ROI_ANGLE2_Y, settings.ROI_ANGLE2_W, settings.ROI_ANGLE2_H),
                    ("weight1", settings.ROI_WEIGHT1_X, settings.ROI_WEIGHT1_Y, settings.ROI_WEIGHT1_W, settings.ROI_WEIGHT1_H),
                    ("weight2", settings.ROI_WEIGHT2_X, settings.ROI_WEIGHT2_Y, settings.ROI_WEIGHT2_W, settings.ROI_WEIGHT2_H)
                ]
                
                if len(display_frame.shape) == 2:
                    display_frame = cv2.cvtColor(display_frame, cv2.COLOR_GRAY2BGR)
                
                readings = getattr(self, "latest_readings", {})
                
                for label, x, y, w, h in roi_configs:
                    cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    value = readings.get(label, (None,))[0]
                    text_to_show = f"{label}: {value if value is not None else '-'}"
                    text_x = x + 5
                    text_y = y + h // 2
                    cv2.putText(display_frame, text_to_show, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,0,0), 2)
                
                height, width, channel = display_frame.shape
                bytes_per_line = 3 * width
                qt_image = QImage(display_frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
            else:
                if len(display_frame.shape) == 2:
                    height, width = display_frame.shape
                    bytes_per_line = width
                    qt_image = QImage(display_frame.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
                else:
                    height, width, channel = display_frame.shape
                    bytes_per_line = 3 * width
                    qt_image = QImage(display_frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
            
            pixmap = QPixmap.fromImage(qt_image)
            self.camera_label.setPixmap(pixmap)
        except Exception:
            pass

    def start_camera(self):
        """Start camera service"""
        try:
            success = camera_service.start_camera()
            if success:
                self.statusbar.showMessage("📷 Camera started successfully")
                self.start_camera_thread()
            else:
                self.statusbar.showMessage("❌ Failed to start camera")
        except Exception as e:
            QMessageBox.critical(self, "Camera Error", f"Failed to start camera: {str(e)}")

    def toggle_roi_view(self):
        self.show_roi = not self.show_roi
        self.statusbar.showMessage(f"🔍 ROI {'On' if self.show_roi else 'Off'}")

    def load_parts(self):
        """Load parts into combo box"""
        self.part_combo.clear()
        db = SessionLocal()
        try:
            parts = data_service.get_all_parts(db)
            for part in parts:
                self.part_combo.addItem(f"{part.part_code} - {part.part_name}")
        finally:
            db.close()

    def load_last_part(self):
        """Load last selected part from state"""
        try:
            state = _load_state()
            last_part = state.get("last_part")
            if last_part:
                for i in range(self.part_combo.count()):
                    if last_part in self.part_combo.itemText(i):
                        self.part_combo.setCurrentIndex(i)
                        break
        except Exception:
            pass

    def on_part_selected(self, text):
        """Handle part selection"""
        if text:
            part_code = text.split(" - ")[0]
            self.current_part = part_code
            state = _load_state()
            _save_state(state.get("month"), state.get("serial", 0), part_code)

    def open_part_management(self):
        """Open part management dialog"""
        dialog = PartManagementDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.load_parts()

    def capture_reading(self):
        """Capture reading, print QR, and wait for scan before storing."""
        # Setup table for display
        if self.results_table.rowCount() != 2 or self.results_table.columnCount() != 2:
            self.results_table.setRowCount(2)
            self.results_table.setColumnCount(2)
            self.results_table.setHorizontalHeaderLabels(["Left", "Right"])
            self.results_table.setVerticalHeaderLabels(["Weight", "Angle"])
            self.results_table.setColumnWidth(0, 230)
            self.results_table.setColumnWidth(1, 230)
            self.results_table.setRowHeight(0, 72)
            self.results_table.setRowHeight(1, 72)

        big_bold_font = QFont()
        big_bold_font.setPointSize(24)
        big_bold_font.setBold(True)

        self.status_label.setText("🔄 Processing...")
        self.status_label.setStyleSheet("font-weight: bold; color: orange;")

        try:
            frame = camera_service.get_current_frame()
            if frame is None:
                self.status_label.setText("❌ Error: No camera frame")
                self.status_label.setStyleSheet("font-weight: bold; color: red;")
                self.send_HW_result('NO_FRAME')
                return

            readings = ocr_service.extract_balance_readings(frame)

            # Weight row (top)
            value_weight1, _ = readings.get("weight1", (None, 0.0))
            value_weight2, _ = readings.get("weight2", (None, 0.0))
            # Angle row (bottom)
            value_angle1, _ = readings.get("angle1", (None, 0.0))
            value_angle2, _ = readings.get("angle2", (None, 0.0))

            items = [
                (0, 0, value_weight1),
                (0, 1, value_weight2),
                (1, 0, value_angle1),
                (1, 1, value_angle2)
            ]

            for row, col, value in items:
                if value is None:
                    text = "N/A"
                else:
                    if row == 0:      # Weight row
                        text = f"{value:.3f}"
                    else:             # Angle row
                        text = f"{value:.2f}"
                item = QTableWidgetItem(text)
                item.setFont(big_bold_font)
                self.results_table.setItem(row, col, item)

            missing = [k for k in ["angle1", "weight1", "angle2", "weight2"] if readings.get(k, (None,))[0] is None]
            processing_error = f"Missing: {', '.join(missing)}" if missing else None
            limits_failed = []
            part_obj = None

            if not missing and self.current_part:
                db = SessionLocal()
                try:
                    part_obj = db.query(Part).filter(Part.part_code == self.current_part).first()
                    if part_obj:
                        for measurement in ["angle1", "weight1", "angle2", "weight2"]:
                            value = readings[measurement][0]
                            if value is not None:
                                min_val = getattr(part_obj, f"{measurement}_min")
                                max_val = getattr(part_obj, f"{measurement}_max")
                                if min_val is not None and value < min_val:
                                    limits_failed.append(f"{measurement} < {min_val}")
                                if max_val is not None and value > max_val:
                                    limits_failed.append(f"{measurement} > {max_val}")
                finally:
                    db.close()

            if limits_failed:
                if processing_error:
                    processing_error += f"; Limits: {', '.join(limits_failed)}"
                else:
                    processing_error = f"Limits failed: {', '.join(limits_failed)}"

            is_valid = not missing and not limits_failed
            os.makedirs("data", exist_ok=True)
            camera_service.save_frame(frame, "data/latest_captured_frame.jpg")
            qr_printed = False

            if is_valid:
                serial, part_code = get_current_serial_and_part(self.current_part)

                # Unpack the return values: (bool, qr_value, qr_image_path)
                qr_printed, qr_value, qr_image_path = print_balance_readings(
                    part=self.current_part or "Unknown",
                    angle1=readings["angle1"][0],
                    weight1=readings["weight1"][0],
                    angle2=readings["angle2"][0],
                    weight2=readings["weight2"][0],
                )

                if qr_printed:
                    # Show scan dialog with full QR data format that matches what was printed
                    angle1_str = f"{readings['angle1'][0]:.2f}"
                    weight1_str = f"{readings['weight1'][0]:.3f}"
                    angle2_str = f"{readings['angle2'][0]:.2f}"
                    weight2_str = f"{readings['weight2'][0]:.3f}"
                    expected = f"{serial}{part_code};{angle1_str};{weight1_str};{angle2_str};{weight2_str}"

                    dialog = QRScanDialog(expected_value=expected, timeout=10, parent=self)
                    if dialog.exec_() == QDialog.Accepted and dialog.success:
                        # ✅ Only now store data
                        db = SessionLocal()
                        try:
                            reading_data = BalanceReadingCreate(
                                angle1=readings["angle1"][0],
                                weight1=readings["weight1"][0],
                                angle2=readings["angle2"][0],
                                weight2=readings["weight2"][0],
                                is_valid=True,
                                processing_error=processing_error,
                                part_name=part_obj.part_name if part_obj else None
                            )
                            data_service.create_reading(db, reading_data)
                            db.commit()
                            self.status_label.setText("✅ QR matched & data stored!")
                            self.status_label.setStyleSheet("font-weight: bold; color: green;")
                            self.send_HW_result('PASS')
                        finally:
                            db.close()
                    else:
                        self.status_label.setText("⚠️ Scan timeout or mismatch - data not saved")
                        self.status_label.setStyleSheet("font-weight: bold; color: orange;")
                else:
                    self.status_label.setText("❌ Print failed - skipping scan/store")
                    self.status_label.setStyleSheet("font-weight: bold; color: red;")
            else:
                self.status_label.setText(f"❌ Invalid reading: {processing_error}")
                self.status_label.setStyleSheet("font-weight: bold; color: red;")
                self.send_HW_result('FAIL')

            self.last_qr_label.setText(f"🖨️ QR Print: {'✅ Success' if qr_printed else '❌ Failed'}")
            self.last_qr_label.setStyleSheet("color: green;" if qr_printed else "color: red;")

        except Exception as e:
            self.status_label.setText(f"❌ Error: {str(e)}")
            self.status_label.setStyleSheet("font-weight: bold; color: red;")

    def export_data(self):
        """Export readings to CSV"""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Export Readings",
                f"readings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "CSV Files (*.csv)"
            )
            
            if filename:
                db = SessionLocal()
                try:
                    readings, total = data_service.get_readings(db, skip=0, limit=10000)
                    import pandas as pd
                    rows = []
                    for reading in readings:
                        row = {
                            'ID': reading.id,
                            'Created At': reading.created_at,
                            'Part Name': getattr(reading, 'part_name', ''),
                            'L Angle': reading.angle1,
                            'L Weight': reading.weight1,
                            'R Angle': reading.angle2,
                            'R Weight': reading.weight2,
                            'Is Valid': reading.is_valid,
                        }
                        rows.append(row)
                    df = pd.DataFrame(rows)
                    df.to_csv(filename, index=False)
                    QMessageBox.information(self, "Export Success", f"✅ Data exported to {filename}")
                finally:
                    db.close()
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"❌ Failed to export data: {str(e)}")

    def view_all_data(self):
        """Open data viewing dialog"""
        dialog = QDialog(self)
        dialog.setWindowTitle("📊 All Readings")
        dialog.resize(1100, 600)
        dialog.setStyleSheet(self.get_enhanced_stylesheet())

        layout = QVBoxLayout(dialog)
        table = QTableWidget()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([
            "ID", "Created At", "Part", "L Angle", "L Weight", "R Angle", "R Weight", "Valid"
        ])

        table.setColumnWidth(0, 60)  # ID column small
        table.setColumnWidth(1, 220)

        db = SessionLocal()
        try:
            readings, total = data_service.get_readings(db, skip=0, limit=1000)
            table.setRowCount(len(readings))
            for row, reading in enumerate(readings):
                table.setItem(row, 0, QTableWidgetItem(str(reading.id)))
                table.setItem(row, 1, QTableWidgetItem(
                    reading.created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(reading.created_at, "strftime") else str(reading.created_at)))
                table.setItem(row, 2, QTableWidgetItem(getattr(reading, 'part_name', '')))
                table.setItem(row, 3, QTableWidgetItem(str(reading.angle1)))
                table.setItem(row, 4, QTableWidgetItem(str(reading.weight1)))
                table.setItem(row, 5, QTableWidgetItem(str(reading.angle2)))
                table.setItem(row, 6, QTableWidgetItem(str(reading.weight2)))
                table.setItem(row, 7, QTableWidgetItem("✅ Yes" if reading.is_valid else "❌ No"))
        finally:
            db.close()

        layout.addWidget(table)
        close_btn = QPushButton("🚪 Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec_()

    def toggle_fullscreen(self):
        """Toggle fullscreen mode"""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event):
        """Handle application close"""
        try:
            # Stop HW listening
            self.HW_running = False
            if self.HW_serial and self.HW_serial.is_open:
                self.HW_serial.close()
                
            # Stop camera thread
            if self.camera_thread:
                self.camera_thread.stop()
                self.camera_thread.wait()
            camera_service.stop_camera()
        except Exception:
            pass
        
        event.accept()

def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    
    # Set application properties
    app.setApplicationName("HMI Balance Machine OCR System - Professional Edition with HW")
    app.setApplicationVersion("2.0.1")
    app.setOrganizationName("Industrial Excellence Solutions")
    
    # Create and show main window
    window = HMIDesktopApp()
    window.showFullScreen()
    
    # Run application
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()