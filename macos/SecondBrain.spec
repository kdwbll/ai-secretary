from pathlib import Path
import re
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
version = re.search(r'APP_VERSION = "([^"]+)"', (root / "core/secretary/app.py").read_text()).group(1)
datas = [(str(root / "web"), "web"), (str(root / "core/prompts"), "core/prompts"), (str(root / "LICENSE"), ".")]
binaries, hiddenimports = [], []
for package in ("uvicorn", "imageio_ffmpeg"):
    extra_data, extra_bins, extra_imports = collect_all(package)
    datas += extra_data
    binaries += extra_bins
    hiddenimports += extra_imports

a = Analysis([str(root / "macos/second_brain_launcher.py")], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SecondBrain", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="SecondBrain")
app = BUNDLE(coll, name="SecondBrain.app", icon=str(root / "macos/SecondBrain.icns"),
             bundle_identifier="com.secondbrain.desktop", version=version,
             info_plist={"CFBundleShortVersionString": version,
                         "NSHighResolutionCapable": True, "LSUIElement": True})
