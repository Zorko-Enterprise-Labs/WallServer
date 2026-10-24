# WallClient: runs on your PC

## Setup (once)

```
pip install -r requirements.txt
```

Start it with `Wall Client.bat` (or `pythonw wall_client.py`). Click **Settings** and enter:
- **Wall address:** the address WallServer prints when it starts, for example `http://192.168.1.50:8765`.
- **Token:** the same word as in WallServer's `config.json`.
- **Show me as:** the name shown on the wall's Receiving card. If left empty, it uses your computer name.

The dot next to "Wall" turns green once it can reach the wall.

## Sending

- **Drag files onto the window**, or click the drop area to choose them.
- **Slot:** "Next free" fills empty slots first, then replaces the oldest unpinned one. Pick a number to aim at a specific slot.
- Several files at once are queued and sent one after another. **Cancel** stops the current transfer and clears the queue.
- **Layout / Screen / On the wall:** switch layouts, toggle blackout, and pin or clear individual slots.

## Right-click menu (optional)

```
python install_sendto.py
```

After this, right-click any file and choose **Send to → Wall**. A small console window shows the progress.
To remove it later, run `python install_sendto.py --remove`.

## Command line (optional)

```
python send.py photo.jpg --slot 2
python send.py --layout grid
python send.py --blackout
```

`send.py` and the window share the same `config.json`.
