"""停一下：操作 15 分钟耗光电量，停手 30 分钟充满。"""

from __future__ import annotations

import ctypes
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SERVER_NAME = "stop-work-floater"
ERROR_ALREADY_EXISTS = 183


def report_fatal(summary: str, detail: str = "") -> None:
    from store import log

    log(summary if not detail else summary + "\n" + detail)
    ctypes.windll.user32.MessageBoxW(
        None,
        summary + "\n\nDetails were written to %APPDATA%\\StopWork\\log.txt",
        "Stop Work",
        0x00000010,
    )


def acquire_mutex():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\StopWorkFloater")
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    return handle, already


def dump_previews(folder: Path) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    from engine import Engine
    from monitor import ActivityMonitor
    from window import FloatWindow

    folder.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    now = time.monotonic()
    cases = [
        ("work", 0.85, True),
        ("paused", 1.0, False),
        ("rest", 0.35, False),
        ("empty", 0.0, True),
        ("low", 0.12, True),
    ]
    for name, battery, active in cases:
        engine = Engine()
        engine.start(now, battery)
        engine.last_input = now if active else now - 30
        window = FloatWindow(engine, ActivityMonitor(), frozen=True)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.set_forced_view(engine.view(now))
        window.show()
        app.processEvents()
        image = QImage(window.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#5C6772"))
        window.render(image)
        image.save(str(folder / f"{name}.png"))
        window.close()
    app.quit()


def run() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    from engine import Engine
    from monitor import ActivityMonitor
    from store import load_state, log
    from window import FloatWindow, make_font, make_icon

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Stop Work")
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion")
    app.setWindowIcon(make_icon())

    handle, already = acquire_mutex()
    app._mutex = handle  # type: ignore[attr-defined]
    if already:
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if sock.waitForConnected(400):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(400)
            log("second instance asked the window to show")
        else:
            log("second instance found the mutex but could not reach the window")
        return 0

    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    if not server.listen(SERVER_NAME):
        log("single-instance listen failed: " + server.errorString())
    app._server = server  # type: ignore[attr-defined]

    state = load_state()
    engine = Engine()
    engine.start(time.monotonic(), state["battery"])
    monitor = ActivityMonitor()
    monitor.start()
    if not monitor.healthy():
        log("monitor failed at start: " + (monitor.error or "not alive"))

    pos = None
    if state["x"] is not None and state["y"] is not None:
        pos = (state["x"], state["y"])
    window = FloatWindow(engine, monitor, pos)

    def on_connection() -> None:
        client = server.nextPendingConnection()
        window.bring()
        if client is not None:
            client.disconnectFromServer()

    server.newConnection.connect(on_connection)

    tray = QSystemTrayIcon(make_icon(), app)
    tray.setToolTip("Stop Work  ·  drain 15m / charge 30m")
    menu = QMenu()
    menu.setFont(make_font(12))
    menu.addAction("SHOW", window.bring)
    menu.addAction("QUIT", app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: window.bring()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()
    app._tray = tray  # type: ignore[attr-defined]

    app.aboutToQuit.connect(window.persist)
    app.aboutToQuit.connect(monitor.stop)
    window.bring()
    log("started")
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    if len(args) >= 3 and args[1] == "--preview-dump":
        dump_previews(Path(args[2]))
        return 0
    try:
        return run()
    except Exception as exc:
        report_fatal("Stop Work failed to start: " + str(exc), traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
