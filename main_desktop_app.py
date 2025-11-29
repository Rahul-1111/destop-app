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
from pathlib import Path
from app.core.config import settings

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
        label = QLabel(f"Please 🔎 scan the QR")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 18px; font-weight: bold; color: #4A90E2;")
        layout.addWidget(label)

        # Scan box
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("🔎 Scan here...")
        self.input_edit.setStyleSheet("font-size: 20px; color: darkgreen; background: #eeeeee;")
        self.input_edit.textChanged.connect(self.check_scan)
        layout.addWidget(self.input_edit)

        # Status label for result
        self.status_label = QLabel(f"⏳ Waiting for scan (timeout {timeout}s)...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px; color: orange; font-weight: bold;")
        layout.addWidget(self)

        self.setLayout(layout)
        self.input_edit.setFocus()
        
        # Start timeout timer
        self.timeout_timer = QTimer(self)
        self.timeout_timer.timeout.connect(self.check_timeout)
        self.timeout_timer.start(timeout * 1000)  # Convert to milliseconds

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
            self.status_label.setStyleSheet("font-size: 16px; color: green; font-weight: bold;")
            QTimer.singleShot(500, self.accept)  # Close after 0.5 seconds
        else:
            self.status_label.setText("❌ Scan mismatch! Try again...")
            self.status_label.setStyleSheet("font-size: 16px; color: red; font-weight: bold;")
            self.input_edit.clear()  # Clear for retry
            self.input_edit.selectAll()

    def check_timeout(self):
        """Called when timeout expires"""
        if not self.success:
            self.status_label.setText("⏱️ Scan timeout!")
            self.status_label.setStyleSheet("font-size: 16px; color: red; font-weight: bold;")
            QTimer.singleShot(1000, self.reject)  # Close after 1 second

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
    """Dialog for adding/editing/deleting parts - NO ANGLE THRESHOLDS"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Part Management")
        self.setModal(True)
        self.resize(900, 400)  # Smaller width since fewer columns
        self.current_theme = getattr(parent, 'current_theme', 'Modern Industrial Dark')
        self.setup_ui()
        self.load_parts()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.setStyleSheet(self.get_enhanced_stylesheet())

        # Parts table - ONLY 6 COLUMNS (removed 4 angle columns)
        self.parts_table = QTableWidget()
        self.parts_table.setColumnCount(6)
        self.parts_table.setHorizontalHeaderLabels([
            "Code", "Name", "W1 Min", "W1 Max", "W2 Min", "W2 Max"
        ])
        layout.addWidget(self.parts_table)

        # Buttons
        button_layout = QHBoxLayout()
        self.add_btn = QPushButton("➕ Add Part")
        self.edit_btn = QPushButton("✏️ Edit Part")
        self.delete_btn = QPushButton("🗑️ Delete Part")
        self.close_btn = QPushButton("⏎ Close")

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
        """Load parts - ONLY WEIGHT COLUMNS"""
        db = SessionLocal()
        try:
            parts = data_service.get_all_parts(db)
            self.parts_table.setRowCount(len(parts))

            for row, part in enumerate(parts):
                self.parts_table.setItem(row, 0, QTableWidgetItem(part.part_code or ""))
                self.parts_table.setItem(row, 1, QTableWidgetItem(part.part_name or ""))

                def show3(v):
                    if v is None or v == "":
                        return ""
                    return f"{float(v):.3f}"

                # ONLY WEIGHT COLUMNS (columns 2-5)
                self.parts_table.setItem(row, 2, QTableWidgetItem(show3(part.weight1_min)))
                self.parts_table.setItem(row, 3, QTableWidgetItem(show3(part.weight1_max)))
                self.parts_table.setItem(row, 4, QTableWidgetItem(show3(part.weight2_min)))
                self.parts_table.setItem(row, 5, QTableWidgetItem(show3(part.weight2_max)))

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
    """Dialog for editing part details - NO ANGLE FIELDS"""

    def __init__(self, parent=None, part_code=None):
        super().__init__(parent)
        self.part_code = part_code
        self.setWindowTitle("Edit Part" if part_code else "Add Part")
        self.setModal(True)
        self.resize(400, 250)  # Smaller height
        self.current_theme = getattr(parent, 'current_theme', 'Modern Industrial Dark')
        self.setup_ui()
        if part_code:
            self.load_part_data()

    def setup_ui(self):
        layout = QFormLayout(self)
        self.setStyleSheet(self.get_enhanced_stylesheet())

        self.code_edit = QLineEdit()
        self.name_edit = QLineEdit()
        # ONLY WEIGHT FIELDS (removed angle fields)
        self.w1_min_edit = QLineEdit()
        self.w1_max_edit = QLineEdit()
        self.w2_min_edit = QLineEdit()
        self.w2_max_edit = QLineEdit()

        layout.addRow("🏷️ Part Code:", self.code_edit)
        layout.addRow("📛 Part Name:", self.name_edit)
        layout.addRow("⚖️ Weight L Min:", self.w1_min_edit)
        layout.addRow("⚖️ Weight L Max:", self.w1_max_edit)
        layout.addRow("⚖️ Weight R Min:", self.w2_min_edit)
        layout.addRow("⚖️ Weight R Max:", self.w2_max_edit)

        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("💾 Save")
        self.cancel_btn = QPushButton("⏎ Cancel")

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
        else:
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
        """Load existing part data - ONLY WEIGHTS"""
        db = SessionLocal()
        try:
            part = db.query(Part).filter(Part.part_code == self.part_code).first()
            if part:
                self.code_edit.setText(part.part_code or "")
                self.name_edit.setText(part.part_name or "")
                # ONLY WEIGHT FIELDS
                self.w1_min_edit.setText(f"{part.weight1_min:.3f}" if part.weight1_min is not None else "")
                self.w1_max_edit.setText(f"{part.weight1_max:.3f}" if part.weight1_max is not None else "")
                self.w2_min_edit.setText(f"{part.weight2_min:.3f}" if part.weight2_min is not None else "")
                self.w2_max_edit.setText(f"{part.weight2_max:.3f}" if part.weight2_max is not None else "")
        finally:
            db.close()

    def save_part(self):
        """Save part data - ONLY WEIGHTS"""
        try:
            def safe_float(text):
                return float(text) if text.strip() else None

            db = SessionLocal()
            try:
                if self.part_code:  # Edit existing
                    part = db.query(Part).filter(Part.part_code == self.part_code).first()
                    if part:
                        part.part_name = self.name_edit.text()
                        # ONLY UPDATE WEIGHTS
                        part.weight1_min = safe_float(self.w1_min_edit.text())
                        part.weight1_max = safe_float(self.w1_max_edit.text())
                        part.weight2_min = safe_float(self.w2_min_edit.text())
                        part.weight2_max = safe_float(self.w2_max_edit.text())
                else:  # Add new
                    data_service.add_part(
                        db,
                        self.code_edit.text(),
                        self.name_edit.text(),
                        None,  # angle1_min - removed
                        None,  # angle1_max - removed
                        None,  # angle2_min - removed
                        None,  # angle2_max - removed
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
        self.active_toast = None
        
        # ENHANCED THEME SYSTEM - ONLY 3 THEMES
        self.is_dark_mode = True
        self.current_theme = "Modern Industrial Dark"
        
        self.init_services()
        self.init_ui()
        self.start_camera_thread()
        self.start_HW_thread()  # Start HW serial listening
        self.show_roi = True
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
        """Enhanced Menu Bar with ROI Editor"""
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
        
        # **ADD ROI EDITOR HERE**
        roi_action = QAction('📐 Edit ROI Regions', self)
        roi_action.setShortcut('Ctrl+R')
        roi_action.triggered.connect(self.open_roi_editor)
        tools_menu.addAction(roi_action)

        # View menu
        view_menu = menubar.addMenu('👁️ View')
        fullscreen_action = QAction('🖥️ Fullscreen', self)
        fullscreen_action.setShortcut('F11')
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fullscreen_action)

        # Theme menu
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
        theme_action = QAction('🌓 Toggle Dark/Light Mode', self)
        theme_action.setShortcut('Ctrl+T')
        theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(theme_action)

    def open_roi_editor(self):
        """Open ROI Editor dialog"""
        dialog = ROIEditorDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            # Reload settings immediately after successful save
            if self.reload_settings_live():
                self.show_auto_popup(
                    "Settings Applied",
                    "✅ New ROI coordinates are now active!\n\nNo restart required.",
                    popup_type="success",
                    duration=3000
                )
            else:
                self.show_auto_popup(
                    "Reload Failed",
                    "⚠️ Please restart the application\nto apply ROI changes.",
                    popup_type="warning",
                    duration=4000
                )

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
    - Modern Industrial Dark
    - Industrial Orange
    - HW Push Button Support
    - Real-time Camera OCR
    - Part Management System

    Developed for Industrial Excellence ⚡
    HW Support: Push button triggers capture""")

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
                    ("angle L", settings.ROI_ANGLE1_X, settings.ROI_ANGLE1_Y, settings.ROI_ANGLE1_W, settings.ROI_ANGLE1_H),
                    ("angle R", settings.ROI_ANGLE2_X, settings.ROI_ANGLE2_Y, settings.ROI_ANGLE2_W, settings.ROI_ANGLE2_H),
                    ("weight L", settings.ROI_WEIGHT1_X, settings.ROI_WEIGHT1_Y, settings.ROI_WEIGHT1_W, settings.ROI_WEIGHT1_H),
                    ("weight R", settings.ROI_WEIGHT2_X, settings.ROI_WEIGHT2_Y, settings.ROI_WEIGHT2_W, settings.ROI_WEIGHT2_H)
                ]
                
                # Convert grayscale to BGR
                if len(display_frame.shape) == 2:
                    display_frame = cv2.cvtColor(display_frame, cv2.COLOR_GRAY2BGR)
                
                readings = getattr(self, "latest_readings", {})

                for label, x, y, w, h in roi_configs:
                    # Draw ROI box
                    cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

                    # Get reading
                    value = readings.get(label, (None,))[0]
                    text_to_show = f"{label.upper()}: {value if value is not None else '-'}"

                    # ---- TEXT ABOVE the ROI ----
                    cv2.putText(
                        display_frame,
                        text_to_show,
                        (x + 5, y + 15),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.4,
                        (0, 255, 255),  # Yellow text for clarity
                        1
                    )

                # Convert to Qt image
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
        """Toggle ROI visibility on camera feed"""
        self.show_roi = not self.show_roi
        if self.show_roi:
            self.roi_view_btn.setText("🔎 Hide ROI")
            self.statusbar.showMessage("📐 ROI boxes shown")
        else:
            self.roi_view_btn.setText("🔎 Show ROI")
            self.statusbar.showMessage("📐 ROI boxes hidden")

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

    def test_limit_validation(self):
        """Test limit validation logic"""
        # Create test part with limits
        db = SessionLocal()
        try:
            test_part = Part(
                part_code="TEST001",
                part_name="Test Part",
                angle1_min=5.0,
                angle1_max=15.0,
                weight1_min=2.5,
                weight1_max=4.5,
                angle2_min=5.0,
                angle2_max=15.0,
                weight2_min=2.5,
                weight2_max=4.5
            )
            db.add(test_part)
            db.commit()
            
            # Test cases
            test_readings = [
                {"angle1": 3.0, "weight1": 3.0, "angle2": 10.0, "weight2": 3.5, 
                "expected": "FAIL", "reason": "angle1 too low"},
                {"angle1": 10.0, "weight1": 5.0, "angle2": 10.0, "weight2": 3.5, 
                "expected": "FAIL", "reason": "weight1 too high"},
                {"angle1": 10.0, "weight1": 3.0, "angle2": 10.0, "weight2": 3.5, 
                "expected": "PASS", "reason": "all within limits"},
            ]
            
            print("🧪 Testing limit validation:")
            for i, test in enumerate(test_readings, 1):
                limits_failed = []
                for measurement in ["angle1", "weight1", "angle2", "weight2"]:
                    value = test[measurement]
                    min_val = getattr(test_part, f"{measurement}_min")
                    max_val = getattr(test_part, f"{measurement}_max")
                    
                    if min_val is not None and value < min_val:
                        limits_failed.append(f"{measurement} < {min_val}")
                    if max_val is not None and value > max_val:
                        limits_failed.append(f"{measurement} > {max_val}")
                
                result = "FAIL" if limits_failed else "PASS"
                status = "✅" if result == test["expected"] else "❌"
                print(f"  Test {i}: {status} Expected {test['expected']}, Got {result}")
                if limits_failed:
                    print(f"    Failures: {limits_failed}")
        finally:
            db.close()

    def capture_reading(self):
        """Modified version - Only validates WEIGHT thresholds, ignores angle limits"""
        
        if self.active_toast:
            try:
                self.active_toast.close()
            except:
                pass
            self.active_toast = None

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
        
        QApplication.processEvents()

        try:
            frame = camera_service.get_current_frame()
            if frame is None:
                self.status_label.setText("❌ Error: No camera frame")
                self.status_label.setStyleSheet("font-weight: bold; color: red;")
                self.send_HW_result('NO_FRAME')
                
                self.show_auto_popup(
                    "Camera Error",
                    "No camera frame available! Check camera connection.",
                    popup_type="error",
                    duration=3000
                )
                return

            readings = ocr_service.extract_balance_readings(frame)

            # Store for visualization
            self.latest_readings = {
                "angle L": (readings.get("angle1", (None,))[0],),
                "angle R": (readings.get("angle2", (None,))[0],),
                "weight L": (readings.get("weight1", (None,))[0],),
                "weight R": (readings.get("weight2", (None,))[0],)
            }

            # Extract values
            value_weight1, conf_w1 = readings.get("weight1", (None, 0.0))
            value_weight2, conf_w2 = readings.get("weight2", (None, 0.0))
            value_angle1, conf_a1 = readings.get("angle1", (None, 0.0))
            value_angle2, conf_a2 = readings.get("angle2", (None, 0.0))

            # Prepare table data with validation tracking
            validation_results = {}
            
            items = [
                (0, 0, value_weight1, "weight1", conf_w1),
                (0, 1, value_weight2, "weight2", conf_w2),
                (1, 0, value_angle1, "angle1", conf_a1),
                (1, 1, value_angle2, "angle2", conf_a2)
            ]

            # Check for missing readings
            missing = []
            missing_details = []
            for measurement in ["angle1", "weight1", "angle2", "weight2"]:
                val, conf = readings.get(measurement, (None, 0.0))
                if val is None:
                    missing.append(measurement)
                    readable_name = measurement.replace("1", " Left").replace("2", " Right").replace("angle", "Angle").replace("weight", "Weight")
                    missing_details.append(f"{readable_name}")
            
            processing_error = f"Missing: {', '.join(missing)}" if missing else None
            limits_failed = []
            limits_details = []
            part_obj = None

            # ============================================================
            # MODIFIED: Validate ONLY WEIGHT against part limits
            # Angles are IGNORED - no validation at all
            # ============================================================
            if not missing and self.current_part:
                db = SessionLocal()
                try:
                    part_obj = db.query(Part).filter(Part.part_code == self.current_part).first()
                    if part_obj:
                        # ONLY CHECK WEIGHT1 and WEIGHT2
                        for measurement in ["weight1", "weight2"]:
                            value = readings[measurement][0]
                            
                            if value is not None:
                                min_val = getattr(part_obj, f"{measurement}_min")
                                max_val = getattr(part_obj, f"{measurement}_max")
                                
                                is_valid = True
                                error_msg = []
                                
                                readable_name = measurement.replace("1", " L").replace("2", " R").replace("weight", "Weight")
                                
                                # Check minimum
                                if min_val is not None and value < min_val:
                                    is_valid = False
                                    error_msg.append(f"< {min_val}")
                                    limits_failed.append(f"{measurement} too low")
                                    limits_details.append(f"{readable_name}: {value:.3f} < {min_val}")
                                
                                # Check maximum
                                if max_val is not None and value > max_val:
                                    is_valid = False
                                    error_msg.append(f"> {max_val}")
                                    limits_failed.append(f"{measurement} too high")
                                    limits_details.append(f"{readable_name}: {value:.3f} > {max_val}")
                                
                                validation_results[measurement] = {
                                    'valid': is_valid,
                                    'error': ' & '.join(error_msg) if error_msg else None
                                }
                            else:
                                validation_results[measurement] = {'valid': False, 'error': 'Missing'}
                        
                        # ANGLES: Always mark as valid (no validation)
                        for measurement in ["angle1", "angle2"]:
                            value = readings[measurement][0]
                            if value is not None:
                                validation_results[measurement] = {'valid': True, 'error': None}
                            else:
                                validation_results[measurement] = {'valid': False, 'error': 'Missing'}
                    else:
                        self.status_label.setText(f"⚠️ Part '{self.current_part}' not found")
                        self.status_label.setStyleSheet("font-weight: bold; color: orange;")
                        
                        self.show_auto_popup(
                            "Part Not Found",
                            f"Part '{self.current_part}' not in database. Add it first.",
                            popup_type="warning",
                            duration=3000
                        )
                        return
                finally:
                    db.close()
            elif not self.current_part:
                self.status_label.setText("⚠️ No part selected")
                self.status_label.setStyleSheet("font-weight: bold; color: orange;")
                
                self.show_auto_popup(
                    "No Part Selected",
                    "Please select a part from the dropdown menu first.",
                    popup_type="warning",
                    duration=3000
                )
                return

            # Update processing error
            if limits_failed:
                if processing_error:
                    processing_error += f"; Limits: {', '.join(limits_failed)}"
                else:
                    processing_error = f"Limits failed: {', '.join(limits_failed)}"

            # Display values in table WITH COLOR CODING
            for row, col, value, measurement, confidence in items:
                if value is None:
                    text = "N/A"
                else:
                    if row == 0:  # Weight row
                        text = f"{value:.3f}"
                    else:  # Angle row
                        text = f"{value:.2f}"
                
                item = QTableWidgetItem(text)
                item.setFont(big_bold_font)
                item.setTextAlignment(Qt.AlignCenter)
                
                validation = validation_results.get(measurement, {'valid': True})
                
                if value is None:
                    item.setBackground(QColor(180, 180, 180))
                    item.setForeground(QColor(80, 80, 80))
                    item.setToolTip(f"❌ OCR Failed (confidence: {confidence:.1%})")
                elif not validation['valid']:
                    item.setBackground(QColor(255, 100, 100))
                    item.setForeground(QColor(139, 0, 0))
                    if validation.get('error'):
                        item.setToolTip(f"❌ OUT OF LIMITS: {validation['error']}")
                elif confidence < 0.7:
                    item.setBackground(QColor(255, 255, 150))
                    item.setForeground(QColor(139, 69, 0))
                    item.setToolTip(f"⚠️ Low confidence: {confidence:.1%}")
                else:
                    item.setBackground(QColor(144, 238, 144))
                    item.setForeground(QColor(0, 100, 0))
                    # Different tooltip for angles (no validation)
                    if measurement.startswith('angle'):
                        item.setToolTip(f"✅ Read successfully (confidence: {confidence:.1%}) - No validation")
                    else:
                        item.setToolTip(f"✅ Valid (confidence: {confidence:.1%})")
                
                self.results_table.setItem(row, col, item)

            # Force table update
            QApplication.processEvents()

            # Determine if reading is valid (only weights matter now)
            is_valid = not missing and not limits_failed
            
            # Save frame
            os.makedirs("data", exist_ok=True)
            camera_service.save_frame(frame, "data/latest_captured_frame.jpg")
            
            qr_printed = False

            # Handle invalid readings
            if not is_valid:
                error_parts = []
                if missing:
                    error_parts.append(f"Missing: {', '.join(missing_details)}")
                if limits_failed:
                    error_parts.append(f"Weight out of limits: {', '.join(limits_details)}")
                
                error_message = " | ".join(error_parts)
                
                error_summary = []
                if missing:
                    error_summary.append(f"{len(missing)} missing")
                if limits_failed:
                    error_summary.append(f"{len(limits_failed)} weight(s) out of limits")
                
                status_text = f"❌ Invalid: {', '.join(error_summary)}"
                self.status_label.setText(status_text)
                self.status_label.setStyleSheet("font-weight: bold; color: red;")
                
                self.send_HW_result('FAIL')
                
                self.show_auto_popup(
                    "Reading Invalid",
                    error_message,
                    popup_type="error",
                    duration=5000
                )
                
                self.last_qr_label.setText(f"🖨️ QR Print: ❌ Skipped (invalid)")
                self.last_qr_label.setStyleSheet("color: red;")
                return

            # Readings are VALID - proceed with QR printing
            self.status_label.setText("✅ Valid - printing QR...")
            self.status_label.setStyleSheet("font-weight: bold; color: green;")
            QApplication.processEvents()
            
            serial, part_code = get_current_serial_and_part(self.current_part)

            qr_printed, qr_value, qr_image_path = print_balance_readings(
                part=self.current_part or "Unknown",
                angle1=readings["angle1"][0],
                weight1=readings["weight1"][0],
                angle2=readings["angle2"][0],
                weight2=readings["weight2"][0],
            )

            if qr_printed:
                angle1_str = f"{readings['angle1'][0]:.2f}"
                weight1_str = f"{readings['weight1'][0]:.3f}"
                angle2_str = f"{readings['angle2'][0]:.2f}"
                weight2_str = f"{readings['weight2'][0]:.3f}"
                expected = f"{serial}{part_code};{angle1_str};{weight1_str};{angle2_str};{weight2_str}"

                dialog = QRScanDialog(expected_value=expected, timeout=60, parent=self)
                result = dialog.exec_()
                
                if result == QDialog.Accepted and dialog.success:
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
                        
                        success_text = f"Saved! Serial: {serial} | {weight1_str}kg/{angle1_str}° | {weight2_str}kg/{angle2_str}°"
                        self.show_auto_popup(
                            "Success",
                            success_text,
                            popup_type="success",
                            duration=3000
                        )
                        
                    except Exception as e:
                        db.rollback()
                        self.status_label.setText(f"❌ Database error")
                        self.status_label.setStyleSheet("font-weight: bold; color: red;")
                        
                        self.show_auto_popup(
                            "Database Error",
                            f"Failed to save data: {str(e)}",
                            popup_type="error",
                            duration=4000
                        )
                        self.send_HW_result('FAIL')
                    finally:
                        db.close()
                else:
                    self.status_label.setText("⚠️ QR scan failed - NOT saved")
                    self.status_label.setStyleSheet("font-weight: bold; color: orange;")
                    
                    self.show_auto_popup(
                        "QR Scan Failed",
                        "QR scan timed out or mismatched. Data not saved.",
                        popup_type="warning",
                        duration=3000
                    )
            else:
                self.status_label.setText("❌ QR print failed")
                self.status_label.setStyleSheet("font-weight: bold; color: red;")
                
                self.show_auto_popup(
                    "Print Failed",
                    "Failed to print QR code. Check printer connection.",
                    popup_type="error",
                    duration=3000
                )

            self.last_qr_label.setText(f"🖨️ QR Print: {'✅ Success' if qr_printed else '❌ Failed'}")
            self.last_qr_label.setStyleSheet("color: green;" if qr_printed else "color: red;")

        except Exception as e:
            self.status_label.setText(f"❌ System Error")
            self.status_label.setStyleSheet("font-weight: bold; color: red;")
            
            import traceback
            print(f"Capture error: {traceback.format_exc()}")
            
            self.show_auto_popup(
                "System Error",
                f"System error: {str(e)[:100]}",
                popup_type="error",
                duration=4000
            )

    def show_auto_popup(self, title, message, popup_type="info", duration=3000):
        """
        Show a non-blocking toast notification at the bottom of the window.
        Does NOT block any operations - user can continue working immediately.
        
        Args:
            title: Toast title
            message: Message to display
            popup_type: "success", "error", "warning", or "info"
            duration: Time in milliseconds before auto-close (default 3000ms = 3s)
        """
        # Create independent widget (not blocking)
        toast = QWidget()
        toast.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint | 
            Qt.Tool |
            Qt.X11BypassWindowManagerHint
        )
        toast.setAttribute(Qt.WA_TranslucentBackground)
        toast.setAttribute(Qt.WA_ShowWithoutActivating)  # CRITICAL: Don't steal focus
        toast.setAttribute(Qt.WA_DeleteOnClose)
        
        # Set size
        toast.setFixedSize(700, 100)
        
        # Main layout
        layout = QVBoxLayout(toast)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Container widget for styling
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(15, 12, 15, 12)
        container_layout.setSpacing(15)
        
        # Icon and styling based on type
        if popup_type == "success":
            icon_text = "✅"
            bg_color = "#27AE60"
            border_color = "#229954"
        elif popup_type == "error":
            icon_text = "❌"
            bg_color = "#E74C3C"
            border_color = "#C0392B"
        elif popup_type == "warning":
            icon_text = "⚠️"
            bg_color = "#F39C12"
            border_color = "#E67E22"
        else:  # info
            icon_text = "ℹ️"
            bg_color = "#3498DB"
            border_color = "#2980B9"
        
        # Style the container
        container.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {bg_color}, stop:1 {border_color});
                border-radius: 10px;
                border: 2px solid {border_color};
            }}
            QLabel {{
                color: white;
                background: transparent;
            }}
        """)
        
        # Icon label
        icon_label = QLabel(icon_text)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 32px; background: transparent;")
        icon_label.setFixedWidth(45)
        container_layout.addWidget(icon_label)
        
        # Text container (title + message)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        
        # Title label
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 15px; font-weight: bold; background: transparent;")
        text_layout.addWidget(title_label)
        
        # Message label (single line, truncated if too long)
        message_short = message[:120] + "..." if len(message) > 120 else message
        message_label = QLabel(message_short)
        message_label.setStyleSheet("font-size: 13px; background: transparent;")
        text_layout.addWidget(message_label)
        
        container_layout.addLayout(text_layout, 1)
        
        # Countdown label
        countdown_label = QLabel(f"{duration//1000}s")
        countdown_label.setAlignment(Qt.AlignCenter)
        countdown_label.setStyleSheet("font-size: 16px; font-weight: bold; color: rgba(255,255,255,200); background: transparent;")
        countdown_label.setFixedWidth(35)
        container_layout.addWidget(countdown_label)
        
        layout.addWidget(container)
        
        # Position at BOTTOM CENTER of parent window
        parent_geometry = self.geometry()
        toast_x = parent_geometry.x() + (parent_geometry.width() - toast.width()) // 2
        toast_y = parent_geometry.y() + parent_geometry.height() - toast.height() - 30  # 30px from bottom
        
        # Start position (below screen for slide-up animation)
        start_y = parent_geometry.y() + parent_geometry.height() + 20
        toast.move(toast_x, start_y)
        
        # Show with opacity 0
        toast.setWindowOpacity(0)
        toast.show()
        
        # Slide-up animation
        slide_up = QPropertyAnimation(toast, b"pos")
        slide_up.setDuration(400)
        slide_up.setStartValue(QPoint(toast_x, start_y))
        slide_up.setEndValue(QPoint(toast_x, toast_y))
        slide_up.setEasingCurve(QEasingCurve.OutCubic)
        
        # Fade in animation
        fade_in = QPropertyAnimation(toast, b"windowOpacity")
        fade_in.setDuration(400)
        fade_in.setStartValue(0)
        fade_in.setEndValue(0.95)
        
        # Start animations
        slide_up.start()
        fade_in.start()
        
        # Store animation references to prevent garbage collection
        toast.slide_up = slide_up
        toast.fade_in = fade_in
        
        # Countdown timer
        remaining_time = [duration]
        
    def show_auto_popup(self, title, message, popup_type="info", duration=None):
        # CLOSE ANY EXISTING POPUP
        if self.active_toast:
            try:
                self.active_toast.close()
            except:
                pass
            self.active_toast = None

        toast = QWidget()
        toast.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.X11BypassWindowManagerHint
        )
        toast.setAttribute(Qt.WA_TranslucentBackground)
        toast.setAttribute(Qt.WA_ShowWithoutActivating)
        toast.setAttribute(Qt.WA_DeleteOnClose)
        toast.setFixedSize(700, 100)

        layout = QVBoxLayout(toast)
        layout.setContentsMargins(0, 0, 0, 0)

        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(15, 12, 15, 12)
        container_layout.setSpacing(15)

        if popup_type == "success":
            icon_text = "✅"
            bg_color = "#27AE60"
            border_color = "#229954"
        elif popup_type == "error":
            icon_text = "❌"
            bg_color = "#E74C3C"
            border_color = "#C0392B"
        elif popup_type == "warning":
            icon_text = "⚠️"
            bg_color = "#F39C12"
            border_color = "#E67E22"
        else:
            icon_text = "ℹ️"
            bg_color = "#3498DB"
            border_color = "#2980B9"

        container.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {bg_color}, stop:1 {border_color});
                border-radius: 10px;
                border: 2px solid {border_color};
            }}
            QLabel {{
                color: white;
                background: transparent;
            }}
        """)

        icon_label = QLabel(icon_text)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 32px;")
        icon_label.setFixedWidth(45)
        container_layout.addWidget(icon_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        text_layout.addWidget(title_label)

        short_msg = message[:120] + "..." if len(message) > 120 else message
        msg_label = QLabel(short_msg)
        msg_label.setStyleSheet("font-size: 13px;")
        text_layout.addWidget(msg_label)

        container_layout.addLayout(text_layout, 1)
        layout.addWidget(container)

        # Position at bottom
        parent_geometry = self.geometry()
        toast_x = parent_geometry.x() + (parent_geometry.width() - toast.width()) // 2
        start_y = parent_geometry.y() + parent_geometry.height() + 20
        end_y = parent_geometry.y() + parent_geometry.height() - toast.height() - 30

        toast.move(toast_x, start_y)
        toast.setWindowOpacity(0)
        toast.show()

        slide_up = QPropertyAnimation(toast, b"pos")
        slide_up.setDuration(400)
        slide_up.setStartValue(QPoint(toast_x, start_y))
        slide_up.setEndValue(QPoint(toast_x, end_y))
        slide_up.setEasingCurve(QEasingCurve.OutCubic)

        fade_in = QPropertyAnimation(toast, b"windowOpacity")
        fade_in.setDuration(400)
        fade_in.setStartValue(0)
        fade_in.setEndValue(0.95)

        slide_up.start()
        fade_in.start()

        toast.slide_up = slide_up
        toast.fade_in = fade_in

        # CLICK to manually close
        def mousePressEvent(event):
            toast.close()

        toast.mousePressEvent = mousePressEvent

        # STORE reference for next cycle to auto-close
        self.active_toast = toast


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
                    
                    # Show success toast instead of blocking message box
                    self.show_auto_popup(
                        "Export Success",
                        f"Exported {len(rows)} readings to CSV successfully!",
                        popup_type="success",
                        duration=3000
                    )
                finally:
                    db.close()
        except Exception as e:
            # Show error toast instead of blocking message box
            self.show_auto_popup(
                "Export Error",
                f"Failed to export: {str(e)}",
                popup_type="error",
                duration=4000
            )

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

    def reload_settings_live(self):
        """Reload settings from .env file without restarting"""
        try:
            import os
            from pathlib import Path
            
            # 1. Reload .env file into environment
            env_path = Path(".env")
            if env_path.exists():
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            # Remove quotes if present
                            value = value.strip().strip('"').strip("'")
                            os.environ[key.strip()] = value
            
            # 2. Force reload the config module
            import importlib
            if 'app.core.config' in sys.modules:
                del sys.modules['app.core.config']
            
            # 3. Re-import settings
            from app.core.config import Settings
            new_settings = Settings()
            
            # 4. Update the global settings object
            import app.core.config as config_module
            config_module.settings = new_settings
            
            # 5. Update references in services
            try:
                # Update camera_service reference
                from app.services.camera_service import camera_service
                if hasattr(camera_service, 'settings'):
                    camera_service.settings = new_settings
                
                # Update ocr_service reference  
                from app.services.ocr_service import ocr_service
                if hasattr(ocr_service, 'settings'):
                    ocr_service.settings = new_settings
            except Exception as e:
                print(f"Note: Could not update service references: {e}")
            
            # 6. Update local reference
            globals()['settings'] = new_settings
            
            # 7. Verify the reload worked
            print(f"✅ Settings reloaded:")
            print(f"  ROI_ANGLE1: X={new_settings.ROI_ANGLE1_X}, Y={new_settings.ROI_ANGLE1_Y}, W={new_settings.ROI_ANGLE1_W}, H={new_settings.ROI_ANGLE1_H}")
            print(f"  ROI_WEIGHT1: X={new_settings.ROI_WEIGHT1_X}, Y={new_settings.ROI_WEIGHT1_Y}, W={new_settings.ROI_WEIGHT1_W}, H={new_settings.ROI_WEIGHT1_H}")
            
            self.statusbar.showMessage("✅ ROI settings reloaded - Changes active immediately!")
            
            return True
            
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"❌ Failed to reload settings: {error_trace}")
            self.statusbar.showMessage(f"❌ Failed to reload settings: {str(e)}")
            return False
        
    def verify_roi_reload(self):
        """Show a visual confirmation that ROI changed"""
        from app.core.config import settings as current_settings
        
        # Create a toast with the new coordinates
        roi_info = (
            f"New ROI Coordinates:\n"
            f"Angle L: ({current_settings.ROI_ANGLE1_X}, {current_settings.ROI_ANGLE1_Y}) "
            f"{current_settings.ROI_ANGLE1_W}x{current_settings.ROI_ANGLE1_H}\n"
            f"Weight L: ({current_settings.ROI_WEIGHT1_X}, {current_settings.ROI_WEIGHT1_Y}) "
            f"{current_settings.ROI_WEIGHT1_W}x{current_settings.ROI_WEIGHT1_H}"
        )
        
        print(roi_info)  # Also log to console

class ROIEditorDialog(QDialog):
    """Interactive ROI Editor - drag and resize boxes visually"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ROI Editor - Drag to Adjust Regions")
        self.setModal(True)
        self.resize(1200, 900)
        self.current_theme = getattr(parent, 'current_theme', 'Modern Industrial Dark')
        
        # Current frame
        self.frame = None
        self.display_frame = None
        self.scale_factor = 1.0
        
        # ROI boxes (x, y, w, h, name, color)
        self.roi_boxes = []
        self.selected_box = None
        self.drag_mode = None  # 'move', 'resize_br', 'resize_tl', etc.
        self.drag_start_pos = None
        self.drag_start_box = None
        
        self.setup_ui()
        self.load_current_frame()
        self.load_roi_boxes()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.setStyleSheet(self.get_stylesheet())
        
        # Instructions
        instructions = QLabel(
            "📐 ROI Editor Instructions:\n"
            "• Click and drag box CENTER to MOVE\n"
            "• Click and drag box CORNERS to RESIZE\n"
            "• Click box to select (shows coordinates)\n"
            "• Use Reset button to restore defaults"
        )
        instructions.setStyleSheet("font-size: 13px; padding: 10px; background: rgba(74,144,226,50); border-radius: 5px;")
        layout.addWidget(instructions)
        
        # Main content - horizontal split
        content_layout = QHBoxLayout()
        
        # Left side - Image display
        image_container = QVBoxLayout()
        
        # Image label with scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumWidth(800)
        
        self.image_label = ClickableLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(640, 640)
        self.image_label.mousePressEvent = self.on_mouse_press
        self.image_label.mouseMoveEvent = self.on_mouse_move
        self.image_label.mouseReleaseEvent = self.on_mouse_release
        self.image_label.setMouseTracking(True)
        
        scroll_area.setWidget(self.image_label)
        image_container.addWidget(scroll_area)
        
        # Zoom controls
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("🔍 Zoom:"))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setMinimum(50)
        self.zoom_slider.setMaximum(200)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setTickPosition(QSlider.TicksBelow)
        self.zoom_slider.setTickInterval(25)
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        zoom_layout.addWidget(self.zoom_slider)
        self.zoom_label = QLabel("100%")
        zoom_layout.addWidget(self.zoom_label)
        image_container.addLayout(zoom_layout)
        
        content_layout.addLayout(image_container, 3)
        
        # Right side - ROI list and controls
        right_panel = QVBoxLayout()
        
        # ROI list
        roi_group = QGroupBox("📦 ROI Regions")
        roi_layout = QVBoxLayout(roi_group)
        
        self.roi_table = QTableWidget()
        self.roi_table.setColumnCount(5)
        self.roi_table.setHorizontalHeaderLabels(["Region", "X", "Y", "Width", "Height"])
        self.roi_table.setColumnWidth(0, 100)
        self.roi_table.setColumnWidth(1, 60)
        self.roi_table.setColumnWidth(2, 60)
        self.roi_table.setColumnWidth(3, 60)
        self.roi_table.setColumnWidth(4, 60)
        self.roi_table.cellChanged.connect(self.on_table_cell_changed)
        roi_layout.addWidget(self.roi_table)
        
        right_panel.addWidget(roi_group)
        
        # Action buttons
        button_layout = QVBoxLayout()
        
        self.save_btn = QPushButton("💾 Save ROI Settings")
        self.save_btn.clicked.connect(self.save_roi_settings)
        button_layout.addWidget(self.save_btn)
        
        self.reset_btn = QPushButton("🔄 Reset to Defaults")
        self.reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(self.reset_btn)
        
        self.test_btn = QPushButton("🧪 Test OCR on ROIs")
        self.test_btn.clicked.connect(self.test_ocr)
        button_layout.addWidget(self.test_btn)
        
        self.close_btn = QPushButton("❌ Close")
        self.close_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.close_btn)
        
        right_panel.addLayout(button_layout)
        right_panel.addStretch()
        
        content_layout.addLayout(right_panel, 1)
        
        layout.addLayout(content_layout)
        
    def get_stylesheet(self):
        """Match parent theme"""
        if self.current_theme == "Modern Industrial Dark":
            return """
            QDialog {
                background-color: #1E2D3A;
                color: #FFFFFF;
            }
            QGroupBox {
                background: rgba(42,63,79,200);
                border: 2px solid #4A90E2;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
            }
            QGroupBox::title {
                color: #4A90E2;
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 5px 10px;
            }
            QTableWidget {
                background: rgba(55,71,79,220);
                color: white;
                border: 2px solid #546E7A;
                border-radius: 5px;
                gridline-color: #546E7A;
            }
            QHeaderView::section {
                background: #4A90E2;
                color: white;
                border: 1px solid #357ABD;
                padding: 5px;
                font-weight: bold;
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4A90E2, stop:1 #357ABD);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px;
                font-weight: bold;
                min-height: 30px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #66B3FF, stop:1 #4A90E2);
            }
            QLabel {
                color: white;
            }
            QSlider::groove:horizontal {
                background: #546E7A;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #4A90E2;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            """
        else:
            return """
            QDialog {
                background-color: #2C3E50;
                color: #ECF0F1;
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #E67E22, stop:1 #D35400);
                color: white;
                border-radius: 8px;
                padding: 10px;
                font-weight: bold;
            }
            """
    
    def load_current_frame(self):
        """Load current camera frame"""
        self.frame = camera_service.get_current_frame()
        if self.frame is None:
            # Load a dummy frame
            self.frame = np.zeros((640, 640), dtype=np.uint8)
            cv2.putText(self.frame, "No Camera Frame", (200, 320), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        self.update_display()
    
    def load_roi_boxes(self):
        """Load ROI boxes from CURRENT settings (.env takes priority)"""
        # Force reload settings to get latest .env values
        from app.core.config import settings as current_settings
        
        self.roi_boxes = [
            {
                'name': 'Angle L',
                'x': current_settings.ROI_ANGLE1_X,
                'y': current_settings.ROI_ANGLE1_Y,
                'w': current_settings.ROI_ANGLE1_W,
                'h': current_settings.ROI_ANGLE1_H,
                'color': (0, 255, 0),  # Green
                'setting_prefix': 'ROI_ANGLE1'
            },
            {
                'name': 'Weight L',
                'x': current_settings.ROI_WEIGHT1_X,
                'y': current_settings.ROI_WEIGHT1_Y,
                'w': current_settings.ROI_WEIGHT1_W,
                'h': current_settings.ROI_WEIGHT1_H,
                'color': (255, 255, 0),  # Cyan
                'setting_prefix': 'ROI_WEIGHT1'
            },
            {
                'name': 'Angle R',
                'x': current_settings.ROI_ANGLE2_X,
                'y': current_settings.ROI_ANGLE2_Y,
                'w': current_settings.ROI_ANGLE2_W,
                'h': current_settings.ROI_ANGLE2_H,
                'color': (0, 255, 255),  # Yellow
                'setting_prefix': 'ROI_ANGLE2'
            },
            {
                'name': 'Weight R',
                'x': current_settings.ROI_WEIGHT2_X,
                'y': current_settings.ROI_WEIGHT2_Y,
                'w': current_settings.ROI_WEIGHT2_W,
                'h': current_settings.ROI_WEIGHT2_H,
                'color': (255, 0, 255),  # Magenta
                'setting_prefix': 'ROI_WEIGHT2'
            }
        ]
        self.update_roi_table()
        self.update_display()
    
    def update_roi_table(self):
        """Update table with current ROI values"""
        self.roi_table.blockSignals(True)  # Prevent triggering cellChanged
        self.roi_table.setRowCount(len(self.roi_boxes))
        
        for i, box in enumerate(self.roi_boxes):
            self.roi_table.setItem(i, 0, QTableWidgetItem(box['name']))
            self.roi_table.setItem(i, 1, QTableWidgetItem(str(box['x'])))
            self.roi_table.setItem(i, 2, QTableWidgetItem(str(box['y'])))
            self.roi_table.setItem(i, 3, QTableWidgetItem(str(box['w'])))
            self.roi_table.setItem(i, 4, QTableWidgetItem(str(box['h'])))
            
            # Make name column read-only
            self.roi_table.item(i, 0).setFlags(Qt.ItemIsEnabled)
        
        self.roi_table.blockSignals(False)
    
    def update_display(self):
        """Update the display with ROI boxes drawn"""
        if self.frame is None:
            return
        
        # Create display frame
        if len(self.frame.shape) == 2:
            self.display_frame = cv2.cvtColor(self.frame, cv2.COLOR_GRAY2BGR)
        else:
            self.display_frame = self.frame.copy()
        
        # Draw ROI boxes
        for i, box in enumerate(self.roi_boxes):
            x, y, w, h = box['x'], box['y'], box['w'], box['h']
            color = box['color']
            
            # Draw rectangle
            thickness = 3 if i == self.selected_box else 2
            cv2.rectangle(self.display_frame, (x, y), (x + w, y + h), color, thickness)
            
            # Draw corner handles for selected box
            if i == self.selected_box:
                handle_size = 8
                # Top-left
                cv2.circle(self.display_frame, (x, y), handle_size, color, -1)
                # Top-right
                cv2.circle(self.display_frame, (x + w, y), handle_size, color, -1)
                # Bottom-left
                cv2.circle(self.display_frame, (x, y + h), handle_size, color, -1)
                # Bottom-right
                cv2.circle(self.display_frame, (x + w, y + h), handle_size, color, -1)
            
            # Draw label
            label = f"{box['name']}: {w}x{h}"
            cv2.putText(self.display_frame, label, (x, y - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        
        # Convert to QPixmap with zoom
        height, width, channel = self.display_frame.shape
        bytes_per_line = 3 * width
        qt_image = QImage(self.display_frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
        
        # Apply zoom
        scaled_width = int(width * self.scale_factor)
        scaled_height = int(height * self.scale_factor)
        qt_image = qt_image.scaled(scaled_width, scaled_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        
        pixmap = QPixmap.fromImage(qt_image)
        self.image_label.setPixmap(pixmap)
        self.image_label.resize(pixmap.size())
    
    def on_zoom_changed(self, value):
        """Handle zoom slider change"""
        self.scale_factor = value / 100.0
        self.zoom_label.setText(f"{value}%")
        self.update_display()
    
    def get_click_coords(self, event):
        """Convert click position to image coordinates"""
        if self.display_frame is None:
            return None, None
        
        # Get click position relative to label
        x = event.pos().x()
        y = event.pos().y()
        
        # Convert to image coordinates (account for zoom)
        img_x = int(x / self.scale_factor)
        img_y = int(y / self.scale_factor)
        
        return img_x, img_y
    
    def on_mouse_press(self, event):
        """Handle mouse press - start drag"""
        img_x, img_y = self.get_click_coords(event)
        if img_x is None:
            return
        
        # Check if clicking on a box
        for i, box in enumerate(self.roi_boxes):
            x, y, w, h = box['x'], box['y'], box['w'], box['h']
            
            # Check corners first (resize handles)
            handle_size = 10
            if abs(img_x - x) < handle_size and abs(img_y - y) < handle_size:
                self.selected_box = i
                self.drag_mode = 'resize_tl'
                self.drag_start_pos = (img_x, img_y)
                self.drag_start_box = (x, y, w, h)
                return
            elif abs(img_x - (x + w)) < handle_size and abs(img_y - y) < handle_size:
                self.selected_box = i
                self.drag_mode = 'resize_tr'
                self.drag_start_pos = (img_x, img_y)
                self.drag_start_box = (x, y, w, h)
                return
            elif abs(img_x - x) < handle_size and abs(img_y - (y + h)) < handle_size:
                self.selected_box = i
                self.drag_mode = 'resize_bl'
                self.drag_start_pos = (img_x, img_y)
                self.drag_start_box = (x, y, w, h)
                return
            elif abs(img_x - (x + w)) < handle_size and abs(img_y - (y + h)) < handle_size:
                self.selected_box = i
                self.drag_mode = 'resize_br'
                self.drag_start_pos = (img_x, img_y)
                self.drag_start_box = (x, y, w, h)
                return
            
            # Check if inside box (move mode)
            elif x <= img_x <= x + w and y <= img_y <= y + h:
                self.selected_box = i
                self.drag_mode = 'move'
                self.drag_start_pos = (img_x, img_y)
                self.drag_start_box = (x, y, w, h)
                self.update_display()
                return
        
        # Clicked outside all boxes - deselect
        self.selected_box = None
        self.update_display()
    
    def on_mouse_move(self, event):
        """Handle mouse move - drag box or resize"""
        if self.drag_mode is None or self.selected_box is None:
            # Change cursor based on hover position
            img_x, img_y = self.get_click_coords(event)
            if img_x is None:
                return
            
            for box in self.roi_boxes:
                x, y, w, h = box['x'], box['y'], box['w'], box['h']
                handle_size = 10
                
                # Check corners
                if abs(img_x - x) < handle_size and abs(img_y - y) < handle_size:
                    self.image_label.setCursor(Qt.SizeFDiagCursor)
                    return
                elif abs(img_x - (x + w)) < handle_size and abs(img_y - (y + h)) < handle_size:
                    self.image_label.setCursor(Qt.SizeFDiagCursor)
                    return
                elif abs(img_x - (x + w)) < handle_size and abs(img_y - y) < handle_size:
                    self.image_label.setCursor(Qt.SizeBDiagCursor)
                    return
                elif abs(img_x - x) < handle_size and abs(img_y - (y + h)) < handle_size:
                    self.image_label.setCursor(Qt.SizeBDiagCursor)
                    return
                elif x <= img_x <= x + w and y <= img_y <= y + h:
                    self.image_label.setCursor(Qt.SizeAllCursor)
                    return
            
            self.image_label.setCursor(Qt.ArrowCursor)
            return
        
        # Dragging
        img_x, img_y = self.get_click_coords(event)
        if img_x is None:
            return
        
        dx = img_x - self.drag_start_pos[0]
        dy = img_y - self.drag_start_pos[1]
        
        box = self.roi_boxes[self.selected_box]
        start_x, start_y, start_w, start_h = self.drag_start_box
        
        if self.drag_mode == 'move':
            box['x'] = max(0, start_x + dx)
            box['y'] = max(0, start_y + dy)
        elif self.drag_mode == 'resize_tl':
            new_x = start_x + dx
            new_y = start_y + dy
            box['x'] = max(0, new_x)
            box['y'] = max(0, new_y)
            box['w'] = start_w + (start_x - box['x'])
            box['h'] = start_h + (start_y - box['y'])
        elif self.drag_mode == 'resize_tr':
            box['y'] = max(0, start_y + dy)
            box['w'] = max(10, start_w + dx)
            box['h'] = start_h + (start_y - box['y'])
        elif self.drag_mode == 'resize_bl':
            box['x'] = max(0, start_x + dx)
            box['w'] = start_w + (start_x - box['x'])
            box['h'] = max(10, start_h + dy)
        elif self.drag_mode == 'resize_br':
            box['w'] = max(10, start_w + dx)
            box['h'] = max(10, start_h + dy)
        
        # Ensure minimum size
        box['w'] = max(20, box['w'])
        box['h'] = max(20, box['h'])
        
        self.update_display()
        self.update_roi_table()
    
    def on_mouse_release(self, event):
        """Handle mouse release - end drag"""
        self.drag_mode = None
        self.drag_start_pos = None
        self.drag_start_box = None
    
    def on_table_cell_changed(self, row, col):
        """Handle manual table edit"""
        if col == 0:  # Name column is read-only
            return
        
        try:
            value = int(self.roi_table.item(row, col).text())
            if col == 1:
                self.roi_boxes[row]['x'] = max(0, value)
            elif col == 2:
                self.roi_boxes[row]['y'] = max(0, value)
            elif col == 3:
                self.roi_boxes[row]['w'] = max(20, value)
            elif col == 4:
                self.roi_boxes[row]['h'] = max(20, value)
            
            self.update_display()
        except ValueError:
            self.update_roi_table()  # Reset invalid value
    
    def save_roi_settings(self):
        """Save ROI settings to .env file and apply immediately"""
        try:
            env_path = Path(".env")
            
            if not env_path.exists():
                QMessageBox.warning(self, "Warning", 
                    "⚠️ .env file not found!\n\n"
                    "Cannot save ROI settings.")
                return
            
            # Read current .env
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Track which settings we updated
            updated_count = 0
            
            # Update ROI values in .env
            for box in self.roi_boxes:
                prefix = box['setting_prefix']
                for i, line in enumerate(lines):
                    if line.startswith(f"{prefix}_X="):
                        lines[i] = f"{prefix}_X={box['x']}\n"
                        updated_count += 1
                    elif line.startswith(f"{prefix}_Y="):
                        lines[i] = f"{prefix}_Y={box['y']}\n"
                        updated_count += 1
                    elif line.startswith(f"{prefix}_W="):
                        lines[i] = f"{prefix}_W={box['w']}\n"
                        updated_count += 1
                    elif line.startswith(f"{prefix}_H="):
                        lines[i] = f"{prefix}_H={box['h']}\n"
                        updated_count += 1
            
            # Write back to .env
            with open(env_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
            # Also update config.py for reference (optional but good for consistency)
            try:
                config_path = Path("app/core/config.py")
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_lines = f.readlines()
                    
                    for box in self.roi_boxes:
                        prefix = box['setting_prefix']
                        for i, line in enumerate(config_lines):
                            if f"{prefix}_X:" in line and "int" in line:
                                config_lines[i] = f"    {prefix}_X: int = {box['x']}\n"
                            elif f"{prefix}_Y:" in line and "int" in line:
                                config_lines[i] = f"    {prefix}_Y: int = {box['y']}\n"
                            elif f"{prefix}_W:" in line and "int" in line:
                                config_lines[i] = f"    {prefix}_W: int = {box['w']}\n"
                            elif f"{prefix}_H:" in line and "int" in line:
                                config_lines[i] = f"    {prefix}_H: int = {box['h']}\n"
                    
                    with open(config_path, 'w', encoding='utf-8') as f:
                        f.writelines(config_lines)
            except Exception as e:
                print(f"Note: Could not update config.py: {e}")
            
            # Show success message with live reload option
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Information)
            msg.setWindowTitle("Settings Saved")
            msg.setText(
                f"✅ ROI settings saved successfully!\n\n"
                f"Updated {updated_count} coordinates in .env file.\n\n"
                f"Changes will be applied when you close this dialog."
            )
            msg.setInformativeText(
                "The new ROI coordinates will be loaded automatically.\n"
                "Restart required!"
            )
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()
            
            self.accept()  # Close dialog
            
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Save error: {error_trace}")
            QMessageBox.critical(self, "Error", 
                f"❌ Failed to save settings:\n\n{str(e)}\n\n"
                f"Check console for details.")
    
    def reset_to_defaults(self):
        """Reset ROI boxes to default values"""
        reply = QMessageBox.question(self, "Reset ROI",
            "⚠️ Reset all ROI regions to default values?\n\n"
            "This will restore the original coordinates.\n"
            "(Values will be updated in the editor only,\n"
            "you still need to click Save to apply them.)",
            QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            # Default values (from your config.py)
            defaults = {
                'ROI_ANGLE1': (101, 434, 139, 81),
                'ROI_WEIGHT1': (56, 333, 217, 90),
                'ROI_ANGLE2': (445, 417, 106, 57),
                'ROI_WEIGHT2': (420, 324, 165, 78)
            }
            
            for box in self.roi_boxes:
                prefix = box['setting_prefix']
                if prefix in defaults:
                    x, y, w, h = defaults[prefix]
                    box['x'] = x
                    box['y'] = y
                    box['w'] = w
                    box['h'] = h
            
            self.update_roi_table()
            self.update_display()
            
            QMessageBox.information(self, "Reset Complete",
                "✅ ROI regions reset to defaults!\n\n"
                "Click 'Save ROI Settings' to apply these changes.")
    
    def test_ocr(self):
        """Test OCR on current ROI regions"""
        if self.frame is None:
            QMessageBox.warning(self, "No Frame", 
                "❌ No camera frame available for testing.\n\n"
                "Please ensure the camera is connected.")
            return
        
        results = []
        for box in self.roi_boxes:
            x, y, w, h = box['x'], box['y'], box['w'], box['h']
            
            # Validate coordinates
            if y + h > self.frame.shape[0] or x + w > self.frame.shape[1]:
                results.append(f"{box['name']}: ERROR - Out of bounds!")
                continue
                
            roi = self.frame[y:y+h, x:x+w]
            
            # Run OCR
            try:
                value, confidence = ocr_service.extract_numeric_value(roi)
                if value is not None:
                    results.append(f"{box['name']}: {value} (confidence: {confidence:.1%})")
                else:
                    results.append(f"{box['name']}: No value detected (confidence: {confidence:.1%})")
            except Exception as e:
                results.append(f"{box['name']}: ERROR - {str(e)}")
        
        QMessageBox.information(self, "OCR Test Results",
            "🧪 OCR Test Results:\n\n" + "\n".join(results) + "\n\n"
            "These are live OCR readings from the current\n"
            "camera frame using the ROI coordinates shown.")


class ClickableLabel(QLabel):
    """QLabel that accepts mouse events"""
    pass


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("HMI Balance Machine OCR System - Professional Edition with HW")
    app.setApplicationVersion("2.0.1")
    app.setOrganizationName("Industrial Excellence Solutions")
    window = HMIDesktopApp()
    window.showFullScreen()
    
    # Run application
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()