@echo off
echo ===================================================
echo     GERADOR DE INSTALADOR MESTRE (BUNDLE)
echo ===================================================
echo.
echo 1. Preparando arquivos...
if exist "staging" rmdir /s /q "staging"
mkdir "staging"

if not exist "dist\Indicador Server.exe" (
    echo [ERRO] 'Indicador Server.exe' nao encontrado na pasta dist!
    echo Compile o servidor primeiro.
    pause
    exit
)
copy "dist\Indicador Server.exe" "staging\"
copy "dist\Setup Wizard.exe" "staging\"

echo.
echo 2. Verificando Assets...
if not exist "installer_assets" (
    echo [ERRO] A pasta 'installer_assets' nao existe!
    pause
    exit
)
echo Verificando arquivos em installer_assets...
dir installer_assets

echo.
echo 3. Compilando 'Instalador Completo v6.exe'...
echo Isso pode levar alguns minutos...
pyinstaller --noconfirm --onefile --windowed --name "Instalador Completo v6" --icon "icon.ico" --add-data "staging;dist_bundle" --add-data "installer_assets;installer_assets" master_setup.py

echo.
echo Limpando staging...
rmdir /s /q "staging"

echo.
echo ===================================================
echo                  CONCLUIDO!
echo ===================================================
echo O arquivo final esta em: dist/Instalador Completo.exe
echo.
pause
