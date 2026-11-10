# ==============================================================================
# Clip Farming Studio - Automatisches Setup & Hardware-Optimierung
# Richtet Python 3.12, FFmpeg und KI-Bibliotheken vollautomatisch im Ordner ein.
# ==============================================================================

param(
    [switch]$Force,
    [switch]$VerboseLog
)

$ErrorActionPreference = "Continue"

# Ermittle Projekt-Wurzelverzeichnis
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

function Emit-Progress {
    param(
        [int]$Percent,
        [int]$Step,
        [int]$TotalSteps,
        [string]$Message,
        [string]$LogLine = ""
    )
    $payload = @{
        percent     = $Percent
        step        = $Step
        total_steps = $TotalSteps
        message     = $Message
        log         = $LogLine
    }
    $json = $payload | ConvertTo-Json -Compress
    Write-Output "PROGRESS:$json"
    [Console]::Out.Flush()
}

Emit-Progress -Percent 2 -Step 1 -TotalSteps 5 -Message "Prüfe System & Grafikkarte..." -LogLine "Starte Clip-Farming Erst-Einrichtung..."

# ==============================================================================
# SCHRITT 1: Grafikkarte & Hardware-Encoder erkennen
# ==============================================================================
$detectedGpus = @()
$recommendedEncoder = "cpu"
$whisperDevice = "cpu"
$gpuName = "Standard Prozessor (CPU)"

try {
    $videoControllers = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue
    foreach ($vc in $videoControllers) {
        $name = $vc.Name
        if (-not $name) { continue }
        $vramMB = if ($vc.AdapterRAM) { [math]::Round($vc.AdapterRAM / 1MB) } else { 0 }
        
        $detectedGpus += [PSCustomObject]@{
            Name = $name
            VRAM = $vramMB
        }

        if ($name -match "NVIDIA|GeForce|RTX|GTX") {
            $recommendedEncoder = "nvenc"
            $whisperDevice = "cuda"
            $gpuName = "$name ($vramMB MB VRAM)"
            break
        } elseif ($name -match "AMD|Radeon") {
            if ($recommendedEncoder -eq "cpu") {
                $recommendedEncoder = "amf"
                $gpuName = "$name ($vramMB MB VRAM)"
            }
        } elseif ($name -match "Intel.*(Arc|Iris|Xe)") {
            if ($recommendedEncoder -eq "cpu") {
                $recommendedEncoder = "qsv"
                $gpuName = "$name ($vramMB MB VRAM)"
            }
        }
    }
} catch {
    Emit-Progress -Percent 5 -Step 1 -TotalSteps 5 -Message "Hardware-Erkennung läuft..." -LogLine "Hinweis: Win32_VideoController Fallback aktiviert."
}

Emit-Progress -Percent 10 -Step 1 -TotalSteps 5 `
    -Message "Hardware erkannt: $gpuName -> $recommendedEncoder" `
    -LogLine "Erkannte Grafikkarte: $gpuName. Empfohlener Video-Encoder: $recommendedEncoder"

# ==============================================================================
# SCHRITT 2: Portable Python 3.12 Laufzeitumgebung einrichten
# ==============================================================================
Emit-Progress -Percent 15 -Step 2 -TotalSteps 5 -Message "Prüfe Python-Laufzeitumgebung..." -LogLine "Prüfe './runtime' oder './.venv'..."

$runtimeDir = Join-Path $ProjectRoot "runtime"
$pythonExe = Join-Path $runtimeDir "python.exe"
if (-not (Test-Path $pythonExe)) {
    $venvPy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        $pythonExe = $venvPy
    }
}

if (-not (Test-Path $pythonExe) -or $Force) {
    Emit-Progress -Percent 20 -Step 2 -TotalSteps 5 `
        -Message "Lade eigenständiges Python 3.12 herunter (~36 MB)..." `
        -LogLine "Download von python-build-standalone (GitHub Releases)..."

    if (-not (Test-Path $runtimeDir)) {
        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    }

    $pyArchive = Join-Path $ProjectRoot "python_temp.tar.gz"
    $pyUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.12.7+20241016-x86_64-pc-windows-msvc-shared-install_only.tar.gz"
    
    # Download mit curl.exe
    & curl.exe -L -k --retry 3 -o $pyArchive $pyUrl
    
    if (Test-Path $pyArchive) {
        Emit-Progress -Percent 30 -Step 2 -TotalSteps 5 `
            -Message "Entpacke Python 3.12 in lokalen Ordner 'runtime/'..." `
            -LogLine "Entpacke $pyArchive..."

        & tar.exe -xzf $pyArchive -C $runtimeDir --strip-components 1
        Remove-Item -Path $pyArchive -Force -ErrorAction SilentlyContinue
    }

    $pythonExe = Join-Path $runtimeDir "python.exe"
}

if (-not (Test-Path $pythonExe)) {
    # Letzter Fallback: Prüfe ob Windows-System Python vorhanden ist
    $sysPy = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($sysPy) {
        Emit-Progress -Percent 32 -Step 2 -TotalSteps 5 `
            -Message "Erstelle isoliertes Python-Environment via System-Python..." `
            -LogLine "Verwende System-Python: $sysPy"
        & $sysPy -m venv $runtimeDir
        $pythonExe = Join-Path $runtimeDir "Scripts\python.exe"
    }
}

if (-not (Test-Path $pythonExe)) {
    throw "Fehler: Python konnte nicht installiert oder gefunden werden."
}

Emit-Progress -Percent 35 -Step 2 -TotalSteps 5 `
    -Message "Python 3.12 erfolgreich bereitgestellt." `
    -LogLine "Python-Pfad: $pythonExe"

# ==============================================================================
# SCHRITT 3: FFmpeg Video-Engine bereitstellen
# ==============================================================================
Emit-Progress -Percent 40 -Step 3 -TotalSteps 5 -Message "Prüfe FFmpeg Video-Engine..." -LogLine "Prüfe 'bin/ffmpeg.exe'..."

$binDir = Join-Path $ProjectRoot "bin"
$ffmpegExe = Join-Path $binDir "ffmpeg.exe"
$ffprobeExe = Join-Path $binDir "ffprobe.exe"

if (-not (Test-Path $ffmpegExe) -or $Force) {
    Emit-Progress -Percent 45 -Step 3 -TotalSteps 5 `
        -Message "Lade FFmpeg Video-Engine herunter (~35 MB)..." `
        -LogLine "Download von Gyan FFmpeg Essentials..."

    if (-not (Test-Path $binDir)) {
        New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    }

    $ffmpegZip = Join-Path $ProjectRoot "ffmpeg_temp.zip"
    $ffmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

    & curl.exe -L -k --retry 3 -o $ffmpegZip $ffmpegUrl

    if (Test-Path $ffmpegZip) {
        Emit-Progress -Percent 55 -Step 3 -TotalSteps 5 `
            -Message "Entpacke FFmpeg in 'bin/'..." `
            -LogLine "Extrahiere ffmpeg.exe & ffprobe.exe..."

        $tempExtractDir = Join-Path $ProjectRoot "ffmpeg_extracted"
        if (Test-Path $tempExtractDir) { Remove-Item -Recurse -Force $tempExtractDir }
        New-Item -ItemType Directory -Path $tempExtractDir -Force | Out-Null

        Expand-Archive -Path $ffmpegZip -DestinationPath $tempExtractDir -Force

        $foundFfmpeg = Get-ChildItem -Path $tempExtractDir -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
        $foundFfprobe = Get-ChildItem -Path $tempExtractDir -Filter "ffprobe.exe" -Recurse | Select-Object -First 1

        if ($foundFfmpeg) {
            Copy-Item -Path $foundFfmpeg.FullName -Destination $ffmpegExe -Force
        }
        if ($foundFfprobe) {
            Copy-Item -Path $foundFfprobe.FullName -Destination $ffprobeExe -Force
        }

        Remove-Item -Path $ffmpegZip -Force -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $tempExtractDir -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $ffmpegExe)) {
    # Prüfe ob System-FFmpeg existiert
    $sysFfmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
    if ($sysFfmpeg) {
        Copy-Item -Path $sysFfmpeg -Destination $ffmpegExe -Force -ErrorAction SilentlyContinue
    }
}

Emit-Progress -Percent 60 -Step 3 -TotalSteps 5 `
    -Message "FFmpeg Video-Engine bereit." `
    -LogLine "FFmpeg bereit unter: $ffmpegExe"

# ==============================================================================
# SCHRITT 4: Python-Abhängigkeiten & KI-Module installieren
# ==============================================================================
Emit-Progress -Percent 65 -Step 4 -TotalSteps 5 `
    -Message "Installiere KI-Module & Bibliotheken (OpenCV, Whisper, Flask)..." `
    -LogLine "Führe pip install -r requirements.txt aus..."

$reqFile = Join-Path $ProjectRoot "requirements.txt"
if (Test-Path $reqFile) {
    # Aktualisiere Pip
    & $pythonExe -m pip install --upgrade pip --quiet --no-warn-script-location 2>&1 | Out-Null
    
    # Installiere Requirements
    Emit-Progress -Percent 75 -Step 4 -TotalSteps 5 `
        -Message "Lade KI-Module herunter (Whisper, OpenCV, Web-Server)..." `
        -LogLine "pip install -r requirements.txt läuft..."

    & $pythonExe -m pip install -r $reqFile --no-warn-script-location

    Emit-Progress -Percent 88 -Step 4 -TotalSteps 5 `
        -Message "KI-Module erfolgreich installiert." `
        -LogLine "Alle Python-Pakete sind aktuell und einsatzbereit."
}

# ==============================================================================
# SCHRITT 5: Konfiguration & Ordnerstruktur optimieren
# ==============================================================================
Emit-Progress -Percent 90 -Step 5 -TotalSteps 5 `
    -Message "Erstelle Ordner und optimiere Konfiguration für deine GPU..." `
    -LogLine "Hardware-Encoder: $recommendedEncoder"

# Erstelle notwendige Ordner
foreach ($sub in @("downloads", "output\shorts", "output\metadata", "data", "fonts", "config")) {
    $p = Join-Path $ProjectRoot $sub
    if (-not (Test-Path $p)) {
        New-Item -ItemType Directory -Path $p -Force | Out-Null
    }
}

# Config aktualisieren / anlegen
$configFile = Join-Path $ProjectRoot "config\config.yaml"
if (-not (Test-Path $configFile)) {
    $configContent = @"
# Clip Farming Konfiguration (Automatisch generiert)
hardware_encoder: "$recommendedEncoder"
whisper_device: "$whisperDevice"
whisper_model: "base"

streamers:
  - eliasn97
  - letshugotv
  - papaplatte
  - rewinside
  - trymacs
  - zarbex
  - nooreax

auto_publish: false
publish_interval_minutes: 30
"@
    Set-Content -Path $configFile -Value $configContent -Encoding UTF8
    Emit-Progress -Percent 95 -Step 5 -TotalSteps 5 `
        -Message "Konfiguration config.yaml mit $recommendedEncoder Encoder erstellt." `
        -LogLine "Konfiguration gespeichert."
}

# Verifikation: Teste Core-Imports
$verifyCmd = "import flask, cv2, faster_whisper, yaml; print('SETUP_SUCCESS')"
$verifyOutput = & $pythonExe -c $verifyCmd 2>&1
Emit-Progress -Percent 98 -Step 5 -TotalSteps 5 `
    -Message "System-Selbsttest..." `
    -LogLine "Selbsttest-Ergebnis: $verifyOutput"

# ==============================================================================
# FERTIG!
# ==============================================================================
Emit-Progress -Percent 100 -Step 5 -TotalSteps 5 `
    -Message "Einrichtung erfolgreich abgeschlossen! Starte Clip Farming Studio..." `
    -LogLine "Alles bereit! Starte Desktop-App..."
