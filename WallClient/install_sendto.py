"""Adds "Send to Wall" to the Windows right-click > Send to menu.

    python install_sendto.py            install
    python install_sendto.py --remove   uninstall
"""
import os
import sys
from pathlib import Path

SENDTO = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "SendTo"
ENTRY = SENDTO / "Wall.bat"
SEND_PY = Path(__file__).with_name("send.py").resolve()

if "--remove" in sys.argv:
    ENTRY.unlink(missing_ok=True)
    print("Removed 'Wall' from the Send to menu.")
else:
    ENTRY.write_text(
        "@echo off\r\n"
        "title Sending to Wall\r\n"
        f'"{sys.executable}" "{SEND_PY}" --pause-on-error %*\r\n',
        encoding="utf-8",
    )
    print(f"Installed. Right-click any file > Send to > Wall\n({ENTRY})")
