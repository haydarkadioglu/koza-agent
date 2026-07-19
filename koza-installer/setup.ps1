Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# GUI Colors & Fonts
$BgColor = [System.Drawing.Color]::FromArgb(248, 247, 247)
$PanelColor = [System.Drawing.Color]::White
$PrimaryColor = [System.Drawing.Color]::FromArgb(0, 120, 215)
$TextColor = [System.Drawing.Color]::Black
$Font = New-Object System.Drawing.Font("Segoe UI", 10)
$TitleFont = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)

# Form Setup
$form = New-Object System.Windows.Forms.Form
$form.Text = "Koza Setup"
$form.Size = New-Object System.Drawing.Size(500, 400)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.BackColor = $BgColor
$form.Font = $Font

# Title Label
$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text = "Koza Kurulum Sihirbazi"
$lblTitle.Font = $TitleFont
$lblTitle.AutoSize = $true
$lblTitle.Location = New-Object System.Drawing.Point(20, 20)
$form.Controls.Add($lblTitle)

# Panel
$panel = New-Object System.Windows.Forms.Panel
$panel.BackColor = $PanelColor
$panel.Location = New-Object System.Drawing.Point(20, 60)
$panel.Size = New-Object System.Drawing.Size(440, 220)
$panel.BorderStyle = "FixedSingle"
$form.Controls.Add($panel)

# Language Label
$lblLang = New-Object System.Windows.Forms.Label
$lblLang.Text = "Dil (Language):"
$lblLang.Location = New-Object System.Drawing.Point(20, 20)
$lblLang.AutoSize = $true
$panel.Controls.Add($lblLang)

# Language ComboBox
$cmbLang = New-Object System.Windows.Forms.ComboBox
$cmbLang.Items.Add("Turkce")
$cmbLang.Items.Add("English")
$cmbLang.SelectedIndex = 0
$cmbLang.Location = New-Object System.Drawing.Point(20, 40)
$cmbLang.Size = New-Object System.Drawing.Size(400, 25)
$cmbLang.DropDownStyle = "DropDownList"
$panel.Controls.Add($cmbLang)

# Path Label
$lblPath = New-Object System.Windows.Forms.Label
$lblPath.Text = "Kurulum Dizini (Install Path):"
$lblPath.Location = New-Object System.Drawing.Point(20, 80)
$lblPath.AutoSize = $true
$panel.Controls.Add($lblPath)

# Path TextBox
$txtPath = New-Object System.Windows.Forms.TextBox
$txtPath.Text = "$env:USERPROFILE\Koza"
$txtPath.Location = New-Object System.Drawing.Point(20, 100)
$txtPath.Size = New-Object System.Drawing.Size(310, 25)
$panel.Controls.Add($txtPath)

# Browse Button
$btnBrowse = New-Object System.Windows.Forms.Button
$btnBrowse.Text = "Gozat..."
$btnBrowse.Location = New-Object System.Drawing.Point(340, 99)
$btnBrowse.Size = New-Object System.Drawing.Size(80, 27)
$btnBrowse.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.SelectedPath = $txtPath.Text
    if ($dialog.ShowDialog() -eq "OK") {
        $txtPath.Text = $dialog.SelectedPath
    }
})
$panel.Controls.Add($btnBrowse)

# Status Label
$lblStatus = New-Object System.Windows.Forms.Label
$lblStatus.Text = "Kuruluma baslamak icin 'Kur' butonuna tiklayin."
$lblStatus.Location = New-Object System.Drawing.Point(20, 145)
$lblStatus.Size = New-Object System.Drawing.Size(400, 25)
$lblStatus.ForeColor = [System.Drawing.Color]::DimGray
$panel.Controls.Add($lblStatus)

# Progress Bar
$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(20, 175)
$progressBar.Size = New-Object System.Drawing.Size(400, 20)
$progressBar.Style = "Continuous"
$panel.Controls.Add($progressBar)

# Install Button
$btnInstall = New-Object System.Windows.Forms.Button
$btnInstall.Text = "Kur (Install)"
$btnInstall.Location = New-Object System.Drawing.Point(360, 300)
$btnInstall.Size = New-Object System.Drawing.Size(100, 35)
$btnInstall.BackColor = $PrimaryColor
$btnInstall.ForeColor = [System.Drawing.Color]::White
$btnInstall.FlatStyle = "Flat"
$form.Controls.Add($btnInstall)

# Install Logic
$btnInstall.Add_Click({
    $InstallDir = $txtPath.Text
    $Lang = $cmbLang.SelectedItem
    $btnInstall.Enabled = $false
    $txtPath.Enabled = $false
    $btnBrowse.Enabled = $false
    $cmbLang.Enabled = $false

    try {
        if (!(Test-Path $InstallDir)) {
            New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
        }
        
        $ToolsDir = Join-Path $InstallDir "tools"
        if (!(Test-Path $ToolsDir)) {
            New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
        }

        # Python Check
        $lblStatus.Text = "Python kontrol ediliyor..."
        [System.Windows.Forms.Application]::DoEvents()
        $SysPython = Get-Command "python" -ErrorAction SilentlyContinue
        $PythonExe = $null
        
        if ($SysPython) {
            $lblStatus.Text = "Sistemdeki Python kullanilacak: $($SysPython.Source)"
            $PythonExe = $SysPython.Source
        } else {
            $lblStatus.Text = "Python indiriliyor (Portable)..."
            [System.Windows.Forms.Application]::DoEvents()
            $progressBar.Style = "Marquee"
            $PyInstallerPath = Join-Path $env:TEMP "python-installer.exe"
            Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe" -OutFile $PyInstallerPath -UseBasicParsing
            
            $lblStatus.Text = "Python sanal (izole) olarak kuruluyor..."
            [System.Windows.Forms.Application]::DoEvents()
            $PyInstallDir = Join-Path $ToolsDir "python"
            $args = "/quiet InstallAllUsers=0 TargetDir=`"$PyInstallDir`" Include_test=0 Include_doc=0 PrependPath=0"
            $process = Start-Process -FilePath $PyInstallerPath -ArgumentList $args -PassThru
            while (-not $process.HasExited) {
                [System.Windows.Forms.Application]::DoEvents()
                Start-Sleep -Milliseconds 100
            }
            $PythonExe = Join-Path $PyInstallDir "python.exe"
            $progressBar.Style = "Continuous"
        }

        # Bun Check
        $lblStatus.Text = "Bun (Node alternatifi) kontrol ediliyor..."
        [System.Windows.Forms.Application]::DoEvents()
        $SysBun = Get-Command "bun" -ErrorAction SilentlyContinue
        $BunExe = $null
        $BunDir = $null

        if ($SysBun) {
            $lblStatus.Text = "Sistemdeki Bun kullanilacak: $($SysBun.Source)"
            $BunExe = $SysBun.Source
        } else {
            $lblStatus.Text = "Bun indiriliyor (Portable)..."
            [System.Windows.Forms.Application]::DoEvents()
            $progressBar.Style = "Marquee"
            $BunZip = Join-Path $env:TEMP "bun.zip"
            Invoke-WebRequest -Uri "https://github.com/oven-sh/bun/releases/latest/download/bun-windows-x64.zip" -OutFile $BunZip -UseBasicParsing
            
            $lblStatus.Text = "Bun cikariliyor..."
            [System.Windows.Forms.Application]::DoEvents()
            Expand-Archive -Path $BunZip -DestinationPath $ToolsDir -Force
            $BunExe = Join-Path $ToolsDir "bun-windows-x64\bun.exe"
            $BunDir = Join-Path $ToolsDir "bun-windows-x64"
            $progressBar.Style = "Continuous"
        }

        # App Download
        $lblStatus.Text = "Koza kaynak kodlari Github'dan indiriliyor..."
        $progressBar.Style = "Marquee"
        [System.Windows.Forms.Application]::DoEvents()
        $AppZip = Join-Path $env:TEMP "koza-app.zip"
        Invoke-WebRequest -Uri "https://github.com/haydarkadioglu/koza-agent/archive/refs/heads/main.zip" -OutFile $AppZip -UseBasicParsing
        
        $lblStatus.Text = "Kaynak kodlar cikariliyor..."
        [System.Windows.Forms.Application]::DoEvents()
        $ExtractDir = Join-Path $env:TEMP "koza-app-extract"
        if (Test-Path $ExtractDir) { Remove-Item -Recurse -Force $ExtractDir }
        Expand-Archive -Path $AppZip -DestinationPath $ExtractDir -Force
        
        $AppDir = Join-Path $InstallDir "app"
        if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
        $ExtractedFolder = Get-ChildItem $ExtractDir | Select-Object -First 1
        Move-Item -Path $ExtractedFolder.FullName -Destination $AppDir -Force
        
        # VirtualEnv Creation
        $lblStatus.Text = "Sanal ortam (Virtual Env) olusturuluyor..."
        [System.Windows.Forms.Application]::DoEvents()
        $VenvDir = Join-Path $AppDir ".venv"
        & $PythonExe -m venv $VenvDir
        $VenvPip = Join-Path $VenvDir "Scripts\pip.exe"
        $VenvKoza = Join-Path $VenvDir "Scripts\koza.exe"

        # Install Python dependencies
        $lblStatus.Text = "Python bagimliliklari kuruluyor..."
        [System.Windows.Forms.Application]::DoEvents()
        & $VenvPip install -e $AppDir

        # Install UI dependencies
        $lblStatus.Text = "Arayuz (UI) bagimliliklari kuruluyor..."
        [System.Windows.Forms.Application]::DoEvents()
        $UiDir = Join-Path $AppDir "ui"
        
        # Use a temporary script to run bun install
        $BunInstallScript = Join-Path $env:TEMP "run-bun.bat"
        $BunScriptContent = ""
        if ($BunDir) { $BunScriptContent += "set PATH=$BunDir;%PATH%`n" }
        $BunScriptContent += "cd /d `"$UiDir`"`n"
        $BunScriptContent += "`"$BunExe`" install"
        Set-Content -Path $BunInstallScript -Value $BunScriptContent
        $bunProcess = Start-Process -FilePath $BunInstallScript -WindowStyle Hidden -PassThru
        while (-not $bunProcess.HasExited) {
            [System.Windows.Forms.Application]::DoEvents()
            Start-Sleep -Milliseconds 100
        }

        # Create koza.bat in InstallDir and add to PATH
        $lblStatus.Text = "Terminal kisayollari ve ayarlar yapiliyor..."
        [System.Windows.Forms.Application]::DoEvents()
        $BatPath = Join-Path $InstallDir "koza.bat"
        $BatContent = "@echo off`n"
        if ($BunDir) { $BatContent += "set PATH=$BunDir;%PATH%`n" }
        $BatContent += "`"$VenvKoza`" %*"
        Set-Content -Path $BatPath -Value $BatContent

        # Add InstallDir to User PATH if not present
        $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
        $pathEntries = $currentPath -split ";" | Where-Object { $_.Trim() -ne "" }
        if ($pathEntries -notcontains $InstallDir) {
            $newPath = ($pathEntries + $InstallDir) -join ";"
            [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        }

        # Create Desktop Shortcut
        $lblStatus.Text = "Masaustu kisayolu olusturuluyor..."
        [System.Windows.Forms.Application]::DoEvents()
        
        # Create a hidden starter vbs for the desktop app
        $VbsPath = Join-Path $InstallDir "start-ui.vbs"
        $VbsContent = "Set WshShell = CreateObject(`"WScript.Shell`")`n"
        $VbsContent += "WshShell.CurrentDirectory = `"$UiDir`"`n"
        $VbsContent += "WshShell.Run `"`"$BunExe`" run dev:desktop`", 0, False"
        Set-Content -Path $VbsPath -Value $VbsContent

        $WshShell = New-Object -ComObject WScript.Shell
        $DesktopPath = [Environment]::GetFolderPath("Desktop")
        $ShortcutPath = Join-Path $DesktopPath "Koza.lnk"
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = "wscript.exe"
        $Shortcut.Arguments = "`"$VbsPath`""
        $Shortcut.WorkingDirectory = $UiDir
        # Try to use the icon from the app directory if exists
        $IconPath = Join-Path $AppDir "icon.ico"
        if (Test-Path $IconPath) {
            $Shortcut.IconLocation = $IconPath
        }
        $Shortcut.Save()

        $progressBar.Style = "Continuous"
        $progressBar.Value = 100
        $lblStatus.Text = "Kurulum basariyla tamamlandi!"
        [System.Windows.Forms.MessageBox]::Show("Kurulum basariyla tamamlandi!`nMasaustundeki Koza kisayolundan baslatabilirsiniz.", "Basarili", 0, 64)
        $form.Close()

    } catch {
        $lblStatus.Text = "Kurulum sirasinda hata olustu."
        [System.Windows.Forms.MessageBox]::Show("Hata: $($_.Exception.Message)", "Hata", 0, 16)
    } finally {
        $btnInstall.Enabled = $true
        $txtPath.Enabled = $true
        $btnBrowse.Enabled = $true
        $cmbLang.Enabled = $true
    }
})

$form.ShowDialog() | Out-Null
