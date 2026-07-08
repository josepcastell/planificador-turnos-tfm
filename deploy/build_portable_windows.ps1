#requires -version 5
<#
.SYNOPSIS
  Construeix un paquet PORTABLE de PAC3_turnos per a Windows.

.DESCRIPTION
  Crea una carpeta autonoma que NO necessita instal.lacio ni permisos
  d'administrador a l'ordinador de desti (la feina). Conte:

    PAC3_turnos_portable\
      python\     Python 3.13 "embeddable" (no s'instal.la)
      app\        el codi de l'aplicacio (app.py, src, data, ...)
      run.bat     engegador (doble clic): obre l'app al navegador

  Copia tota la carpeta (o el .zip amb -Zip) a l'ordinador de la feina
  (per USB) i fes doble clic a run.bat. A la maquina de desti NO cal
  internet ni instal.lar res.

  Aquest script s'ha d'executar UN COP en un Windows AMB internet (p.ex.
  el de desenvolupament). Baixa el Python embeddable i les dependencies
  (rodes/wheels de Windows) i ho deixa tot autocontingut.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\build_portable_windows.ps1
  powershell -ExecutionPolicy Bypass -File deploy\build_portable_windows.ps1 -Zip
#>
[CmdletBinding()]
param(
  # Carpeta on crear el paquet (per defecte: l'Escriptori).
  [string]$OutDir = (Join-Path $env:USERPROFILE 'Desktop'),
  # Versio de Python embeddable (ha de coincidir amb la de desenvolupament).
  [string]$PyVersion = '3.13.5',
  # Si s'indica, crea tambe un .zip del paquet.
  [switch]$Zip
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# El repo es la carpeta pare d'aquest script (deploy\..).
$repo = Split-Path -Parent $PSScriptRoot
$bundleName = 'PAC3_turnos_portable'
$bundle = Join-Path $OutDir $bundleName
$pyDir  = Join-Path $bundle 'python'
$appDir = Join-Path $bundle 'app'
$verNoDot = (($PyVersion -split '\.')[0..1]) -join ''   # 3.13.5 -> 313

Write-Host "==> Repo d'origen : $repo"
Write-Host "==> Paquet de sortida: $bundle"

if (Test-Path $bundle) { Remove-Item $bundle -Recurse -Force }
New-Item -ItemType Directory -Force -Path $pyDir, $appDir | Out-Null

# ---------------------------------------------------------------------------
# 1) Python "embeddable" (portable, sense instal.lacio)
# ---------------------------------------------------------------------------
$embZip = Join-Path $env:TEMP "python-$PyVersion-embed-amd64.zip"
$embUrl = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip"
Write-Host "==> Baixant Python embeddable $PyVersion ..."
Invoke-WebRequest -Uri $embUrl -OutFile $embZip
Expand-Archive -Path $embZip -DestinationPath $pyDir -Force

# 2) Habilitar 'site' i site-packages al fitxer ._pth (cal per a pip i imports)
$pth = Get-ChildItem $pyDir -Filter '*._pth' | Select-Object -First 1
if (-not $pth) { throw "No s'ha trobat el fitxer ._pth a $pyDir" }
@"
python$verNoDot.zip
.
..\app
Lib\site-packages

import site
"@ | Set-Content -Encoding ascii $pth.FullName

# ---------------------------------------------------------------------------
# 3) pip (bootstrap amb get-pip)
# ---------------------------------------------------------------------------
$py = Join-Path $pyDir 'python.exe'
$getpip = Join-Path $env:TEMP 'get-pip.py'
Write-Host "==> Baixant get-pip ..."
Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getpip
& $py $getpip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip ha fallat (codi $LASTEXITCODE)" }

# ---------------------------------------------------------------------------
# 4) Dependencies (rodes de Windows, des de requirements.txt)
# ---------------------------------------------------------------------------
$req = Join-Path $repo 'requirements.txt'
Write-Host "==> Instal.lant dependencies des de requirements.txt ..."
& $py -m pip install --no-warn-script-location -r $req
if ($LASTEXITCODE -ne 0) { throw "pip install ha fallat (codi $LASTEXITCODE)" }

# ---------------------------------------------------------------------------
# 5) Copiar l'aplicacio (sense artefactes ni dades de sessio)
# ---------------------------------------------------------------------------
Write-Host "==> Copiant l'aplicacio ..."
foreach ($item in @('app.py', 'requirements.txt', 'VERSION', 'src')) {
  $srcPath = Join-Path $repo $item
  if (Test-Path $srcPath) {
    Copy-Item $srcPath -Destination $appDir -Recurse -Force
  } else {
    Write-Warning "No existeix $srcPath (s'omet)"
  }
}
# CONFIDENCIALITAT: de data/ nomes es copien les CAPÇALERES dels CSV
# (0 files de dades). MAI es copien dades reals del servei, backups
# (.bak), uploads, raw ni derived.
$dataSrc = Join-Path $repo 'data'
$dataDst = Join-Path $appDir 'data'
if (Test-Path $dataSrc) {
  Get-ChildItem $dataSrc -Recurse -File -Filter '*.csv' | ForEach-Object {
    $rel = $_.FullName.Substring($dataSrc.Length).TrimStart('\', '/')
    if ($rel -match '\.bak|uploads|raw[\\/]|derived[\\/]|before_') { return }
    $destFile = Join-Path $dataDst $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $destFile) | Out-Null
    Get-Content $_.FullName -TotalCount 1 | Set-Content -Encoding utf8 -Path $destFile
  }
}
# Comprovacio de seguretat: cap CSV del paquet pot tenir mes d'1 linia.
$leaky = Get-ChildItem $dataDst -Recurse -File -Filter '*.csv' -ErrorAction SilentlyContinue |
  Where-Object { (Get-Content $_.FullName | Measure-Object -Line).Lines -gt 1 }
if ($leaky) { throw "ATURAT: CSV amb dades dins el paquet: $($leaky.FullName -join ', ')" }
# Neteja __pycache__ que s'hagin copiat.
Get-ChildItem $appDir -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force
# Carpeta de sortides (l'app hi escriu en temps d'execucio).
New-Item -ItemType Directory -Force -Path (Join-Path $appDir 'outputs') | Out-Null
# PDFs autocontinguts (els llançadors hi apunten via PAC3_PDF_OUTPUT_DIR).
New-Item -ItemType Directory -Force -Path (Join-Path $bundle 'dades\PDFs') | Out-Null

# ---------------------------------------------------------------------------
# 6) Engegador run.bat (doble clic)
# ---------------------------------------------------------------------------
$runBat = @'
@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%app"
set "STREAMLIT_BROWSER_GATHERUSAGESTATS=false"
set "STREAMLIT_SERVER_PORT=8501"
rem Nomes accessible des d'aquest PC (mai des de la xarxa).
set "STREAMLIT_SERVER_ADDRESS=127.0.0.1"
rem UTF-8 al Python embegut (evita errors d'encoding als logs del solver).
set "PYTHONUTF8=1"
rem PDFs autocontinguts dins del paquet.
set "PAC3_PDF_OUTPUT_DIR=%ROOT%dades\PDFs"
set "PAC3_DESKTOP_DIR=%ROOT%dades\PDFs"

rem Evita la pregunta de l'email al primer arrencada de Streamlit.
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
  >"%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >>"%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo.
echo  PAC3_turnos s'esta obrint al navegador (http://localhost:8501)...
echo  (No tanquis aquesta finestra mentre facis servir el programa.)
echo.
"%ROOT%python\python.exe" -m streamlit run app.py
echo.
echo  El programa s'ha aturat. Pots tancar aquesta finestra.
pause
'@
Set-Content -Encoding ascii -Path (Join-Path $bundle 'run.bat') -Value $runBat

# 6b) Aturador (allibera el port 8501) + llançador SENSE finestra (VBS).
#     L'usuari fa doble clic a Planificador.vbs: obre l'app al navegador sense
#     cap finestra de terminal. Per aturar-lo, botó "Tancar el programa" a l'app.
$stopBat = @'
@echo off
setlocal
set "ROOT=%~dp0"
rem Nomes mata el proces del port 8501 si es el python d'AQUEST paquet
rem (mai una altra app que casualment usi el mateix port).
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501 " ^| findstr LISTENING') do (
  for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "(Get-Process -Id %%a -ErrorAction SilentlyContinue).Path"`) do (
    if /I "%%p"=="%ROOT%python\python.exe" taskkill /F /PID %%a >nul 2>&1
  )
)
'@
Set-Content -Encoding ascii -Path (Join-Path $bundle '_stop.bat') -Value $stopBat

$launcherVbs = @'
Option Explicit
Dim sh, fso, root, home, credDir, credFile, f, env
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
home = sh.ExpandEnvironmentStrings("%USERPROFILE%")
credDir = home & "\.streamlit"
credFile = credDir & "\credentials.toml"
If Not fso.FolderExists(credDir) Then fso.CreateFolder(credDir)
If Not fso.FileExists(credFile) Then
  Set f = fso.CreateTextFile(credFile, True)
  f.WriteLine "[general]"
  f.WriteLine "email = " & Chr(34) & Chr(34)
  f.Close
End If
' Allibera el port si havia quedat una instancia oberta (nomes el nostre python).
sh.Run Chr(34) & root & "\_stop.bat" & Chr(34), 0, True
' Entorn del proces fill: UTF-8 + PDFs autocontinguts dins del paquet.
Set env = sh.Environment("PROCESS")
env("PYTHONUTF8") = "1"
env("PAC3_PDF_OUTPUT_DIR") = root & "\dades\PDFs"
env("PAC3_DESKTOP_DIR") = root & "\dades\PDFs"
sh.CurrentDirectory = root & "\app"
' 0 = finestra oculta; Streamlit obre el navegador sol quan esta a punt.
' Nomes accessible des d'aquest PC (127.0.0.1), mai des de la xarxa.
sh.Run Chr(34) & root & "\python\python.exe" & Chr(34) & " -m streamlit run app.py --browser.gatherUsageStats=false --server.address=127.0.0.1 --server.port=8501", 0, False
'@
Set-Content -Encoding ascii -Path (Join-Path $bundle 'Planificador.vbs') -Value $launcherVbs

# ---------------------------------------------------------------------------
# 7) (Opcional) zip
# ---------------------------------------------------------------------------
Write-Host "==> Paquet creat: $bundle"
if ($Zip) {
  $zipPath = "$bundle.zip"
  if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
  Write-Host "==> Comprimint a $zipPath ..."
  Compress-Archive -Path $bundle -DestinationPath $zipPath
  Write-Host "==> Zip creat: $zipPath"
}
Write-Host ""
Write-Host "LLEST. Copia la carpeta (o el .zip) a l'ordinador de la feina i"
Write-Host "fes doble clic a Planificador.vbs (obre sense finestra de terminal)."
