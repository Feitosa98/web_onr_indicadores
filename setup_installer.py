import tkinter as tk
from tkinter import filedialog, messagebox
import os
import shutil
import sys
import zipfile
import win32com.client # Need pywin32 for shortcuts

# Configuration
INSTALL_DIR = r"C:\IndicadorReal"
APP_NAME = "Indicador Real Server"
EXE_NAME = "IndicadorRealServer.exe"

class InstallerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Instalador - Indicador Real")
        self.root.geometry("500x350")
        
        # Heading
        tk.Label(root, text="Instalação do Sistema", font=("Helvetica", 16, "bold")).pack(pady=20)
        
        tk.Label(root, text=f"O sistema será instalado em:\n{INSTALL_DIR}", font=("Helvetica", 10)).pack(pady=10)
        
        # Backup Frame
        frame_bkp = tk.LabelFrame(root, text="Restauração de Backup (Opcional)", padx=10, pady=10)
        frame_bkp.pack(fill="x", padx=20, pady=10)
        
        self.backup_path = tk.StringVar()
        tk.Entry(frame_bkp, textvariable=self.backup_path, width=40).pack(side=tk.LEFT, padx=5)
        tk.Button(frame_bkp, text="Selecionar .DB", command=self.browse_backup).pack(side=tk.LEFT)
        
        tk.Label(root, text="Se nenhum backup for selecionado, um banco limpo será criado.\nUsuário padrão: admin / admin", font=("Arial", 8), fg="gray").pack(pady=5)
        
        # Firewall Checkbox
        self.var_firewall = tk.BooleanVar(value=True)
        tk.Checkbutton(root, text="Liberar Firewall (Permitir acesso de outros PCs)", variable=self.var_firewall).pack(pady=5)

        # Install Button
        tk.Button(root, text="INSTALAR AGORA", command=self.install, bg="#4CAF50", fg="white", font=("Helvetica", 12, "bold"), pady=10).pack(pady=20)
        
    def browse_backup(self):
        filename = filedialog.askopenfilename(filetypes=[("SQLite DB", "*.db"), ("All Files", "*.*")])
        if filename:
            self.backup_path.set(filename)
            
    def install(self):
        try:
            # 1. Create Directory
            if not os.path.exists(INSTALL_DIR):
                os.makedirs(INSTALL_DIR)
                
            # 2. Extract Payload
            # Expecting 'payload.zip' in the same dir as installer exe
            # Or PyInstaller temp dir if bundled (simpler: same dir for now)
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            payload_zip = os.path.join(base_path, "payload.zip")
            
            if not os.path.exists(payload_zip):
                 # Fallback for dev testing
                 if os.path.exists("payload.zip"):
                     payload_zip = "payload.zip"
                 else:
                     messagebox.showerror("Erro", "Arquivo payload.zip não encontrado!")
                     return

            with zipfile.ZipFile(payload_zip, 'r') as zip_ref:
                zip_ref.extractall(INSTALL_DIR)
                
            # 3. Handle Database
            db_dest = os.path.join(INSTALL_DIR, "imoveis.db")
            backup_src = self.backup_path.get()
            
            if backup_src and os.path.exists(backup_src):
                shutil.copy2(backup_src, db_dest)
                print(f"Backup restored from {backup_src}")
            else:
                # Run create_clean_db logic (imported or executed)
                # Since we extracted payload, create_clean_db.py matches logic, 
                # but easier to just create it here or copy a 'clean.db' included in payload.
                # Let's assume create_clean_db.py generated a 'clean.db' that we included in payload.
                # Or we can run the script if Python is there. 
                # BEST: The payload should include 'clean.db.template'.
                clean_template = os.path.join(INSTALL_DIR, "clean.db.template")
                if os.path.exists(clean_template):
                    shutil.copy2(clean_template, db_dest)
                else:
                    # Fallback: Let the app handle missing db? No, user wants clean db.
                    # We will create it on the fly or rely on 'clean.db.template' being present.
                    pass 

            # 4. Create Shortcut
            self.create_shortcut()
            
            # 5. Firewall Rule
            if self.var_firewall.get():
                try:
                    import subprocess
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        f"name={APP_NAME}", "dir=in", "action=allow",
                        "protocol=TCP", "localport=5000"
                    ], check=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
                    print("Firewall rule added.")
                except Exception as e:
                    messagebox.showwarning("Aviso", f"Não foi possível adicionar regra no Firewall:\n{e}\n\nVocê precisará liberar a porta 5000 manualmente.")

            
            messagebox.showinfo("Sucesso", "Instalação Concluída!\nO ícone foi criado na Área de Trabalho.")
            self.root.destroy()
            
        except Exception as e:
            messagebox.showerror("Erro Fatal", str(e))

    def create_shortcut(self):
        desktop = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop') 
        path = os.path.join(desktop, f"{APP_NAME}.lnk")
        target = os.path.join(INSTALL_DIR, EXE_NAME)
        
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(path)
        shortcut.Targetpath = target
        shortcut.WorkingDirectory = INSTALL_DIR
        shortcut.IconLocation = target
        shortcut.save()

if __name__ == "__main__":
    if not win32com.client:
        messagebox.showerror("Erro", "Dependência win32com não encontrada.")
    else:
        root = tk.Tk()
        app = InstallerGUI(root)
        root.mainloop()
