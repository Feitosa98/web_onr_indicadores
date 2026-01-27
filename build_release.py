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
    
    server_exe = os.path.join(DIST_DIR, "Indicador Server.exe")
    if not os.path.exists(server_exe):
        # Fallback to dir check just in case spec changes
        if os.path.exists(SERVER_DIST):
             server_exe = None # It is a dir
        else:
             print(f"Error: {server_exe} not found!")
             return

    with zipfile.ZipFile(PAYLOAD_ZIP, 'w', zipfile.ZIP_DEFLATED) as zipf:
        if server_exe:
            # It's a file. Rename to match what setup_installer expects
            zipf.write(server_exe, "IndicadorRealServer.exe")
        else:
            # It's a directory
            for root, dirs, files in os.walk(SERVER_DIST):
                for file in files:
                    abs_path = os.path.join(root, file)
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
