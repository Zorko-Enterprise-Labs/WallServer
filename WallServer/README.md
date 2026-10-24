# WallServer: runs on the machine connected to the TV

## Setup (once)

```
pip install -r requirements.txt
```

The first time the server starts, it creates `config.json`, picks a random **token**, saves it there and prints it. WallClient needs the same token. To choose your own, put it in `config.json` as `token`.

## Start

- **Windows:** double-click `start_wall.bat`. It starts the server and opens the wall fullscreen in Brave, Chrome or Edge, whichever it finds first.
- **Raspberry Pi / Linux:** `sh start_wall.sh`
- **Server only:** `python server.py`, then open `http://localhost:8765` fullscreen yourself.

When it starts, the server prints the **address for WallClient**, something like `http://192.168.1.50:8765`. Put that into WallClient's Settings.

If Windows Firewall asks about Python, allow it on **private networks**.

To close a kiosk browser window, press Alt+F4.

## Good to know

- A small red dot in the bottom-right corner of the wall means it lost the server. It reconnects by itself.
- `http://<address>:8765/control` is a control page for your phone. Enter the token once and it remembers it.
- Only the wall on this machine can watch without the token. To show the wall on a different machine, open `http://<address>:8765/?token=<token>`.
- Files over 2 GB are refused. To change the limit, set `max_upload_mb` in `config.json`.
- Everything goes over plain HTTP, so use it on a network you trust, such as your home network.
- Received files live in `uploads/` and are deleted when they're replaced or cleared.
- The wall starts empty every time the server restarts.
