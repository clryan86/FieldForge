# Build on Windows x64, never cross-compile or use the source tree at runtime.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
hidden = collect_submodules('fieldforge') + collect_submodules('fieldforge_gps')
gps_data = collect_data_files('fieldforge_gps')
portal_data = collect_data_files('fieldforge.online')
reference_data = collect_data_files('fieldforge.content')
common = dict(pathex=[str(root)], hiddenimports=hidden, binaries=[], hookspath=[], runtime_hooks=[],
              excludes=['pytest', 'ruff', 'numpy', 'matplotlib', 'cryptography', 'Crypto'],
              noarchive=False, optimize=0)
app = Analysis([str(root / 'packaging/desktop_entry.py')],
               datas=[(str(root / 'build/windows-metadata/_build.json'), 'fieldforge'), *gps_data, *portal_data, *reference_data], **common)
tools = Analysis([str(root / 'packaging/tools_entry.py')], datas=[*gps_data, *portal_data, *reference_data], **common)
main_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True, name='FieldForge',
               debug=False, strip=False, upx=False, console=False, disable_windowed_traceback=True)
helper_exe = EXE(PYZ(tools.pure), tools.scripts, [], exclude_binaries=True, name='FieldForgeTools',
                 debug=False, strip=False, upx=False, console=True)
COLLECT(main_exe, helper_exe, app.binaries, app.datas, tools.binaries, tools.datas,
        strip=False, upx=False, name='FieldForge-Windows')
