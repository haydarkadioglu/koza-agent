import os
import sys
import shutil
import subprocess
import time

def find_electron_install_script(opencode_dir):
    for root, dirs, files in os.walk(os.path.join(opencode_dir, "node_modules")):
        if "install.js" in files and "electron" in root:
            return os.path.join(root, "install.js")
    return None

def cleanup_unused_folders(opencode_dir):
    print("🧹 Cleaning up unused OpenCode folders...")
    folders_to_delete = [
        ".git", ".github", ".husky", ".vscode", ".zed",
        "infra", "nix", "perf", "specs", "sdks", "patches", "artifacts", "github"
    ]
    for folder in folders_to_delete:
        path = os.path.join(opencode_dir, folder)
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
                
    packages_to_delete = ["console", "stats", "storybook", "slack", "enterprise", "docs"]
    packages_dir = os.path.join(opencode_dir, "packages")
    for pkg in packages_to_delete:
        path = os.path.join(packages_dir, pkg)
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
            
    for file in os.listdir(opencode_dir):
        if file.startswith("README.") and file.endswith(".md") and file != "README.tr.md":
            os.remove(os.path.join(opencode_dir, file))
            
    for extra_file in ["STATS.md", "CONTEXT.md", "CONTRIBUTING.md", "SECURITY.md"]:
        path = os.path.join(opencode_dir, extra_file)
        if os.path.exists(path):
            os.remove(path)

def create_desktop_shortcut(koza_exe, agent_dir):
    try:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        shortcut_path = os.path.join(desktop, "Koza.lnk")
        ps_cmd = f"""
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
        $Shortcut.TargetPath = '{koza_exe}'
        $Shortcut.Arguments = 'ui'
        $Shortcut.WorkingDirectory = '{agent_dir}'
        $Shortcut.Save()
        """
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True, capture_output=True)
        print("  ✓ Created desktop shortcut: Koza.lnk")
    except Exception as e:
        print("  ✗ Failed to create desktop shortcut:", e)

def cmd_ui(args: list[str] | None = None) -> None:
    agent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    opencode_dir = os.path.join(agent_dir, "ui")
    
    # Locate python executable that has fastapi installed
    python_exe = None
    for candidate in ["python", "python3", sys.executable]:
        try:
            res = subprocess.run([candidate, "-c", "import fastapi"], capture_output=True)
            if res.returncode == 0:
                python_exe = candidate
                break
        except Exception:
            pass
            
    if not python_exe:
        python_exe = sys.executable  # fallback
        
    desktop_dist_dir = os.path.join(opencode_dir, "packages", "desktop", "dist", "win-unpacked")
    exe_path = os.path.join(desktop_dist_dir, "Koza Dev.exe")
    
    # Check if compiled app exists
    if not os.path.exists(exe_path):
        import ctypes
        def is_admin():
            try:
                return ctypes.windll.shell32.IsUserAnAdmin()
            except Exception:
                return False

        if sys.platform == "win32" and not is_admin():
            print("🔒 First-time setup requires Administrator privileges. Requesting elevation (UAC)...")
            params = subprocess.list2cmdline(sys.argv)
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
            sys.exit(0)

        print("🔧 First-time Koza UI Setup Initiated...")
        
        # 1. Clone if needed
        if not os.path.exists(opencode_dir):
            print("📥 Cloning Koza UI repository...")
            subprocess.run(["git", "clone", "https://github.com/anomalyco/opencode.git", opencode_dir], check=True)
            cleanup_unused_folders(opencode_dir)
            
        # 2. Bun install
        print("📦 Installing package dependencies (this may take a few minutes)...")
        subprocess.run(["bun", "install"], cwd=opencode_dir, shell=True, check=True)
        
        # 3. Download Electron binary
        print("⬇️ Downloading Electron platform binary...")
        install_js = find_electron_install_script(opencode_dir)
        if install_js:
            subprocess.run(["node", install_js], cwd=opencode_dir, check=True)
        else:
            print("⚠️ Warning: Electron install script not found, hoping bun install handled it.")
            
        # 4. Package Electron app (dir mode)
        print("⚙️ Compiling and packaging native desktop application...")
        subprocess.run(["bun", "run", "--cwd", "packages/desktop", "package:win", "--dir"], cwd=opencode_dir, shell=True, check=True)
        
        # 5. Create shortcut
        if os.path.exists(exe_path):
            print("🖥️ Creating desktop shortcut...")
            venv_koza = os.path.join(agent_dir, ".venv", "Scripts", "koza.exe") if sys.platform == "win32" else os.path.join(agent_dir, ".venv", "bin", "koza")
            koza_exe = venv_koza if os.path.exists(venv_koza) else "koza"
            create_desktop_shortcut(koza_exe, agent_dir)
        else:
            print("❌ Setup failed to generate Koza Dev.exe!")
            return
            
        print("🎉 Setup complete!")
        
    # Launch application
    print("🚀 Starting Koza Desktop app and API bridge...")
    
    # 1. Start Koza API Server (port 8000)
    print("  -> Starting Koza API Bridge (port 8000)...")
    api_proc = subprocess.Popen(
        [python_exe, "api_server.py"],
        cwd=agent_dir
    )
    
    # 2. Start Desktop App client
    print("  -> Launching Koza Desktop App...")
    env = os.environ.copy()
    env["OPENCODE_DISABLE_CHANNEL_DB"] = "1"
    desktop_proc = subprocess.Popen(
        [exe_path],
        cwd=desktop_dist_dir,
        env=env
    )
    
    print("\nKeep this window open or press Ctrl+C to close Koza.")
    try:
        while True:
            if desktop_proc.poll() is not None:
                print("\nKoza Desktop window closed.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down Koza background processes...")
        api_proc.terminate()
        desktop_proc.terminate()
        print("Koza stopped.")
