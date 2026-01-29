
import os, sys

def _cfg():
    try:
        import pytesseract
    except Exception:
        return

    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        exe = os.path.join(sys._MEIPASS, 'tesseract', 'tesseract.exe')
        if os.path.exists(exe):
            pytesseract.pytesseract.tesseract_cmd = exe
            return

    for p in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if os.path.exists(p):
            pytesseract.pytesseract.tesseract_cmd = p
            return

_cfg()
