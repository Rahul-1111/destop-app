import datetime
import json
import logging
import os
from typing import Optional, Tuple
from zebra import Zebra
import qrcode

PRINTER_NAME = "TSC TE210"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "Qr")
STATE_FILE = os.path.join(BASE_DIR, "serial_state.json")
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clear_old_qr_codes() -> None:
    today_str = datetime.datetime.now().strftime("%d%m%y")
    yesterday_str = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%d%m%y")
    for filename in os.listdir(OUTPUT_DIR):
        if today_str not in filename and yesterday_str not in filename:
            try:
                os.remove(os.path.join(OUTPUT_DIR, filename))
                logger.info(f"Deleted old file: {filename}")
            except Exception as e:
                logger.error(f"Error deleting file {filename}: {e}")

def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"month": datetime.datetime.now().strftime("%m%y"), "serial": 0, "last_part": "X"}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        logger.warning("Could not read state file; starting fresh.")
        return {"month": datetime.datetime.now().strftime("%m%y"), "serial": 0, "last_part": "X"}

def _save_state(month: str, serial: int, part: str) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"month": month, "serial": serial, "last_part": part}, f)
    except Exception as e:
        logger.error(f"Failed to save state file: {e}")

def get_current_serial_and_part(current_part: Optional[str] = None) -> Tuple[str, str]:
    state = _load_state()
    month_now = datetime.datetime.now().strftime("%m%y")
    part_clean = (current_part or "").strip().upper()
    if not part_clean:
        part_clean = state.get("last_part", "X") or "X"
    serial = 1 if state.get("month") != month_now else int(state.get("serial", 0))
    return str(serial).zfill(5), part_clean

def increment_serial(part: Optional[str] = None):
    state = _load_state()
    month_now = datetime.datetime.now().strftime("%m%y")
    part_clean = (part or state.get("last_part", "X")).strip().upper()
    if state.get("month") != month_now:
        new_serial = 1
    else:
        new_serial = int(state.get("serial", 0)) + 1
    _save_state(month_now, new_serial, part_clean)

def get_available_printers() -> list:
    try:
        z = Zebra()
        printers = z.getqueues()
        logger.info(f"Available printers: {printers}")
        return printers
    except Exception as e:
        logger.error(f"Error getting printer list: {e}")
        return []

def generate_zpl_data_print(qr_data: str) -> str:
    """Generate ZPL that prints the same QR data as saved image: serialpart;left_angle;left_weight;right_angle;right_weight"""
    return f"""
^XA
^MD20
^PW400
^LL300
^FO180,60^BQN,2,2
^FDLA,{qr_data}^FS
^PQ1,0,1,Y
^XZ
"""

def save_qr_image(qr_value: str, angle1: str, weight1: str, angle2: str, weight2: str) -> str:
    try:
        # Only values, no text: serialpart;left_angle;left_weight;right_angle;right_weight
        qr_data = f"{qr_value};{angle1};{weight1};{angle2};{weight2}"
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,
            border=2,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        file_path = os.path.join(OUTPUT_DIR, "current_qr.png")
        img.save(file_path)
        logger.info(f"QR image updated: {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"Error saving QR image: {e}")
        return ""

def print_zpl(zpl_command: str) -> bool:
    try:
        z = Zebra()
        printers = z.getqueues()
        printer_to_use = PRINTER_NAME if PRINTER_NAME in printers else (printers[0] if printers else None)
        if not printer_to_use:
            logger.error("No printers found.")
            return False
        if printer_to_use != PRINTER_NAME:
            logger.warning(f"Configured printer '{PRINTER_NAME}' not found. Using fallback: {printer_to_use}")
        z.setqueue(printer_to_use)
        z.output(zpl_command)
        logger.info(f"Printed label on '{printer_to_use}'.")
        return True
    except Exception as e:
        logger.error(f"Printer error: {e}")
        try:
            fname = f"label_{datetime.datetime.now():%Y%m%d_%H%M%S}.zpl"
            path = os.path.join(OUTPUT_DIR, fname)
            with open(path, "w") as f:
                f.write(zpl_command)
            logger.info(f"ZPL saved to file: {path}")
        except Exception as fe:
            logger.error(f"Could not save fallback ZPL: {fe}")
        return False

def print_balance_readings(
    part: Optional[str] = None,
    angle1: Optional[float] = None,
    weight1: Optional[float] = None,
    angle2: Optional[float] = None,
    weight2: Optional[float] = None,
) -> Tuple[bool, str, str]:
    """
    Print QR with same data as saved image:
    serialpart;left_angle;left_weight;right_angle;right_weight
    Both printer and saved image will have identical QR data
    """
    try:
        clear_old_qr_codes()
        now = datetime.datetime.now()
        serial, part_code = get_current_serial_and_part(part)
        qr_value = f"{serial}{part_code}"

        angle1_str = f"{angle1:.2f}" if angle1 is not None else "N/A"
        weight1_str = f"{weight1:.3f}" if weight1 is not None else "N/A"
        angle2_str = f"{angle2:.2f}" if angle2 is not None else "N/A"
        weight2_str = f"{weight2:.3f}" if weight2 is not None else "N/A"

        # Create the same QR data format for both printer and saved image
        qr_data = f"{qr_value};{angle1_str};{weight1_str};{angle2_str};{weight2_str}"

        logger.info(
            f"Printing QR with data: {qr_data} - "
            f"Part: {part_code}, Serial: {serial}, "
            f"Left Angle: {angle1_str}, Left Weight: {weight1_str}, "
            f"Right Angle: {angle2_str}, Right Weight: {weight2_str}"
        )

        # PRINTER: Use same QR data format as saved image
        zpl = generate_zpl_data_print(qr_data)
        success = print_zpl(zpl)

        # SAVED IMAGE: Use same QR data format as printer
        qr_image_path = save_qr_image(qr_value, angle1_str, weight1_str, angle2_str, weight2_str)

        if success:
            increment_serial(part)
            logger.info(f"✅ Label printed and QR updated with same data at {qr_image_path}")
        else:
            logger.error(f"❌ Print failed for {qr_data}")

        return success, qr_value, qr_image_path
    except Exception as e:
        logger.error(f"Print balance readings failed: {e}")
        return False, "", ""
