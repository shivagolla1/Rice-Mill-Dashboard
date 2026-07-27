import os
import shutil
import subprocess
import sys

def main():
    # Detect if currently running on 32-bit Python 3.8
    current_is_py38_32 = (sys.version_info[:2] == (3, 8)) and (sys.maxsize <= 2**32)
    py38_32_exe = r"C:\Python38-32\python.exe"
    
    if not current_is_py38_32:
        if os.path.exists(py38_32_exe):
            print("\n[INFO] Re-launching package.py using 32-bit Python 3.8 environment for maximum Windows 7 compatibility...\n")
            result = subprocess.run([py38_32_exe] + sys.argv, shell=False)
            sys.exit(result.returncode)
        else:
            print("\n[WARNING] 32-bit Python 3.8 (C:\\Python38-32\\python.exe) not found.")
            print("Building with current Python, which might not be compatible with Windows 7 32-bit.\n")

    print("=== Rice Mill Dashboard Production Packager ===")
    
    # 1. Install prerequisites if needed
    print("\n[1/6] Ensuring packaging requirements are installed...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pyarmor", "pyinstaller", "pillow", "-r", "requirements.txt"], check=True)

    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)

    validator_py = "license_validator.py"
    validator_bak = "license_validator.py.bak"
    dist_obf_dir = "dist_obf"
    
    # Clean old builds
    for path in [dist_obf_dir, "build", "dist", "RiceMillDashboard.spec"]:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

    # 2. Obfuscate license_validator.py using PyArmor
    print("\n[2/6] Obfuscating license_validator.py using PyArmor...")
    try:
        subprocess.run([sys.executable, "-m", "pyarmor.cli", "gen", "-O", dist_obf_dir, validator_py], check=True)
        print("Obfuscation successful.")
    except Exception as e:
        print(f"Error during PyArmor obfuscation: {e}")
        return

    # 3. Ensure static/logo.ico and static/logo.jpg exist by normalizing any logo input
    static_dir = "static"
    logo_jpg = os.path.join(static_dir, "logo.jpg")
    logo_ico = os.path.join(static_dir, "logo.ico")
    
    possible_names = ["logo.png", "logo.jpeg", "logo.jpg", "Fallback Logo.png", "fallback logo.png", "Fallback Logo.jpg", "fallback_logo.png"]
    found_logo = None
    for name in possible_names:
        p = os.path.join(static_dir, name)
        if os.path.exists(p):
            found_logo = p
            break
            
    if found_logo:
        print(f"\n[3/6] Normalizing fallback logo from: {found_logo}")
        try:
            from PIL import Image
            img = Image.open(found_logo)
            # Save a standard RGB copy as logo.jpg
            if found_logo != logo_jpg:
                img.convert('RGB').save(logo_jpg, "JPEG", quality=95)
                print(f"Generated standard fallback logo: {logo_jpg}")
            
            # Save as ICO for PyInstaller icon
            img.save(logo_ico, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32)])
            print(f"Successfully generated/updated icon: {logo_ico}")
        except Exception as e:
            print(f"Warning: Could not process/convert logo file: {e}")

    # 4. Temporarily hide plain text license_validator.py so PyInstaller packages the obfuscated one from dist_obf
    print("\n[4/6] Backing up plain text license_validator.py...")
    if os.path.exists(validator_bak):
        os.remove(validator_bak)
    os.rename(validator_py, validator_bak)

    try:
        # 4. Build single-file executable using PyInstaller
        print("\n[5/6] Running PyInstaller to bundle executable...")
        pyinstaller_cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--noconsole",
            "--icon=static/logo.ico",
            "--add-data=templates;templates",
            "--add-data=static;static",
            "-p", dist_obf_dir,  # Resolve imports from the obfuscated folder
            "--name=RiceMillDashboard",
            "app.py"
        ]
        
        subprocess.run(pyinstaller_cmd, check=True)
        print("Executable built successfully inside dist/ folder.")

    finally:
        # 5. Restore the original plain text license_validator.py source file
        if os.path.exists(validator_bak):
            print("\n[6/6] Restoring plain text license_validator.py...")
            if os.path.exists(validator_py):
                os.remove(validator_py)
            os.rename(validator_bak, validator_py)

    # Move output executable to parent directory
    dest_exe = os.path.join(app_dir, "RiceMillDashboard.exe")
    src_exe = os.path.join(app_dir, "dist", "RiceMillDashboard.exe")
    if os.path.exists(src_exe):
        if os.path.exists(dest_exe):
            os.remove(dest_exe)
        shutil.move(src_exe, dest_exe)
        print(f"\nSUCCESS: RiceMillDashboard.exe created in: {dest_exe}")
        
        # Clean up build artifacts
        for path in [dist_obf_dir, "build", "dist", "RiceMillDashboard.spec"]:
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
    else:
        print("\nERROR: Could not find built executable in dist/")

if __name__ == "__main__":
    main()
