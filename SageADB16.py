import os
import sys
import shlex
import shutil
import subprocess
import zipfile
import tempfile
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTextEdit, QTabWidget, QListWidget,
    QListWidgetItem, QSpinBox, QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt, QObject, pyqtSignal, QThread


class LogcatWorker(QObject):
    newLine = pyqtSignal(str)

    def __init__(self, adb_path):
        super().__init__()
        self.adb_path = adb_path
        self._is_running = False
        self.process = None

    def run(self):
        self._is_running = True
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self.process = subprocess.Popen(
                [self.adb_path, "logcat"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                creationflags=creationflags
            )
            for line in self.process.stdout:
                if not self._is_running:
                    break
                if line.strip():
                    self.newLine.emit(line.rstrip())
        except Exception as e:
            self.newLine.emit(f"CRITICAL ERROR starting logcat: {e}")
        finally:
            if self.process:
                try:
                    self.process.stdout.close()
                    self.process.terminate()
                    self.process.wait()
                except Exception:
                    pass
            self.newLine.emit("Logcat stopped.")

    def stop(self):
        self._is_running = False
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.adb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adb.exe")
        if not os.path.exists(self.adb_path):
            self.adb_path = "adb"  # fallback

        self.logcat_thread = None
        self.logcat_worker = None
        self.push_selected_files = []

        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("SageADB")
        self.resize(900, 650)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_connect_tab(), "Connect")
        self.tabs.addTab(self._build_install_tab(), "Install")
        self.tabs.addTab(self._build_apps_tab(), "Apps")
        self.tabs.addTab(self._build_display_tab(), "Display")
        self.tabs.addTab(self._build_reboot_tab(), "Reboot")
        self.tabs.addTab(self._build_logcat_tab(), "Logcat")
        self.tabs.addTab(self._build_push_tab(), "Push Files")

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(120)

        layout = QVBoxLayout()
        layout.addWidget(self.tabs)
        layout.addWidget(QLabel("Logs:"))
        layout.addWidget(self.log_output)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    # ---------------- Tabs ----------------
    def _build_connect_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.usb_button = QPushButton("Connect USB")
        self.wifi_ip_input = QLineEdit()
        self.wifi_ip_input.setPlaceholderText("Enter device IP:port")
        self.wifi_button = QPushButton("Connect WiFi")

        self.custom_cmd_input = QLineEdit()
        self.custom_cmd_input.setPlaceholderText("Enter custom adb command (without 'adb')")
        self.custom_cmd_btn = QPushButton("Run Command")

        layout.addWidget(self.usb_button)
        layout.addWidget(self.wifi_ip_input)
        layout.addWidget(self.wifi_button)
        layout.addWidget(self.custom_cmd_input)
        layout.addWidget(self.custom_cmd_btn)

        self.usb_button.clicked.connect(self.adb_connect_usb)
        self.wifi_button.clicked.connect(self.adb_connect_wifi)
        self.custom_cmd_btn.clicked.connect(self.run_custom_command)

        return widget

    def _build_install_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.install_apk_input = QLineEdit()
        self.install_apk_input.setPlaceholderText("Enter path to APK/APKM/XAPK/APKS")
        self.install_browse_btn = QPushButton("Browse")
        self.install_btn = QPushButton("Install Package")

        row = QHBoxLayout()
        row.addWidget(self.install_apk_input)
        row.addWidget(self.install_browse_btn)

        layout.addLayout(row)
        layout.addWidget(self.install_btn)

        self.install_browse_btn.clicked.connect(self.browse_install_apk)
        self.install_btn.clicked.connect(self.install_app)
        return widget

    def _build_apps_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.apps_list = QListWidget()
        self.refresh_btn = QPushButton("Refresh Apps")
        self.enable_btn = QPushButton("Enable Selected")
        self.disable_btn = QPushButton("Disable Selected")

        layout.addWidget(self.apps_list)
        layout.addWidget(self.refresh_btn)
        layout.addWidget(self.enable_btn)
        layout.addWidget(self.disable_btn)

        self.refresh_btn.clicked.connect(self.refresh_app_list)
        self.enable_btn.clicked.connect(self.enable_app)
        self.disable_btn.clicked.connect(self.disable_app)

        return widget

    def _build_display_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Set DPI:"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(100, 800)
        self.set_dpi_btn = QPushButton("Apply DPI")

        layout.addWidget(self.dpi_spin)
        layout.addWidget(self.set_dpi_btn)

        self.set_dpi_btn.clicked.connect(self.set_dpi)
        return widget

    def _build_reboot_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.reboot_sys_btn = QPushButton("Reboot System")
        self.reboot_rec_btn = QPushButton("Reboot Recovery")
        self.reboot_boot_btn = QPushButton("Reboot Bootloader")

        layout.addWidget(self.reboot_sys_btn)
        layout.addWidget(self.reboot_rec_btn)
        layout.addWidget(self.reboot_boot_btn)

        self.reboot_sys_btn.clicked.connect(lambda: self.reboot_device(""))
        self.reboot_rec_btn.clicked.connect(lambda: self.reboot_device("recovery"))
        self.reboot_boot_btn.clicked.connect(lambda: self.reboot_device("bootloader"))
        return widget

    def _build_logcat_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.start_logcat_btn = QPushButton("Start Logcat")
        self.stop_logcat_btn = QPushButton("Stop Logcat")
        self.stop_logcat_btn.setEnabled(False)
        self.logcat_output = QTextEdit()
        self.logcat_output.setReadOnly(True)

        layout.addWidget(self.start_logcat_btn)
        layout.addWidget(self.stop_logcat_btn)
        layout.addWidget(self.logcat_output)

        self.start_logcat_btn.clicked.connect(self.start_logcat)
        self.stop_logcat_btn.clicked.connect(self.stop_logcat)

        return widget

    def _build_push_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("Files to push to /sdcard/Download/ on device:"))

        self.push_file_input = QLineEdit()
        self.push_file_input.setPlaceholderText("No file(s) selected")
        self.push_file_input.setReadOnly(True)
        self.push_browse_btn = QPushButton("Browse")

        row = QHBoxLayout()
        row.addWidget(self.push_file_input)
        row.addWidget(self.push_browse_btn)

        self.push_btn = QPushButton("Push to Download")

        layout.addLayout(row)
        layout.addWidget(self.push_btn)
        layout.addStretch()

        self.push_browse_btn.clicked.connect(self.browse_push_files)
        self.push_btn.clicked.connect(self.push_files)

        return widget

    # ---------------- Actions ----------------
    def adb_connect_usb(self):
        self.run_adb_command([self.adb_path, "devices"])

    def adb_connect_wifi(self):
        ip = self.wifi_ip_input.text().strip()
        if ip:
            self.run_adb_command([self.adb_path, "connect", ip])

    def run_custom_command(self):
        cmd_text = self.custom_cmd_input.text().strip()
        if not cmd_text:
            self.log_output.append("No command entered.")
            return
        try:
            args = [self.adb_path] + shlex.split(cmd_text)
        except ValueError as e:
            self.log_output.append(f"Could not parse command: {e}")
            return
        self.run_adb_command(args)

    def get_device_abi(self):
        try:
            abi_output = subprocess.run([self.adb_path, "shell", "getprop", "ro.product.cpu.abi"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            abi = abi_output.stdout.strip()
            if abi:
                self.log_output.append(f"Detected device ABI: {abi}")
            return abi
        except Exception as e:
            self.log_output.append(f"Failed to get device ABI: {e}")
            return None

    def browse_install_apk(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Package to Install", "",
            "Android Packages (*.apk *.apkm *.xapk *.apks);;All Files (*)"
        )
        if path:
            self.install_apk_input.setText(path)

    def install_app(self):
        path = self.install_apk_input.text().strip()
        if not path:
            self.log_output.append("No APK path specified.")
            return

        ext = os.path.splitext(path)[1].lower()

        if ext == ".apk":
            self.run_adb_command([self.adb_path, "install", path])
            return

        if ext in (".apkm", ".xapk", ".apks"):
            temp_dir = tempfile.mkdtemp(prefix="sageadb_")
            try:
                with zipfile.ZipFile(path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)

                apk_files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.endswith('.apk')]

                if not apk_files:
                    self.log_output.append(f"No .apk files found inside {os.path.basename(path)}.")
                    return

                device_abi = self.get_device_abi()
                if device_abi:
                    filtered_apks = [f for f in apk_files if device_abi in os.path.basename(f) or "base.apk" in os.path.basename(f)]
                    if not filtered_apks:
                        self.log_output.append("No matching ABI found. Installing all splits.")
                        filtered_apks = apk_files
                else:
                    filtered_apks = apk_files

                self.run_adb_command([self.adb_path, "install-multiple"] + filtered_apks)
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
            return

        self.run_adb_command([self.adb_path, "install", path])

    def refresh_app_list(self):
        self.apps_list.clear()
        all_apps = self.run_adb_command([self.adb_path, "shell", "pm", "list", "packages"])
        disabled_apps = self.run_adb_command([self.adb_path, "shell", "pm", "list", "packages", "-d"])

        disabled_set = set()
        if disabled_apps:
            disabled_set = {line.replace("package:", "").strip() for line in disabled_apps.splitlines()}

        if all_apps:
            for line in all_apps.splitlines():
                pkg = line.replace("package:", "").strip()
                item = QListWidgetItem(pkg)
                if pkg in disabled_set:
                    item.setForeground(Qt.red)
                self.apps_list.addItem(item)

    def enable_app(self):
        item = self.apps_list.currentItem()
        if item:
            pkg = item.text()
            self.run_adb_command([self.adb_path, "shell", "pm", "enable", pkg])
            self.refresh_app_list()

    def disable_app(self):
        item = self.apps_list.currentItem()
        if item:
            pkg = item.text()
            self.run_adb_command([self.adb_path, "shell", "pm", "disable-user", pkg])
            self.refresh_app_list()

    def set_dpi(self):
        dpi = str(self.dpi_spin.value())
        self.run_adb_command([self.adb_path, "shell", "wm", "density", dpi, "--reset"])

    def reboot_device(self, mode):
        cmd = [self.adb_path, "reboot"]
        if mode:
            cmd.append(mode)
        self.run_adb_command(cmd)

    def start_logcat(self):
        if self.logcat_thread and self.logcat_thread.isRunning():
            self.log_output.append("Logcat is already running.")
            return

        self.logcat_worker = LogcatWorker(self.adb_path)
        self.logcat_thread = QThread()
        self.logcat_worker.moveToThread(self.logcat_thread)
        self.logcat_thread.started.connect(self.logcat_worker.run)
        self.logcat_worker.newLine.connect(self.logcat_output.append)

        self.logcat_thread.start()
        self.start_logcat_btn.setEnabled(False)
        self.stop_logcat_btn.setEnabled(True)

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

    # ---------------- Push Files ----------------
    def browse_push_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select File(s) to Push")
        if paths:
            self.push_selected_files = paths
            self.push_file_input.setText("; ".join(paths))

    def push_files(self):
        if not self.push_selected_files:
            self.log_output.append("No file(s) selected to push.")
            return

        for local_path in self.push_selected_files:
            if not os.path.exists(local_path):
                self.log_output.append(f"Skipping missing file: {local_path}")
                continue
            self.run_adb_command([self.adb_path, "push", local_path, "/sdcard/Download/"])

    def run_adb_command(self, args):
        try:
            result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output = result.stdout.strip() + "\n" + result.stderr.strip()
            self.log_output.append("$ " + " ".join(args))
            if result.returncode != 0:
                self.log_output.append("[FAILED, exit code %d]" % result.returncode)
            self.log_output.append(output.strip())
            return result.stdout
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return None


# ---------------- Main ----------------
def main():
    app = QApplication(sys.argv)
    win = MainWindow()

    dark_stylesheet = """
    QWidget { background-color: #2b2b2b; color: #ffffff; }
    QLineEdit, QTextEdit, QListWidget, QSpinBox {
        background-color: #3c3c3c; color: #ffffff; border: 1px solid #555;
    }
    QPushButton { background-color: #444; color: #fff; border-radius: 4px; padding: 4px; }
    QPushButton:hover { background-color: #555; }
    QTabWidget::pane { border: 1px solid #555; }
    QTabBar::tab { background: #3c3c3c; color: #fff; padding: 6px; }
    QTabBar::tab:selected { background: #555; }
    """
    app.setStyleSheet(dark_stylesheet)

    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
