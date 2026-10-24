"""WallClient: a small window for sending things to the wall.

Drag files onto the window (or click to choose), pick a slot, and watch them go.
Also switches layouts, blackout, and clears or pins what's on the wall.

    pythonw wall_client.py
"""
import json
import socket
import sys
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QFile, QIODevice, Qt, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
LAYOUTS = [("single", "Single", 1), ("split", "Split", 2), ("focus", "Focus", 3), ("grid", "Grid", 4)]
POLL_MS = 2000

ACCENT, BAD, GOOD, MUTED = "#4cc2ff", "#ff6b6b", "#3fb950", "#8b949e"
STYLE = f"""
QWidget {{ background:#0b0f14; color:#e6edf3; font-family:"Segoe UI"; font-size:10pt; }}
QPushButton {{ background:#121922; border:1px solid #223041; border-radius:6px; padding:6px 12px; }}
QPushButton:hover {{ border-color:#3a5068; }}
QPushButton:checked {{ border-color:{ACCENT}; color:{ACCENT}; }}
QPushButton:disabled {{ color:#4a5562; }}
QComboBox, QLineEdit {{ background:#121922; border:1px solid #223041; border-radius:6px; padding:5px 8px; }}
QProgressBar {{ background:#1c2632; border:none; border-radius:2px; }}
QProgressBar::chunk {{ background:{ACCENT}; border-radius:2px; }}
QLabel#drop {{ border:1px dashed #2c3b4d; border-radius:10px; color:{MUTED}; font-size:11pt; }}
QLabel#drop[over="true"] {{ border-color:{ACCENT}; color:{ACCENT}; }}
QLabel#section {{ color:{MUTED}; font-size:8pt; font-weight:600; letter-spacing:2px; padding-top:8px; }}
QLabel#title {{ font-size:14pt; font-weight:600; }}
QFrame#slotrow {{ background:#121922; border:1px solid #223041; border-radius:6px; }}
QFrame#slotrow QLabel {{ background:transparent; }}
"""


def load_config() -> dict:
    cfg = {"server": "http://127.0.0.1:8765", "token": "change-me", "name": ""}
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def fmt_bytes(b: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024 or unit == "GB":
            return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
        b /= 1024
    return ""


class DropZone(QLabel):
    filesDropped = Signal(list)
    clicked = Signal()

    def __init__(self):
        super().__init__("Drop files here\nor click to choose")
        self.setObjectName("drop")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(120)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)

    def _highlight(self, on: bool):
        self.setProperty("over", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._highlight(True)

    def dragLeaveEvent(self, e):
        self._highlight(False)

    def dropEvent(self, e):
        self._highlight(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)

    def mousePressEvent(self, e):
        self.clicked.emit()


class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wall settings")
        self.server = QLineEdit(cfg["server"])
        self.server.setPlaceholderText("http://192.168.1.50:8765")
        self.token = QLineEdit(cfg["token"])
        self.token.setEchoMode(QLineEdit.Password)
        self.name = QLineEdit(cfg["name"])
        self.name.setPlaceholderText(socket.gethostname())
        form = QFormLayout(self)
        form.addRow("Wall address", self.server)
        form.addRow("Token", self.token)
        form.addRow("Show me as", self.name)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(420, 0)

    def values(self) -> dict:
        return {"server": self.server.text().strip().rstrip("/"), "token": self.token.text(),
                "name": self.name.text().strip()}


class WallClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.nam = QNetworkAccessManager(self)
        self.queue: list[str] = []
        self.first_in_batch = True
        self.upload: QNetworkReply | None = None
        self.state_reply: QNetworkReply | None = None
        self.state: dict | None = None
        self.connected: bool | None = None
        self._build_ui()

        self.timer = QTimer(self, interval=POLL_MS, timeout=self.refresh_state)
        self.timer.start()
        self.refresh_state()

    # ---------- UI ----------

    def _section(self, text):
        label = QLabel(text.upper())
        label.setObjectName("section")
        return label

    def _build_ui(self):
        self.setWindowTitle("Wall Client")
        self.resize(420, 640)
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(16, 14, 16, 16)
        v.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("Wall")
        title.setObjectName("title")
        self.status = QLabel()
        settings = QPushButton("Settings")
        settings.clicked.connect(self.open_settings)
        top.addWidget(title)
        top.addSpacing(8)
        top.addWidget(self.status, 1)
        top.addWidget(settings)
        v.addLayout(top)

        v.addWidget(self._section("Send"))
        self.drop = DropZone()
        self.drop.filesDropped.connect(self.enqueue)
        self.drop.clicked.connect(self.pick_files)
        v.addWidget(self.drop)

        row = QHBoxLayout()
        row.addWidget(QLabel("Slot"))
        self.slot = QComboBox()
        self.slot.addItems(["Next free", "1", "2", "3", "4"])
        row.addWidget(self.slot)
        row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.setVisible(False)
        row.addWidget(self.cancel_btn)
        v.addLayout(row)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.prog = QLabel(" ")
        self.prog.setStyleSheet(f"color:{MUTED}")
        self.prog.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(self.bar)
        v.addWidget(self.prog)

        v.addWidget(self._section("Layout"))
        lay = QHBoxLayout()
        self.layout_group = QButtonGroup(self)
        self.layout_buttons = {}
        for key, label, _ in LAYOUTS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.command({"action": "layout", "layout": k}))
            self.layout_group.addButton(b)
            self.layout_buttons[key] = b
            lay.addWidget(b)
        v.addLayout(lay)

        v.addWidget(self._section("Screen"))
        scr = QHBoxLayout()
        self.black_btn = QPushButton("Blackout")
        self.black_btn.setCheckable(True)
        self.black_btn.clicked.connect(lambda: self.command({"action": "blackout"}))
        clear = QPushButton("Clear unpinned")
        clear.clicked.connect(lambda: self.command({"action": "clear"}))
        clear_all = QPushButton("Clear all")
        clear_all.clicked.connect(lambda: self.command({"action": "clear_all"}))
        for b in (self.black_btn, clear, clear_all):
            scr.addWidget(b)
        v.addLayout(scr)

        v.addWidget(self._section("On the wall"))
        self.slots_box = QVBoxLayout()
        self.slots_box.setSpacing(6)
        v.addLayout(self.slots_box)
        v.addStretch(1)

        self.controls = [*self.layout_buttons.values(), self.black_btn, clear, clear_all]
        self.setCentralWidget(root)
        self.set_connected(False)

    def set_connected(self, ok: bool):
        if ok == self.connected:
            return
        self.connected = ok
        if ok:
            self.status.setText(f"<span style='color:{GOOD}'>●</span> Connected")
        else:
            self.status.setText(f"<span style='color:{BAD}'>●</span> Can't reach the wall")
            self.state = None
            self.render_slots({})
        self.status.setToolTip(self.cfg["server"])
        for b in self.controls:
            b.setEnabled(ok)

    def flash(self, text: str, color: str = MUTED):
        self.prog.setText(text)
        self.prog.setStyleSheet(f"color:{color}")

    # ---------- network ----------

    def request(self, path: str) -> QNetworkRequest:
        req = QNetworkRequest(QUrl(self.cfg["server"] + path))
        req.setRawHeader(b"X-Wall-Token", self.cfg["token"].encode())
        req.setRawHeader(b"X-From", quote(self.cfg["name"] or socket.gethostname()).encode())
        return req

    @staticmethod
    def http_status(reply: QNetworkReply) -> int:
        return reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0

    def refresh_state(self):
        if self.state_reply is not None:
            return
        req = self.request("/api/state")
        req.setTransferTimeout(3000)
        self.state_reply = self.nam.get(req)
        self.state_reply.finished.connect(self._on_state)

    def _on_state(self):
        reply, self.state_reply = self.state_reply, None
        if reply.error() == QNetworkReply.NoError:
            self.set_connected(True)
            self.apply_state(json.loads(bytes(reply.readAll())))
        else:
            self.set_connected(False)
        reply.deleteLater()

    def apply_state(self, st: dict):
        if st == self.state:
            return
        self.state = st
        for key, b in self.layout_buttons.items():
            b.setChecked(key == st["layout"])
        self.black_btn.setChecked(st["blackout"])
        self.render_slots(st)

    def render_slots(self, st: dict):
        while self.slots_box.count():
            w = self.slots_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not st:
            return
        count = dict((k, n) for k, _, n in LAYOUTS)[st["layout"]]
        for i in range(1, count + 1):
            item = st["slots"].get(str(i))
            row = QFrame()
            row.setObjectName("slotrow")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 6, 6, 6)
            num = QLabel(str(i))
            num.setStyleSheet(f"color:{ACCENT}; font-weight:600")
            num.setFixedWidth(16)
            name = QLabel(item["name"] if item else "empty")
            name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            name.setToolTip(item["name"] if item else "")
            if not item:
                name.setStyleSheet(f"color:{MUTED}")
            h.addWidget(num)
            h.addWidget(name, 1)
            if item:
                pin = QPushButton("Unpin" if item["pinned"] else "Pin")
                pin.setCheckable(True)
                pin.setChecked(item["pinned"])
                pin.clicked.connect(lambda _=False, n=i, p=item["pinned"]:
                                    self.command({"action": "unpin" if p else "pin", "slot": n}))
                clr = QPushButton("Clear")
                clr.clicked.connect(lambda _=False, n=i: self.command({"action": "clear", "slot": n}))
                h.addWidget(pin)
                h.addWidget(clr)
            self.slots_box.addWidget(row)

    def command(self, payload: dict):
        req = self.request("/api/command")
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        req.setTransferTimeout(5000)
        reply = self.nam.post(req, json.dumps(payload).encode())

        def done():
            status = self.http_status(reply)
            if reply.error() == QNetworkReply.NoError:
                self.apply_state(json.loads(bytes(reply.readAll()))["state"])
            elif status == 401:
                self.flash("Wrong token. Check Settings.", BAD)
                self.state = None  # re-sync the buttons to the real state
                self.refresh_state()
            else:
                self.flash("Couldn't reach the wall.", BAD)
            reply.deleteLater()

        reply.finished.connect(done)

    # ---------- sending ----------

    def pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Send to the wall")
        if paths:
            self.enqueue(paths)

    def enqueue(self, paths: list):
        files = [p for p in paths if Path(p).is_file()]
        if not files:
            self.flash("Only files can be sent (not folders).", BAD)
            return
        if self.upload is None:
            self.first_in_batch = True
        self.queue.extend(files)
        if self.upload is None:
            self.send_next()
        else:
            self._show_progress(0, 0)

    def send_next(self):
        if not self.queue:
            self.cancel_btn.setVisible(False)
            return
        path = Path(self.queue.pop(0))
        f = QFile(str(path))
        if not f.open(QIODevice.ReadOnly):
            self.flash(f"Can't open {path.name}", BAD)
            self.send_next()
            return
        slot = self.slot.currentIndex() if self.first_in_batch else 0
        self.first_in_batch = False

        req = self.request("/api/push")
        req.setRawHeader(b"X-Filename", quote(path.name).encode())
        req.setRawHeader(b"X-Slot", str(slot).encode())
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/octet-stream")
        req.setHeader(QNetworkRequest.ContentLengthHeader, f.size())

        self.current_name = path.name
        self.current_size = f.size()
        self.bar.setValue(0)
        self.cancel_btn.setVisible(True)
        self._show_progress(0, f.size())

        self.upload = self.nam.post(req, f)
        f.setParent(self.upload)  # file closes when the upload is cleaned up
        self.upload.uploadProgress.connect(self._show_progress)
        self.upload.finished.connect(self._on_upload_done)

    def _show_progress(self, sent: int, total: int):
        if self.upload is None and not self.queue:
            return
        total = total or self.current_size
        pct = sent / total if total else 0
        self.bar.setValue(int(pct * 1000))
        more = f"  ·  {len(self.queue)} more queued" if self.queue else ""
        self.flash(f"Sending {self.current_name}  ·  {pct:.0%}  ·  {fmt_bytes(sent)} / {fmt_bytes(total)}{more}")

    def _on_upload_done(self):
        reply, self.upload = self.upload, None
        status = self.http_status(reply)
        if reply.error() == QNetworkReply.NoError:
            slot = json.loads(bytes(reply.readAll())).get("slot")
            self.bar.setValue(1000)
            self.flash(f"✓ {self.current_name} is on the wall (slot {slot})", GOOD)
        elif reply.error() == QNetworkReply.OperationCanceledError:
            self.bar.setValue(0)
            self.flash("Cancelled.", MUTED)
        elif status == 401:
            self.queue.clear()
            self.flash("Wrong token. Check Settings.", BAD)
        else:
            self.queue.clear()
            self.flash(f"Couldn't send {self.current_name}. Is the wall running?", BAD)
        reply.deleteLater()
        self.refresh_state()
        self.send_next()

    def cancel(self):
        self.queue.clear()
        if self.upload is not None:
            self.upload.abort()

    # ---------- settings ----------

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            self.cfg.update(dlg.values())
            CONFIG_PATH.write_text(json.dumps(self.cfg, indent=2), encoding="utf-8")
            self.connected = None
            self.state = None
            self.set_connected(False)
            self.refresh_state()

    def closeEvent(self, e):
        self.cancel()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    win = WallClient()
    win.show()
    # files passed on the command line (e.g. "Open with") are sent straight away
    if len(sys.argv) > 1:
        QTimer.singleShot(300, lambda: win.enqueue(sys.argv[1:]))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
