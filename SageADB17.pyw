"""
SageADB v17 — app icon, sortable/colour-coded Kernel + Partial wakelock tables.
"""
import html
import os
import re
import subprocess
import sys
import tempfile
import zipfile
import ctypes

from PyQt5.QtCore import Qt, QObject, QThread, QRectF, pyqtSignal
from PyQt5.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter,
                         QPen, QPixmap, QTextCursor)
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QLineEdit, QProgressBar, QSpinBox, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)


# ── Icon + wakelock helpers ───────────────────────────────────────────────

def make_app_icon():
    """Use SageADB.ico next to the script if present, otherwise draw an icon."""
    ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SageADB.ico")
    if os.path.exists(ico):
        return QIcon(ico)
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(size / 64.0, size / 64.0)
        grad = QLinearGradient(0, 0, 0, 64)
        grad.setColorAt(0, QColor("#3a3f4b"))
        grad.setColorAt(1, QColor("#1e2026"))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor("#4fc3f7"), 3))
        p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
        green = QColor("#3ddc84")
        p.setPen(QPen(green, 2.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(24, 24, 20, 15)
        p.drawLine(40, 24, 44, 15)
        p.setPen(Qt.NoPen)
        p.setBrush(green)
        p.drawChord(QRectF(16, 22, 32, 32), 0, 180 * 16)
        p.setBrush(QColor("#1e2026"))
        p.drawEllipse(QRectF(24, 29, 4, 4))
        p.drawEllipse(QRectF(36, 29, 4, 4))
        p.setPen(QColor("#4fc3f7"))
        f = QFont("Arial")
        f.setPixelSize(15)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 41, 64, 19), Qt.AlignCenter, "ADB")
        p.end()
        icon.addPixmap(pm)
    return icon


_DUR_RE = re.compile(r"(\d+)(ms|d|h|m|s)")
_DUR_MS = {"d": 86400000, "h": 3600000, "m": 60000, "s": 1000, "ms": 1}
_KERNEL_RE = re.compile(
    r"^Kernel Wake lock\s*(.*?):\s*((?:\d+(?:ms|d|h|m|s)\s*)+)\((\d+)\s*times?\)")
_PARTIAL_RE = re.compile(
    r"^Wake lock\s+(.*?):\s*((?:\d+(?:ms|d|h|m|s)\s*)+)(?:partial\s*)?\((\d+)\s*times?\)")
_UID_RE = re.compile(r"^(u\d+[a-z]\d+|\d+)\s+(.*)$")
_SYSTEM_UIDS = {"1000": "system", "1001": "radio/phone", "1002": "bluetooth",
                "1010": "wifi", "1013": "media", "1021": "gps", "1027": "nfc",
                "2000": "shell", "0": "root"}


def parse_duration_ms(text):
    return sum(int(n) * _DUR_MS[u] for n, u in _DUR_RE.findall(text))


def fmt_duration(ms):
    if ms < 1000:
        return f"{ms}ms"
    d, rem = divmod(ms, 86400000)
    h, rem = divmod(rem, 3600000)
    m, rem = divmod(rem, 60000)
    s = rem / 1000.0
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m {int(s)}s"
    if m:
        return f"{m}m {int(s)}s"
    return f"{s:.1f}s"


def extract_wl_section(text, header):
    """Return logical entries (wrapped lines re-joined) from a batterystats section."""
    out, inside = [], False
    for raw in text.splitlines():
        s = raw.strip()
        if not inside:
            if s.lstrip("# ").startswith(header):
                inside = True
            continue
        if not s:
            if out:
                break
            continue
        if s.startswith("All ") or s.startswith("#"):
            break
        if s.startswith(("Kernel Wake lock", "Wake lock")):
            out.append(s)
        elif out:
            out[-1] += " " + s
    return out


def wl_colour(ms):
    if ms >= 1800000:
        return "#ff5555"
    if ms >= 300000:
        return "#ffb86c"
    if ms >= 60000:
        return "#f1fa8c"
    return "#cccccc"


class NumItem(QTableWidgetItem):
    """Table item that sorts numerically using the value stored in UserRole."""
    def __lt__(self, other):
        a, b = self.data(Qt.UserRole), other.data(Qt.UserRole)
        if a is not None and b is not None:
            return a < b
        return super().__lt__(other)


# ── Workers ───────────────────────────────────────────────────────────────

class LogcatWorker(QObject):
    newLine = pyqtSignal(str)

    def __init__(self, adb_path, filter_text=""):
        super().__init__()
        self.adb_path = adb_path
        self.filter_text = filter_text.lower().strip()
        self._is_running = False
        self.process = None

    def run(self):
        self._is_running = True
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self.process = subprocess.Popen(
                [self.adb_path, "logcat"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, universal_newlines=True, creationflags=flags,
            )
            for line in self.process.stdout:
                if not self._is_running:
                    break
                line = line.rstrip()
                if line and (not self.filter_text or self.filter_text in line.lower()):
                    self.newLine.emit(line)
        except Exception as e:
            self.newLine.emit(f"ERROR: {e}")
        finally:
            if self.process:
                try:
                    self.process.stdout.close()
                    self.process.terminate()
                    self.process.wait()
                except Exception:
                    pass
            self.newLine.emit("--- Logcat stopped ---")

    def stop(self):
        self._is_running = False
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass


class AppSizeWorker(QObject):
    progress = pyqtSignal(int, int)
    sizeResult = pyqtSignal(str, int)
    finished = pyqtSignal()

    def __init__(self, adb_path, packages):
        super().__init__()
        self.adb_path = adb_path
        self.packages = list(packages)
        self._running = True

    def run(self):
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        total = len(self.packages)
        for i, pkg in enumerate(self.packages):
            if not self._running:
                break
            size = 0
            try:
                r = subprocess.run(
                    [self.adb_path, "shell", "pm", "path", pkg],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, creationflags=flags, timeout=5,
                )
                apk_path = ""
                for line in r.stdout.strip().splitlines():
                    if line.startswith("package:"):
                        apk_path = line[len("package:"):].strip()
                        break
                if apk_path:
                    r2 = subprocess.run(
                        [self.adb_path, "shell", "stat", "-c", "%s", apk_path],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, creationflags=flags, timeout=5,
                    )
                    try:
                        size = int(r2.stdout.strip())
                    except Exception:
                        pass
            except Exception:
                pass
            self.sizeResult.emit(pkg, size)
            self.progress.emit(i + 1, total)
        self.finished.emit()

    def stop(self):
        self._running = False


class AnalysisWorker(QObject):
    output = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, adb_path, cmd_args, timeout=30):
        super().__init__()
        self.adb_path = adb_path
        self.cmd_args = cmd_args
        self.timeout = timeout

    def run(self):
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            r = subprocess.run(
                [self.adb_path] + self.cmd_args,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, creationflags=flags, timeout=self.timeout,
            )
            if r.stdout.strip():
                self.output.emit(r.stdout.strip())
            if r.stderr.strip():
                self.output.emit(f"STDERR: {r.stderr.strip()}")
        except subprocess.TimeoutExpired:
            self.output.emit(f"ERROR: Command timed out after {self.timeout}s")
        except Exception as e:
            self.output.emit(f"ERROR: {e}")
        self.finished.emit()


# ── Main Window ─────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.adb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adb.exe")
        if not os.path.exists(self.adb_path):
            self.adb_path = "adb"

        scrcpy_candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scrcpy.exe")
        self.scrcpy_path = scrcpy_candidate if os.path.exists(scrcpy_candidate) else "scrcpy"

        self.logcat_thread = None
        self.logcat_worker = None
        self.size_thread = None
        self.size_worker = None
        self.analysis_thread = None
        self.analysis_worker = None
        self.battery_thread = None
        self.battery_worker = None
        self._battery_parser = None

        self._all_apps = []

        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("SageADB v17")
        self.setWindowIcon(make_app_icon())
        self.resize(1050, 840)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_connect_tab(), "Connect")
        self.tabs.addTab(self._build_install_tab(), "Install")
        self.tabs.addTab(self._build_apps_tab(), "Apps")
        self.tabs.addTab(self._build_display_tab(), "Display")
        self.tabs.addTab(self._build_battery_tab(), "Battery")
        self.tabs.addTab(self._build_reboot_tab(), "Reboot")
        self.tabs.addTab(self._build_analysis_tab(), "Analysis")
        self.tabs.addTab(self._build_logcat_tab(), "Logcat")
        self.tabs.addTab(self._build_scrcpy_tab(), "Scrcpy")

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(130)
        self.log_output.setMaximumHeight(200)
        self.log_output.setFont(QFont("Consolas", 9))

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Command Log:"))
        log_header.addStretch()
        btn_clear_log = QPushButton("Clear")
        btn_save_log = QPushButton("Save Log")
        btn_clear_log.clicked.connect(self.log_output.clear)
        btn_save_log.clicked.connect(self.save_log)
        log_header.addWidget(btn_clear_log)
        log_header.addWidget(btn_save_log)

        root = QVBoxLayout()
        root.addWidget(self.tabs)
        root.addLayout(log_header)
        root.addWidget(self.log_output)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)
        self.statusBar().showMessage("")

    # ── Tab builders ─────────────────────────────────────────────────

    def _build_connect_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        self.usb_button = QPushButton("Connect USB / List Devices")
        self.wifi_ip_input = QLineEdit()
        self.wifi_ip_input.setPlaceholderText("Device IP:port e.g. 192.168.1.100:5555")
        self.wifi_button = QPushButton("Connect WiFi")
        self.disconnect_btn = QPushButton("Disconnect All")

        self.custom_cmd_input = QLineEdit()
        self.custom_cmd_input.setPlaceholderText("Custom adb command (omit 'adb') — press Enter to run")
        self.custom_cmd_btn = QPushButton("Run Command")
        self.custom_cmd_input.returnPressed.connect(self.run_custom_command)

        lay.addWidget(self.usb_button)
        lay.addWidget(self.wifi_ip_input)
        lay.addWidget(self.wifi_button)
        lay.addWidget(self.disconnect_btn)
        lay.addSpacing(12)
        lay.addWidget(QLabel("Custom Command:"))
        lay.addWidget(self.custom_cmd_input)
        lay.addWidget(self.custom_cmd_btn)
        lay.addStretch()

        self.usb_button.clicked.connect(self.adb_connect_usb)
        self.wifi_button.clicked.connect(self.adb_connect_wifi)
        self.disconnect_btn.clicked.connect(self.adb_disconnect)
        self.custom_cmd_btn.clicked.connect(self.run_custom_command)
        return w

    def _build_install_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("APK / APKM / XAPK / APKS path:"))

        path_row = QHBoxLayout()
        self.install_apk_input = QLineEdit()
        self.install_apk_input.setPlaceholderText("Path to package file…")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self.browse_apk)
        path_row.addWidget(self.install_apk_input)
        path_row.addWidget(browse_btn)

        self.install_btn = QPushButton("Install Package")
        self.install_btn.clicked.connect(self.install_app)

        lay.addLayout(path_row)
        lay.addWidget(self.install_btn)
        lay.addStretch()
        return w

    def _build_apps_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        top = QHBoxLayout()
        self.app_search = QLineEdit()
        self.app_search.setPlaceholderText("Search packages…")
        self.app_search.textChanged.connect(self._apply_app_filter)

        self.app_filter_combo = QComboBox()
        self.app_filter_combo.addItems(["All", "Enabled", "Disabled"])
        self.app_filter_combo.activated.connect(self._apply_app_filter)

        self.app_sort_combo = QComboBox()
        self.app_sort_combo.addItems(["Name A-Z", "Name Z-A", "Size asc", "Size desc"])
        self.app_sort_combo.activated.connect(self._apply_app_filter)

        top.addWidget(QLabel("Search:"))
        top.addWidget(self.app_search, 3)
        top.addWidget(QLabel("Filter:"))
        top.addWidget(self.app_filter_combo)
        top.addWidget(QLabel("Sort:"))
        top.addWidget(self.app_sort_combo)

        self.apps_list = QListWidget()
        self.app_count_label = QLabel("0 packages")

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.load_sizes_btn = QPushButton("Load Sizes")
        self.enable_btn = QPushButton("Enable")
        self.disable_btn = QPushButton("Disable")
        self.force_stop_btn = QPushButton("Force Stop")
        for b in (self.refresh_btn, self.load_sizes_btn, self.enable_btn,
                  self.disable_btn, self.force_stop_btn):
            btn_row.addWidget(b)

        self.size_progress = QProgressBar()
        self.size_progress.setVisible(False)

        lay.addLayout(top)
        lay.addWidget(self.apps_list)
        lay.addWidget(self.app_count_label)
        lay.addLayout(btn_row)
        lay.addWidget(self.size_progress)

        self.refresh_btn.clicked.connect(self.refresh_app_list)
        self.load_sizes_btn.clicked.connect(self.load_app_sizes)
        self.enable_btn.clicked.connect(self.enable_app)
        self.disable_btn.clicked.connect(self.disable_app)
        self.force_stop_btn.clicked.connect(self.force_stop_app)
        return w

    def _build_display_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("Set Display DPI:"))
        dpi_row = QHBoxLayout()
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(100, 800)
        self.dpi_spin.setValue(320)
        btn_dpi = QPushButton("Apply DPI")
        btn_rdpi = QPushButton("Reset DPI")
        dpi_row.addWidget(self.dpi_spin)
        dpi_row.addWidget(btn_dpi)
        dpi_row.addWidget(btn_rdpi)
        lay.addLayout(dpi_row)

        lay.addSpacing(10)
        lay.addWidget(QLabel("Animation Scale:"))
        anim_row = QHBoxLayout()
        btn_anim0 = QPushButton("Disable (0x)")
        btn_anim05 = QPushButton("Fast (0.5x)")
        btn_anim1 = QPushButton("Normal (1x)")
        anim_row.addWidget(btn_anim0)
        anim_row.addWidget(btn_anim05)
        anim_row.addWidget(btn_anim1)
        lay.addLayout(anim_row)
        lay.addStretch()

        btn_dpi.clicked.connect(self.set_dpi)
        btn_rdpi.clicked.connect(lambda: self.run_adb_command(
            [self.adb_path, "shell", "wm", "density", "reset"]))
        btn_anim0.clicked.connect(lambda: self._set_animations("0"))
        btn_anim05.clicked.connect(lambda: self._set_animations("0.5"))
        btn_anim1.clicked.connect(lambda: self._set_animations("1"))
        return w

    def _build_reboot_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        for label, mode in [("Reboot System", ""), ("Reboot Recovery", "recovery"),
                             ("Reboot Bootloader", "bootloader")]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, m=mode: self.reboot_device(m))
            lay.addWidget(btn)
        lay.addStretch()
        return w

    # ── Battery tab ──────────────────────────────────────────────────

    def _build_battery_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("Battery / Deep-Sleep Diagnostics:"))
        row1 = QHBoxLayout()
        row2 = QHBoxLayout()

        btn_rank = QPushButton("Top Battery Users (mAh)")
        btn_live_wl = QPushButton("Active Wake Locks (Live)")
        btn_kernel_wl = QPushButton("Kernel Wakelocks")
        btn_partial_wl = QPushButton("Partial Wakelocks")
        btn_doze = QPushButton("Doze / Deep Sleep State")
        btn_alarms = QPushButton("Alarm Wakeups")
        btn_battinfo = QPushButton("Battery Info")
        btn_reset = QPushButton("Reset Battery Stats")

        for b in (btn_rank, btn_live_wl, btn_kernel_wl, btn_partial_wl):
            row1.addWidget(b)
        for b in (btn_doze, btn_alarms, btn_battinfo, btn_reset):
            row2.addWidget(b)

        lay.addLayout(row1)
        lay.addLayout(row2)

        lay.addSpacing(6)
        lay.addWidget(QLabel("Ranked Battery Users (tap 'Top Battery Users' to populate):"))
        self.battery_rank_list = QListWidget()
        self.battery_rank_list.setMaximumHeight(110)
        lay.addWidget(self.battery_rank_list)


        lay.addSpacing(4)
        self.wl_title = QLabel("Wakelocks (since charge): press 'Kernel Wakelocks' or 'Partial Wakelocks'")
        lay.addWidget(self.wl_title)
        wl_ctrl = QHBoxLayout()
        self.wl_filter = QLineEdit()
        self.wl_filter.setPlaceholderText("Filter by name / package…")
        self.wl_filter.textChanged.connect(self._wl_apply_filter)
        self.wl_sort_combo = QComboBox()
        self.wl_sort_combo.addItems(["Time held (high-low)", "Count (high-low)",
                                     "Avg per hold (high-low)", "Name (A-Z)"])
        self.wl_sort_combo.activated.connect(self._wl_apply_sort)
        wl_ctrl.addWidget(QLabel("Filter:"))
        wl_ctrl.addWidget(self.wl_filter, 3)
        wl_ctrl.addWidget(QLabel("Sort:"))
        wl_ctrl.addWidget(self.wl_sort_combo, 2)
        lay.addLayout(wl_ctrl)
        legend = QLabel(
            '<span style="color:#ff5555">&#9632; 30 min+</span> &nbsp; '
            '<span style="color:#ffb86c">&#9632; 5 min+</span> &nbsp; '
            '<span style="color:#f1fa8c">&#9632; 1 min+</span> &nbsp; '
            '<span style="color:#cccccc">&#9632; under 1 min</span> &nbsp; '
            '<span style="color:#8be9fd">&#9632; count 1000+</span>')
        lay.addWidget(legend)
        self.wl_table = QTableWidget(0, 5)
        self.wl_table.setHorizontalHeaderLabels(["Wakelock", "Owner", "Time held", "Count", "Avg / hold"])
        self.wl_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.wl_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.wl_table.setSortingEnabled(True)
        hh = self.wl_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        lay.addWidget(self.wl_table, 3)

        out_hdr = QHBoxLayout()
        out_hdr.addWidget(QLabel("Output:"))
        out_hdr.addStretch()
        self.battery_busy = QLabel("")
        btn_clear_b = QPushButton("Clear")
        btn_save_b = QPushButton("Save")
        out_hdr.addWidget(self.battery_busy)
        out_hdr.addWidget(btn_clear_b)
        out_hdr.addWidget(btn_save_b)
        lay.addLayout(out_hdr)

        self.battery_output = QTextEdit()
        self.battery_output.setReadOnly(True)
        self.battery_output.setFont(QFont("Consolas", 9))
        lay.addWidget(self.battery_output, 1)

        btn_rank.clicked.connect(self._refresh_battery_ranking)
        btn_live_wl.clicked.connect(self._show_active_wakelocks)
        btn_kernel_wl.clicked.connect(lambda: self._show_wakelock_table("kernel"))
        btn_partial_wl.clicked.connect(lambda: self._show_wakelock_table("partial"))
        btn_doze.clicked.connect(self._show_doze_state)
        btn_alarms.clicked.connect(self._show_alarms)
        btn_battinfo.clicked.connect(self._show_battery_info)
        btn_reset.clicked.connect(self._reset_battery_stats)
        btn_clear_b.clicked.connect(self.battery_output.clear)
        btn_save_b.clicked.connect(self._save_battery_output)
        return w

    def _run_battery_command(self, args, parser=None, timeout=60):
        if self.battery_thread and self.battery_thread.isRunning():
            self.log("Wait for current battery command to finish.", "info")
            return
        cmd_str = "adb " + " ".join(args)
        self.battery_output.append(f"\n$ {cmd_str}\n{'-' * 60}")
        self.battery_busy.setText("Running...")
        self._battery_parser = parser

        self.battery_worker = AnalysisWorker(self.adb_path, args, timeout)
        self.battery_thread = QThread()
        self.battery_worker.moveToThread(self.battery_thread)
        self.battery_thread.started.connect(self.battery_worker.run)
        self.battery_worker.output.connect(self._on_battery_output)
        self.battery_worker.finished.connect(self._on_battery_done)
        self.battery_thread.start()

    def _on_battery_output(self, text):
        if self._battery_parser:
            try:
                self._battery_parser(text)
            except Exception as e:
                self.battery_output.append(f"[parse error: {e}]")
            self._battery_parser = None
        else:
            self.battery_output.append(text)

    def _on_battery_done(self):
        self.battery_thread.quit()
        self.battery_thread.wait()
        self.battery_busy.setText("")

    def _uid_map(self):
        """Map decimal uid -> package name via `pm list packages -U`."""
        out = self.run_adb_command(
            [self.adb_path, "shell", "pm", "list", "packages", "-U"], silent=True)
        mapping = {}
        if out:
            for line in out.splitlines():
                m = re.match(r"package:(\S+)\s+uid:(\d+)", line.strip())
                if m:
                    mapping[m.group(2)] = m.group(1)
        return mapping

    @staticmethod
    def _decode_uid_token(token):
        """Convert batterystats uid tokens like 'u0a201' or '1000' to a decimal uid string."""
        m = re.match(r"u(\d+)a(\d+)", token)
        if m:
            user, appnum = int(m.group(1)), int(m.group(2))
            return str(user * 100000 + 10000 + appnum)
        if token.isdigit():
            return token
        return None

    def _parse_battery_ranking(self, text):
        uid_map = self._uid_map()
        entries = []
        in_section = False
        for line in text.splitlines():
            if "Estimated power use" in line:
                in_section = True
                continue
            if in_section:
                if not line.strip() or (line.strip()[0].isupper() and ":" not in line and "Uid" not in line):
                    if entries and not line.strip().startswith(("Uid", "Screen", "Cell", "Wifi", "Bluetooth", "Idle", "Capacity")):
                        break
                m = re.match(r"\s*Uid\s+(\S+):\s+([\d.]+)", line)
                if m:
                    token, mah = m.group(1), float(m.group(2))
                    uid_dec = self._decode_uid_token(token)
                    label = uid_map.get(uid_dec, f"uid:{token}")
                    entries.append((label, mah))
                    continue
                m2 = re.match(r"\s*(Screen|Cell standby|Cell|Wifi|Bluetooth|Idle|Camera|Flashlight):\s+([\d.]+)", line)
                if m2:
                    entries.append((f"[{m2.group(1)}]", float(m2.group(2))))

        entries.sort(key=lambda e: e[1], reverse=True)
        self.battery_rank_list.clear()
        if not entries:
            self.battery_output.append(
                "No 'Estimated power use' entries parsed. Raw output appended below "
                "(format may differ on this Android version) -- see raw dump.")
            self.battery_output.append(text)
            return
        for label, mah in entries[:40]:
            item = QListWidgetItem(f"{mah:6.2f} mAh  -  {label}")
            self.battery_rank_list.addItem(item)
        self.log(f"Parsed {len(entries)} battery-use entries.", "info")

    def _refresh_battery_ranking(self):
        self._run_battery_command(
            ["shell", "dumpsys", "batterystats", "--charged"],
            parser=self._parse_battery_ranking)

    def _filter_wakelocks(self, text):
        keep = []
        for line in text.splitlines():
            if re.search(r"WAKE_LOCK|Wake Locks|PowerManager\.WakeLock|tag=", line, re.IGNORECASE):
                keep.append(line.strip())
        self.battery_output.append(
            "\n".join(keep) if keep else "No active wake locks found (device may be idle/asleep).")

    def _show_active_wakelocks(self):
        self._run_battery_command(["shell", "dumpsys", "power"], parser=self._filter_wakelocks)

    def _show_wakelock_table(self, kind):
        self._run_battery_command(
            ["shell", "dumpsys", "batterystats", "--charged"],
            parser=lambda text: self._parse_wl_table(text, kind))

    def _parse_wl_table(self, text, kind):
        if kind == "kernel":
            header, rx = "All kernel wake locks", _KERNEL_RE
        else:
            header, rx = "All partial wake locks", _PARTIAL_RE
        lines = extract_wl_section(text, header)
        uid_map = self._uid_map() if kind == "partial" else {}
        rows = []
        for ln in lines:
            m = rx.match(ln)
            if not m:
                continue
            name, dur, cnt = m.group(1).strip(), m.group(2), int(m.group(3))
            owner = "kernel" if kind == "kernel" else ""
            if kind == "partial":
                um = _UID_RE.match(name)
                if um:
                    token, name = um.group(1), um.group(2).strip()
                    dec = self._decode_uid_token(token)
                    owner = uid_map.get(dec) or _SYSTEM_UIDS.get(dec or token) or token
                else:
                    owner = "(system)"
            rows.append((name or "(unnamed)", owner, parse_duration_ms(dur), cnt))

        self.wl_table.setSortingEnabled(False)
        self.wl_table.setRowCount(0)
        self.wl_table.setColumnHidden(1, kind == "kernel")
        if not rows:
            self.wl_title.setText(f"No {kind} wakelock entries parsed.")
            self.battery_output.append(
                f"Could not find/parse an '{header}:' section in this device's batterystats. "
                "Lines mentioning wake locks:")
            self.battery_output.append("\n".join(
                l.strip() for l in text.splitlines() if "wake lock" in l.lower())[:6000])
            self.wl_table.setSortingEnabled(True)
            return

        self.wl_table.setRowCount(len(rows))
        for r, (name, owner, ms, cnt) in enumerate(rows):
            avg = ms // cnt if cnt else ms
            colour = QColor(wl_colour(ms))
            cells = [
                (QTableWidgetItem(name), None),
                (QTableWidgetItem(owner), None),
                (NumItem(fmt_duration(ms)), ms),
                (NumItem(f"{cnt:,}"), cnt),
                (NumItem(fmt_duration(avg)), avg),
            ]
            for c, (item, val) in enumerate(cells):
                if val is not None:
                    item.setData(Qt.UserRole, val)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setForeground(QColor("#8be9fd") if (c == 3 and cnt >= 1000) else colour)
                if ms >= 1800000:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.wl_table.setItem(r, c, item)

        self.wl_table.setSortingEnabled(True)
        self._wl_apply_sort()
        self._wl_apply_filter()
        total = sum(x[2] for x in rows)
        self.wl_title.setText(
            f"{'Kernel' if kind == 'kernel' else 'Partial'} wakelocks since charge: "
            f"{len(rows)} entries, {fmt_duration(total)} total held time")
        self.log(f"Parsed {len(rows)} {kind} wakelocks.", "info")

    def _wl_apply_sort(self, *_):
        col, order = {0: (2, Qt.DescendingOrder), 1: (3, Qt.DescendingOrder),
                      2: (4, Qt.DescendingOrder), 3: (0, Qt.AscendingOrder)
                      }[self.wl_sort_combo.currentIndex()]
        self.wl_table.sortItems(col, order)

    def _wl_apply_filter(self, *_):
        needle = self.wl_filter.text().lower().strip()
        for r in range(self.wl_table.rowCount()):
            n, o = self.wl_table.item(r, 0), self.wl_table.item(r, 1)
            hay = ((n.text() if n else "") + " " + (o.text() if o else "")).lower()
            self.wl_table.setRowHidden(r, bool(needle) and needle not in hay)

    def _filter_doze(self, text):
        keep = []
        for line in text.splitlines():
            if re.search(r"mState|mLightState|Whitelist|whitelist|Idle", line):
                keep.append(line.strip())
        self.battery_output.append("\n".join(keep) if keep else text)

    def _show_doze_state(self):
        self._run_battery_command(["shell", "dumpsys", "deviceidle"], parser=self._filter_doze)

    def _filter_alarms(self, text):
        keep = []
        capture = False
        for line in text.splitlines():
            if "Top Alarms" in line:
                capture = True
            if capture:
                keep.append(line.strip())
                if len(keep) > 60:
                    break
        self.battery_output.append("\n".join(keep) if keep else text)

    def _show_alarms(self):
        self._run_battery_command(["shell", "dumpsys", "alarm"], parser=self._filter_alarms)

    def _show_battery_info(self):
        self._run_battery_command(["shell", "dumpsys", "battery"])

    def _reset_battery_stats(self):
        confirm = QMessageBox.question(
            self, "Reset Battery Stats",
            "This clears accumulated battery-history counters on the device so future "
            "'since charge' readings start fresh. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.run_adb_command([self.adb_path, "shell", "dumpsys", "batterystats", "--reset"])
            self.log("Battery stats reset.", "info")

    def _save_battery_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Battery Output", "battery_analysis.txt", "Text Files (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.battery_output.toPlainText())
            self.log(f"Saved -> {path}", "info")

    # ── Analysis tab ─────────────────────────────────────────────────

    def _build_analysis_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("Quick Commands:"))
        row1 = QHBoxLayout()
        row2 = QHBoxLayout()
        presets = [
            ("Memory Overview", ["shell", "dumpsys", "meminfo"]),
            ("Top by CPU", ["shell", "top", "-n", "1", "-s", "cpu"]),
            ("Top by Memory", ["shell", "top", "-n", "1", "-s", "rss"]),
            ("CPU Info", ["shell", "dumpsys", "cpuinfo"]),
            ("Battery", ["shell", "dumpsys", "battery"]),
            ("Disk Usage", ["shell", "df", "-h"]),
            ("Network Stats", ["shell", "dumpsys", "netstats"]),
            ("System Props", ["shell", "getprop"]),
        ]
        for i, (label, args) in enumerate(presets):
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, a=args: self._run_analysis(a))
            (row1 if i < 4 else row2).addWidget(btn)
        lay.addLayout(row1)
        lay.addLayout(row2)

        lay.addSpacing(6)
        lay.addWidget(QLabel("Per-App Analysis:"))
        pkg_row = QHBoxLayout()
        self.analysis_pkg_input = QLineEdit()
        self.analysis_pkg_input.setPlaceholderText("Package name (e.g. org.xbmc.kodi)")
        btn_app_mem = QPushButton("Memory")
        btn_app_act = QPushButton("Activity")
        btn_app_pkg = QPushButton("Package Info")
        pkg_row.addWidget(self.analysis_pkg_input, 3)
        pkg_row.addWidget(btn_app_mem)
        pkg_row.addWidget(btn_app_act)
        pkg_row.addWidget(btn_app_pkg)
        lay.addLayout(pkg_row)

        lay.addSpacing(6)
        lay.addWidget(QLabel("Custom Shell Command:"))
        cust_row = QHBoxLayout()
        self.analysis_custom_input = QLineEdit()
        self.analysis_custom_input.setPlaceholderText("e.g. cat /proc/meminfo or ps -A")
        btn_cust = QPushButton("Run")
        cust_row.addWidget(self.analysis_custom_input, 3)
        cust_row.addWidget(btn_cust)
        self.analysis_custom_input.returnPressed.connect(self._run_custom_analysis)
        btn_cust.clicked.connect(self._run_custom_analysis)
        lay.addLayout(cust_row)

        out_hdr = QHBoxLayout()
        out_hdr.addWidget(QLabel("Output:"))
        out_hdr.addStretch()
        self.analysis_busy = QLabel("")
        btn_clear_a = QPushButton("Clear")
        btn_save_a = QPushButton("Save")
        out_hdr.addWidget(self.analysis_busy)
        out_hdr.addWidget(btn_clear_a)
        out_hdr.addWidget(btn_save_a)
        lay.addLayout(out_hdr)

        self.analysis_output = QTextEdit()
        self.analysis_output.setReadOnly(True)
        self.analysis_output.setFont(QFont("Consolas", 9))
        lay.addWidget(self.analysis_output)

        btn_app_mem.clicked.connect(self._run_app_meminfo)
        btn_app_act.clicked.connect(self._run_app_activity)
        btn_app_pkg.clicked.connect(self._run_app_pkginfo)
        btn_clear_a.clicked.connect(self.analysis_output.clear)
        btn_save_a.clicked.connect(self.save_analysis)
        return w

    def _build_logcat_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        ctrl = QHBoxLayout()
        self.logcat_filter_input = QLineEdit()
        self.logcat_filter_input.setPlaceholderText("Filter by tag / package / keyword…")
        self.start_logcat_btn = QPushButton("Start")
        self.stop_logcat_btn = QPushButton("Stop")
        btn_clear_lc = QPushButton("Clear")
        btn_save_lc = QPushButton("Save")
        self.autoscroll_check = QCheckBox("Auto-scroll")
        self.autoscroll_check.setChecked(True)

        ctrl.addWidget(QLabel("Filter:"))
        ctrl.addWidget(self.logcat_filter_input, 2)
        ctrl.addWidget(self.start_logcat_btn)
        ctrl.addWidget(self.stop_logcat_btn)
        ctrl.addWidget(btn_clear_lc)
        ctrl.addWidget(btn_save_lc)
        ctrl.addWidget(self.autoscroll_check)

        self.logcat_output = QTextEdit()
        self.logcat_output.setReadOnly(True)
        self.logcat_output.setFont(QFont("Consolas", 8))

        lay.addLayout(ctrl)
        lay.addWidget(self.logcat_output)

        self.start_logcat_btn.clicked.connect(self.start_logcat)
        self.stop_logcat_btn.clicked.connect(self.stop_logcat)
        btn_clear_lc.clicked.connect(self.logcat_output.clear)
        btn_save_lc.clicked.connect(self.save_logcat)
        return w

    # ── Connect actions ──────────────────────────────────────────────

    def adb_connect_usb(self):
        self.run_adb_command([self.adb_path, "devices"])

    def adb_connect_wifi(self):
        ip = self.wifi_ip_input.text().strip()
        if ip:
            self.run_adb_command([self.adb_path, "connect", ip])
            self.statusBar().showMessage(f"Connecting to {ip}...")

    def adb_disconnect(self):
        self.run_adb_command([self.adb_path, "disconnect"])
        self.statusBar().showMessage("Disconnected")

    def run_custom_command(self):
        cmd = self.custom_cmd_input.text().strip()
        if cmd:
            self.run_adb_command([self.adb_path] + cmd.split())

    # ── Install actions ──────────────────────────────────────────────

    def browse_apk(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Package", "",
            "Android Packages (*.apk *.apkm *.xapk *.apks)")
        if path:
            self.install_apk_input.setText(path)

    def get_device_abi(self):
        try:
            r = subprocess.run(
                [self.adb_path, "shell", "getprop", "ro.product.cpu.abi"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            abi = r.stdout.strip()
            if abi:
                self.log(f"Device ABI: {abi}", "info")
            return abi
        except Exception as e:
            self.log(f"Failed to get ABI: {e}", "error")
            return None

    def install_app(self):
        path = self.install_apk_input.text().strip()
        if not path:
            self.log("No APK path specified.", "info")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext == ".apk":
            self.run_adb_command([self.adb_path, "install", "-r", path])
        elif ext == ".apkm":
            temp_dir = tempfile.mkdtemp(prefix="sageadb_")
            with zipfile.ZipFile(path, "r") as z:
                z.extractall(temp_dir)
            apks = [os.path.join(temp_dir, f)
                    for f in os.listdir(temp_dir) if f.endswith(".apk")]
            abi = self.get_device_abi()
            if abi:
                filtered = [f for f in apks if abi in os.path.basename(f)
                            or "base.apk" in f]
                apks = filtered if filtered else apks
            self.run_adb_command([self.adb_path, "install-multiple"] + apks)
        else:
            self.run_adb_command([self.adb_path, "install", "-r", path])

    # ── Apps actions ─────────────────────────────────────────────────

    def refresh_app_list(self):
        self._all_apps.clear()
        self.apps_list.clear()

        all_out = self.run_adb_command(
            [self.adb_path, "shell", "pm", "list", "packages"], silent=True)
        dis_out = self.run_adb_command(
            [self.adb_path, "shell", "pm", "list", "packages", "-d"], silent=True)

        disabled = set()
        if dis_out:
            for line in dis_out.splitlines():
                pkg = line.replace("package:", "").strip()
                if pkg:
                    disabled.add(pkg)

        if all_out:
            for line in all_out.splitlines():
                pkg = line.replace("package:", "").strip()
                if pkg:
                    self._all_apps.append(
                        {"pkg": pkg, "enabled": pkg not in disabled, "size": None})

        self._apply_app_filter()
        self.log(f"Loaded {len(self._all_apps)} packages.", "info")

    def _apply_app_filter(self):
        search = self.app_search.text().lower().strip()
        filter_mode = self.app_filter_combo.currentText()
        sort_mode = self.app_sort_combo.currentText()

        apps = list(self._all_apps)
        if filter_mode == "Enabled":
            apps = [a for a in apps if a["enabled"]]
        elif filter_mode == "Disabled":
            apps = [a for a in apps if not a["enabled"]]
        if search:
            apps = [a for a in apps if search in a["pkg"].lower()]

        if sort_mode == "Name A-Z":
            apps.sort(key=lambda a: a["pkg"].lower())
        elif sort_mode == "Name Z-A":
            apps.sort(key=lambda a: a["pkg"].lower(), reverse=True)
        elif sort_mode == "Size asc":
            apps.sort(key=lambda a: a["size"] or 0)
        elif sort_mode == "Size desc":
            apps.sort(key=lambda a: a["size"] or 0, reverse=True)

        self.apps_list.clear()
        for a in apps:
            size_str = self._fmt_size(a["size"]) if a["size"] is not None else "-"
            item = QListWidgetItem(f"{a['pkg']} [{size_str}]")
            item.setData(Qt.UserRole, a["pkg"])
            if not a["enabled"]:
                item.setForeground(QColor("#ff6b6b"))
            else:
                item.setForeground(QColor("#cccccc"))
            self.apps_list.addItem(item)

        self.app_count_label.setText(
            f"{len(apps)} shown / {len(self._all_apps)} total")

    @staticmethod
    def _fmt_size(b):
        if b >= 1_048_576:
            return f"{b/1_048_576:.1f} MB"
        if b >= 1024:
            return f"{b/1024:.1f} KB"
        return f"{b} B"

    def load_app_sizes(self):
        if not self._all_apps:
            self.log("Refresh app list first.", "info")
            return
        if self.size_thread and self.size_thread.isRunning():
            self.log("Size loading already running.", "info")
            return
        pkgs = [a["pkg"] for a in self._all_apps]
        self.size_worker = AppSizeWorker(self.adb_path, pkgs)
        self.size_thread = QThread()
        self.size_worker.moveToThread(self.size_thread)
        self.size_thread.started.connect(self.size_worker.run)
        self.size_worker.sizeResult.connect(self._on_size_result)
        self.size_worker.progress.connect(self._on_size_progress)
        self.size_worker.finished.connect(self._on_size_finished)
        self.size_thread.start()
        self.size_progress.setVisible(True)
        self.size_progress.setValue(0)
        self.load_sizes_btn.setEnabled(False)
        self.log(f"Loading sizes for {len(pkgs)} packages...", "info")

    def _on_size_result(self, pkg, size):
        for a in self._all_apps:
            if a["pkg"] == pkg:
                a["size"] = size
                break

    def _on_size_progress(self, cur, total):
        self.size_progress.setMaximum(total)
        self.size_progress.setValue(cur)

    def _on_size_finished(self):
        self.size_thread.quit()
        self.size_thread.wait()
        self.size_progress.setVisible(False)
        self.load_sizes_btn.setEnabled(True)
        self.log("Sizes loaded.", "info")
        self._apply_app_filter()

    def _selected_pkg(self):
        item = self.apps_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def enable_app(self):
        pkg = self._selected_pkg()
        if pkg:
            self.run_adb_command([self.adb_path, "shell", "pm", "enable", "--user", "0", pkg])
            self.refresh_app_list()

    def disable_app(self):
        pkg = self._selected_pkg()
        if pkg:
            self.run_adb_command(
                [self.adb_path, "shell", "pm", "disable-user", "--user", "0", pkg])
            self.refresh_app_list()

    def force_stop_app(self):
        pkg = self._selected_pkg()
        if pkg:
            self.run_adb_command([self.adb_path, "shell", "am", "force-stop", pkg])

    # ── Display actions ──────────────────────────────────────────────

    def set_dpi(self):
        self.run_adb_command(
            [self.adb_path, "shell", "wm", "density", str(self.dpi_spin.value())])

    def _set_animations(self, scale):
        for key in ("window_animation_scale",
                    "transition_animation_scale",
                    "animator_duration_scale"):
            self.run_adb_command(
                [self.adb_path, "shell", "settings", "put", "global", key, scale])

    # ── Reboot ────────────────────────────────────────────────────────

    def reboot_device(self, mode):
        cmd = [self.adb_path, "reboot"]
        if mode:
            cmd.append(mode)
        self.run_adb_command(cmd)

    # ── Analysis actions ─────────────────────────────────────────────

    def _run_analysis(self, args):
        if self.analysis_thread and self.analysis_thread.isRunning():
            self.log("Wait for current analysis to finish.", "info")
            return
        cmd_str = "adb " + " ".join(args)
        self.analysis_output.append(f"\n$ {cmd_str}\n{'-' * 60}")
        self.analysis_busy.setText("Running...")

        self.analysis_worker = AnalysisWorker(self.adb_path, args)
        self.analysis_thread = QThread()
        self.analysis_worker.moveToThread(self.analysis_thread)
        self.analysis_thread.started.connect(self.analysis_worker.run)
        self.analysis_worker.output.connect(self.analysis_output.append)
        self.analysis_worker.finished.connect(self._on_analysis_done)
        self.analysis_thread.start()

    def _run_custom_analysis(self):
        cmd = self.analysis_custom_input.text().strip()
        if cmd:
            self._run_analysis(["shell"] + cmd.split())

    def _run_app_meminfo(self):
        pkg = self.analysis_pkg_input.text().strip()
        if pkg:
            self._run_analysis(["shell", "dumpsys", "meminfo", pkg])
        else:
            self.log("Enter a package name.", "info")

    def _run_app_activity(self):
        pkg = self.analysis_pkg_input.text().strip()
        if pkg:
            self._run_analysis(["shell", "dumpsys", "activity", pkg])
        else:
            self.log("Enter a package name.", "info")

    def _run_app_pkginfo(self):
        pkg = self.analysis_pkg_input.text().strip()
        if pkg:
            self._run_analysis(["shell", "dumpsys", "package", pkg])
        else:
            self.log("Enter a package name.", "info")

    def _on_analysis_done(self):
        self.analysis_thread.quit()
        self.analysis_thread.wait()
        self.analysis_busy.setText("")

    def save_analysis(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Analysis Output", "analysis.txt", "Text Files (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.analysis_output.toPlainText())
            self.log(f"Saved -> {path}", "info")

    # ── Logcat actions ───────────────────────────────────────────────

    def start_logcat(self):
        if self.logcat_thread and self.logcat_thread.isRunning():
            self.log("Logcat already running.", "info")
            return
        filt = self.logcat_filter_input.text().strip()
        self.logcat_worker = LogcatWorker(self.adb_path, filt)
        self.logcat_thread = QThread()
        self.logcat_worker.moveToThread(self.logcat_thread)
        self.logcat_thread.started.connect(self.logcat_worker.run)
        self.logcat_worker.newLine.connect(self._on_logcat_line)
        self.logcat_thread.start()
        self.start_logcat_btn.setEnabled(False)
        self.stop_logcat_btn.setEnabled(True)
        self.log("Logcat started.", "info")

    def _on_logcat_line(self, line):
        esc = html.escape(line)
        lvl = ""
        for part in line.split():
            if len(part) == 1 and part in "EWIDVF":
                lvl = part
                break
        color_map = {
            "E": "#ff6b6b",
            "W": "#ffb86c",
            "I": "#8be9fd",
            "D": "#a0a0a0",
            "V": "#6272a4",
            "F": "#ff5555",
        }
        color = color_map.get(lvl, "#cccccc")
        self.logcat_output.insertHtml(f'<span style="color:{color}">{esc}</span><br>')
        if self.autoscroll_check.isChecked():
            self.logcat_output.moveCursor(QTextCursor.End)

    def stop_logcat(self):
        if self.logcat_worker:
            self.logcat_worker.stop()
        if self.logcat_thread:
            self.logcat_thread.quit()
            self.logcat_thread.wait()
        self.logcat_thread = None
        self.logcat_worker = None
        self.start_logcat_btn.setEnabled(True)
        self.stop_logcat_btn.setEnabled(False)

    def save_logcat(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Logcat", "logcat.txt", "Text Files (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.logcat_output.toPlainText())
            self.log(f"Logcat saved -> {path}", "info")

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Command Log", "sageadb_log.txt", "Text Files (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_output.toPlainText())
            self.log(f"Log saved -> {path}", "info")

    # ── Logging ──────────────────────────────────────────────────────

    def log(self, message: str, kind: str = "info"):
        colors = {
            "cmd": "#f0c040",
            "output": "#cccccc",
            "error": "#ff6b6b",
            "info": "#4fc3f7",
        }
        color = colors.get(kind, "#cccccc")
        esc = html.escape(str(message))
        self.log_output.insertHtml(f'<span style="color:{color}">{esc}</span><br>')
        self.log_output.moveCursor(QTextCursor.End)

    def run_adb_command(self, args, silent=False):
        if not silent:
            self.log("$ " + " ".join(str(a) for a in args), "cmd")
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            result = subprocess.run(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, creationflags=flags)
            if result.stdout.strip() and not silent:
                self.log(result.stdout.strip(), "output")
            if result.stderr.strip() and not silent:
                self.log(result.stderr.strip(), "error")
            return result.stdout
        except Exception as e:
            if not silent:
                self.log(str(e), "error")
                QMessageBox.critical(self, "Error", str(e))
            return None

    # ── Scrcpy tab ───────────────────────────────────────────────────

    def _build_scrcpy_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("scrcpy path:"))
        self.scrcpy_path_input = QLineEdit(self.scrcpy_path)
        self.scrcpy_path_input.setPlaceholderText("Path to scrcpy(.exe) or just 'scrcpy' if on PATH")
        btn_scrcpy_browse = QPushButton("Browse…")
        btn_scrcpy_browse.clicked.connect(self._browse_scrcpy)
        path_row.addWidget(self.scrcpy_path_input, 4)
        path_row.addWidget(btn_scrcpy_browse)
        lay.addLayout(path_row)

        lay.addSpacing(8)
        lay.addWidget(QLabel("Quick Presets:"))

        presets = [
            ("Mirror (default)", []),
            ("Mirror - screen off", ["--turn-screen-off", "--stay-awake"]),
            ("Mirror - view only", ["--no-control"]),
            ("Mirror - fullscreen", ["-f"]),
            ("Mirror - always on top", ["--always-on-top"]),
            ("Show touches", ["--show-touches", "--stay-awake"]),
            ("High quality (H.265)", ["--video-codec=h265", "--max-size=1920",
                                       "--max-fps=60", "--video-bit-rate=8M"]),
            ("Low latency / USB", ["--max-fps=60", "--video-bit-rate=4M",
                                    "--max-size=1280"]),
            ("Audio mirror only", ["--no-video", "--no-control"]),
            ("Audio dup (device+PC)", ["--audio-dup"]),
            ("Mic capture", ["--audio-source=mic"]),
            ("Camera mirror", ["--video-source=camera", "--camera-facing=back"]),
            ("Camera front", ["--video-source=camera", "--camera-facing=front"]),
            ("OTG (kbd+mouse only)", ["--otg"]),
            ("Gamepad passthrough", ["--gamepad=uhid"]),
        ]

        grid_widget = QWidget()
        grid_lay = QVBoxLayout(grid_widget)
        grid_lay.setContentsMargins(0, 0, 0, 0)
        row_lay = None
        for i, (label, args) in enumerate(presets):
            if i % 4 == 0:
                row_lay = QHBoxLayout()
                grid_lay.addLayout(row_lay)
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, a=args: self._launch_scrcpy(a))
            row_lay.addWidget(btn)
        remainder = len(presets) % 4
        if remainder:
            for _ in range(4 - remainder):
                row_lay.addStretch(1)

        lay.addWidget(grid_widget)

        lay.addSpacing(8)
        lay.addWidget(QLabel("Record:"))
        rec_row = QHBoxLayout()
        self.scrcpy_rec_path = QLineEdit()
        self.scrcpy_rec_path.setPlaceholderText("Output file, e.g. capture.mp4 or capture.mkv")
        btn_rec_browse = QPushButton("Browse…")
        btn_rec_browse.clicked.connect(self._browse_scrcpy_rec)
        btn_rec_start = QPushButton("Record + Mirror")
        btn_rec_nodisp = QPushButton("Record only (no display)")
        btn_rec_audio = QPushButton("Audio only (.wav)")
        rec_row.addWidget(self.scrcpy_rec_path, 3)
        rec_row.addWidget(btn_rec_browse)
        lay.addLayout(rec_row)
        rec_btn_row = QHBoxLayout()
        rec_btn_row.addWidget(btn_rec_start)
        rec_btn_row.addWidget(btn_rec_nodisp)
        rec_btn_row.addWidget(btn_rec_audio)
        lay.addLayout(rec_btn_row)

        btn_rec_start.clicked.connect(self._scrcpy_record_mirror)
        btn_rec_nodisp.clicked.connect(self._scrcpy_record_only)
        btn_rec_audio.clicked.connect(self._scrcpy_audio_record)

        lay.addSpacing(8)
        lay.addWidget(QLabel("Custom flags (appended to any launch):"))
        flags_row = QHBoxLayout()
        self.scrcpy_extra_flags = QLineEdit()
        self.scrcpy_extra_flags.setPlaceholderText(
            "e.g. --serial emulator-5554 --max-fps=30 --crop 1080:1920:0:0")
        btn_launch_custom = QPushButton("Launch with flags")
        btn_launch_custom.clicked.connect(self._scrcpy_launch_custom)
        self.scrcpy_extra_flags.returnPressed.connect(self._scrcpy_launch_custom)
        flags_row.addWidget(self.scrcpy_extra_flags, 4)
        flags_row.addWidget(btn_launch_custom)
        lay.addLayout(flags_row)

        lay.addStretch()
        return w

    def _scrcpy_exe(self):
        return self.scrcpy_path_input.text().strip() or "scrcpy"

    def _browse_scrcpy(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select scrcpy executable", "",
            "Executables (*.exe);;All Files (*)")
        if path:
            self.scrcpy_path_input.setText(path)

    def _browse_scrcpy_rec(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save recording as", "capture.mp4",
            "MP4 (*.mp4);;MKV (*.mkv);;WAV (*.wav);;AAC (*.aac);;Opus (*.opus)")
        if path:
            self.scrcpy_rec_path.setText(path)

    def _extra_flags(self):
        raw = self.scrcpy_extra_flags.text().strip()
        return raw.split() if raw else []

    def _launch_scrcpy(self, args):
        exe = self._scrcpy_exe()
        cmd = [exe] + args + self._extra_flags()
        self.log("$ " + " ".join(cmd), "cmd")
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            subprocess.Popen(cmd, creationflags=flags)
        except Exception as e:
            self.log(str(e), "error")
            QMessageBox.critical(self, "scrcpy error", str(e))

    def _scrcpy_record_mirror(self):
        rec = self.scrcpy_rec_path.text().strip()
        if not rec:
            self.log("Set a recording output path first.", "info")
            return
        self._launch_scrcpy([f"--record={rec}"])

    def _scrcpy_record_only(self):
        rec = self.scrcpy_rec_path.text().strip()
        if not rec:
            self.log("Set a recording output path first.", "info")
            return
        self._launch_scrcpy([f"--record={rec}", "--no-playback"])

    def _scrcpy_audio_record(self):
        rec = self.scrcpy_rec_path.text().strip()
        if not rec:
            self.log("Set a recording output path first.", "info")
            return
        self._launch_scrcpy(["--no-video", "--audio-codec=raw",
                              f"--record={rec if rec.endswith('.wav') else rec + '.wav'}"])

    def _scrcpy_launch_custom(self):
        self._launch_scrcpy([])


DARK_STYLE = """
QWidget {
    background-color: #2b2b2b;
    color: #ffffff;
    font-size: 13px;
}
QLineEdit, QTextEdit, QListWidget, QSpinBox, QComboBox, QTableWidget {
    background-color: #3c3c3c;
    color: #ffffff;
    border: 1px solid #555;
    padding: 2px;
}
QPushButton {
    background-color: #444;
    color: #fff;
    border-radius: 4px;
    padding: 5px 10px;
    min-width: 64px;
}
QPushButton:hover { background-color: #556; }
QPushButton:disabled { background-color: #333; color: #777; }
QTabWidget::pane { border: 1px solid #555; }
QTabBar::tab { background: #3c3c3c; color: #fff; padding: 6px 14px; }
QTabBar::tab:selected { background: #555; }
QProgressBar { border: 1px solid #555; border-radius: 3px; text-align: center; }
QProgressBar::chunk { background-color: #4fc3f7; }
QCheckBox { spacing: 5px; }
QHeaderView::section { background-color: #3c3c3c; color: #fff; padding: 4px; border: 1px solid #555; }
QTableWidget { gridline-color: #444; }
QStatusBar { background-color: #1e1e1e; color: #aaa; }
QLabel { color: #ccc; }
"""


def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SageADB.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)
    app.setWindowIcon(make_app_icon())
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
