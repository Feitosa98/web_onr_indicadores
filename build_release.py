import os
import shutil
import subprocess
import zipfile
import sys

def run_command(cmd, cwd=None):
    print(f"Executing: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=cwd)

def main():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DIST_DIR = os.path.join(BASE_DIR, "dist")
    BUILD_DIR = os.path.join(BASE_DIR, "build")
    SERVER_DIST = os.path.join(DIST_DIR, "Indicador Server")
    PAYLOAD_ZIP = os.path.join(BASE_DIR, "payload.zip")
    INSTALLER_NAME = "Instalador_Indicador_Real"

    # 1. Clean previous builds
    print("--- Cleaning up ---")
    if os.path.exists(DIST_DIR): shutil.rmtree(DIST_DIR)
    if os.path.exists(BUILD_DIR): shutil.rmtree(BUILD_DIR)
    if os.path.exists(PAYLOAD_ZIP): os.remove(PAYLOAD_ZIP)
    
    # 2. Build Server (Main App)
    print("--- Building Indicador Server ---")
    run_command(['pyinstaller', 'Indicador Server.spec', '--clean', '--noconfirm'])
    
    # 3. Create Payload Zip
    print("--- Creating payload.zip ---")
    if not os.path.exists(SERVER_DIST):
        print(f"Error: {SERVER_DIST} not found!")
        return

    with zipfile.ZipFile(PAYLOAD_ZIP, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(SERVER_DIST):
            for file in files:
                abs_path = os.path.join(root, file)
                # Rel path inside zip should be relative to SERVER_DIST
                # e.g. "imoveis_web.exe" not "Indicador Server/imoveis_web.exe"
                # Wait, if we extract to InstallDir, we want files directly there.
                rel_path = os.path.relpath(abs_path, SERVER_DIST)
                zipf.write(abs_path, rel_path)
    
    print(f"Payload created: {PAYLOAD_ZIP}")

    # 4. Build Installer (Bundling payload.zip)
    print("--- Building Installer ---")
    # We use --add-data to include payload.zip. 
    # On Windows separator is ;
    add_data_arg = f"payload.zip;."
    
    installer_cmd = [
        'pyinstaller',
        '--onefile',
        '--noconsole',
        '--name', INSTALLER_NAME,
        '--add-data', add_data_arg,
        '--icon', 'icon.ico',
        'setup_installer.py'
    ]
    run_command(installer_cmd)

    print("--- Build Complete ---")
    print(f"Installer available at: {os.path.join(DIST_DIR, INSTALLER_NAME + '.exe')}")

if __name__ == "__main__":
    main()
