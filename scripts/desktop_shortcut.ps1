# Puts a "Perfect Wallpaper" shortcut on the desktop that runs the app from this
# folder with no console window. Run it again if the folder moves.
#
#   powershell -ExecutionPolicy Bypass -File scripts\desktop_shortcut.ps1

$here = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $here ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Error "No .venv in $here yet. Set it up first (see README, Building from source)."
    exit 1
}

$link = Join-Path ([Environment]::GetFolderPath("Desktop")) "Perfect Wallpaper.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $pythonw              # pythonw: no black console window
$shortcut.Arguments = "-m perfect_wallpaper"
$shortcut.WorkingDirectory = $here
$shortcut.IconLocation = (Join-Path $here "assets\icon.ico") + ",0"
$shortcut.Description = "Perfect Wallpaper: enlarge a picture with AI and fit it to your screen"
$shortcut.Save()
Write-Host "Shortcut ready: $link"
