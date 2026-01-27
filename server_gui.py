import tkinter as tk
from tkinter import messagebox
import threading
import sys
import os
import socket
import webbrowser
import time
import waitress
import pystray
from PIL import Image
from pystray import MenuItem as item

# Ensure we can find the app module
# Ensure we can find the app module
if getattr(sys, 'frozen', False):
    # Running in PyInstaller Bundle
    sys.path.append(sys._MEIPASS)
else:
    # Running normally
    sys.path.append(os.getcwd())

# Import the Flask app
import logging

# Configure logging to file
logging.basicConfig(filename='server_error.log', level=logging.DEBUG, 
                    format='%(asctime)s %(levelname)s: %(message)s')

# DEBUG: Inspect Frozen Environment
if getattr(sys, 'frozen', False):
    try:
        logging.info(f"FROZEN MODE. MEIPASS: {sys._MEIPASS}")
        logging.info(f"SYS.PATH: {sys.path}")
        files = os.listdir(sys._MEIPASS)
        logging.info(f"MEIPASS FILES: {files}")
        
        # Check explicitly for imoveis_web
        if 'imoveis_web.py' in files or 'imoveis_web.pyc' in files:
            logging.info("imoveis_web file FOUND in MEIPASS.")
        else:
            logging.error("imoveis_web file NOT FOUND in MEIPASS.")
            
    except Exception as e:
        logging.error(f"Debug check failed: {e}")

# Redirect stderr to logging
class StreamToLogger(object):
    def __init__(self, logger, log_level=logging.ERROR):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())

    def flush(self):
        pass

sys.stderr = StreamToLogger(logging.getLogger('STDERR'), logging.ERROR)

# Import the Flask app
# Import the Flask app
from imoveis_web import app

# Explicit import to help PyInstaller find it (fixes ModuleNotFoundError)
try:
    from flask_wtf.csrf import CSRFProtect
except ImportError:
    pass

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

class ServerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Indicador Real - Servidor")
        self.root.geometry("400x250")
        self.root.configure(bg="#f0f0f0")
        
        # Determine paths for PyInstaller assets (Icon)
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.icon_path = os.path.join(base_dir, "icon.ico")
        if not os.path.exists(self.icon_path):
             # Fallback if icon.ico is not found (e.g. dev mode without conversion)
             # Try to start without, or use default
             self.icon_path = None

        # Set Window Icon
        if self.icon_path and os.path.exists(self.icon_path):
            try:
                self.root.iconbitmap(self.icon_path)
            except:
                pass

        # Center window
        self.center_window()

        # Handle Close (Minimize to Tray)
        self.root.protocol('WM_DELETE_WINDOW', self.minimize_to_tray)

        # Title Label
        tk.Label(root, text="Sistema Indicador Real", font=("Helvetica", 16, "bold"), bg="#f0f0f0", fg="#333").pack(pady=20)

        # Status Label
        self.status_var = tk.StringVar()
        self.status_var.set("Iniciando servidor...")
        self.lbl_status = tk.Label(root, textvariable=self.status_var, font=("Helvetica", 10), bg="#f0f0f0", fg="blue")
        self.lbl_status.pack(pady=10)

        # URL Label
        self.url_var = tk.StringVar()
        self.lbl_url = tk.Entry(root, textvariable=self.url_var, font=("Consolas", 12), justify="center", width=30, state="readonly")
        self.lbl_url.pack(pady=5)

        # Buttons
        btn_frame = tk.Frame(root, bg="#f0f0f0")
        btn_frame.pack(pady=20)

        tk.Button(btn_frame, text="Abrir no Navegador", command=self.open_browser, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=10, pady=5).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Esconder (Tray)", command=self.minimize_to_tray, bg="#FF9800", fg="white", font=("Arial", 10, "bold"), padx=10, pady=5).pack(side=tk.LEFT, padx=10)

        # Server Thread
        self.server_thread = threading.Thread(target=self.run_server, daemon=True)
        self.server_thread.start()
        
        # Check loop
        self.root.after(1000, self.check_status)

    def center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry('{}x{}+{}+{}'.format(width, height, x, y))

    def run_server(self):
        try:
            waitress.serve(app, host="0.0.0.0", port=5000, threads=6)
        except Exception as e:
            self.status_var.set(f"Erro: {e}")

    def check_status(self):
        ip = get_ip()
        url = f"http://{ip}:5000"
        self.url_var.set(url)
        self.status_var.set("Servidor Rodando Online")
        self.lbl_status.config(fg="green")

    def open_browser(self):
        webbrowser.open(self.url_var.get())

    def minimize_to_tray(self):
        self.root.withdraw()
        
        # Prepare image for tray
        if self.icon_path and os.path.exists(self.icon_path):
            image = Image.open(self.icon_path)
        else:
            # Create a fallback image (simple colored square)
            image = Image.new('RGB', (64, 64), color = (73, 109, 137))

        menu = (
             item('Indicador Real (Online)', lambda: None, enabled=False),
             item('Abrir Painel', self.restore_window),
             item('Abrir no Navegador', self.open_browser),
             item('Reiniciar Sistema', self.restart_program),
             item('Sair (Desligar)', self.quit_app)
        )
        
        self.tray_icon = pystray.Icon("name", image, "Indicador Real Server", menu)
        
        # Run tray loop in separate thread so it doesnt block? 
        # pystray run() is blocking. We can run it here, but we need to ensure tk mainloop is fine.
        # usually run_detached is strictly creating a thread.
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def restore_window(self):
        self.tray_icon.stop() # Stop tray
        self.root.after(0, self.root.deiconify)

    def restart_program(self):
        self.tray_icon.stop()
        self.root.destroy()
        # Restart
        python = sys.executable
        os.execl(python, python, *sys.argv)

    def quit_app(self):
        self.tray_icon.stop()
        self.root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    root = tk.Tk()
    app_gui = ServerGUI(root)
    root.mainloop()
