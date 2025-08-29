import os
import sys
import subprocess
import zipfile
import tempfile
import shutil
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTextEdit, QTabWidget, QListWidget,
    QListWidgetItem, QSpinBox, QMessageBox, QFileDialog, QFrame
)
from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal

# --- Worker for running Logcat in the background ---
class LogcatWorker(QObject):
    """
    Runs `adb logcat` in a separate thread to avoid freezing the GUI.
    Emits a signal for each new log line received.
    """
    newLine = pyqtSignal(str)

    def __init__(self, adb_path):
        super().__init__()
        self.adb_path = adb_path
        self._is_running = False
        self.process = None

    def run(self):
        """
        Start `adb logcat` and emit each line via `newLine`.
        """
        self._is_running = True
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
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
                if line:
                    self.newLine.emit(line.rstrip())
        except FileNotFoundError:
            self.newLine.emit("CRITICAL ERROR: adb executable not found. Make sure it's in the same folder as the script.")
        except Exception as e:
            self.newLine.emit(f"CRITICAL ERROR starting logcat: {e}")
        finally:
            try:
                if self.process and self.process.poll() is None:
                    try:
                        self.process.terminate()
                    except Exception:
                        pass
                    try:
                        self.process.wait(timeout=2)
                    except Exception:
                        try:
                            self.process.kill()
                        except Exception:
                            pass
            except Exception:
                pass
            self.newLine.emit("Logcat stopped.")

    def stop(self):
        """Signal the worker to stop; the run loop will terminate soon after."""
        self._is_running = False
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass

# --- Main Application Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Define paths for adb, scrcpy, and debug log file
        base_path = os.path.dirname(os.path.abspath(__file__))
        self.base_path = base_path  # keep a reference for bundletool and extra assets
        self.adb_path = os.path.join(base_path, "adb.exe")
        self.scrcpy_path = os.path.join(base_path, "scrcpy.exe")
        self.log_file_path = os.path.join(base_path, "debug.txt")

        # Clear old log file on start for a clean session
        if os.path.exists(self.log_file_path):
            os.remove(self.log_file_path)

        self.logcat_thread = None
        self.logcat_worker = None

        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("SageADB")
        self.resize(1000, 600)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_connect_tab(), "Connect")
        self.tabs.addTab(self._build_install_tab(), "Install")
        self.tabs.addTab(self._build_apps_tab(), "Apps")
        self.tabs.addTab(self._build_display_tab(), "Display")
        self.tabs.addTab(self._build_reboot_tab(), "Reboot")
        self.tabs.addTab(self._build_logcat_tab(), "Logcat")
        self.tabs.addTab(self._build_scrcpy_tab(), "SCRCPY")

        # Main logs section
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(150)

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

        self.usb_button = QPushButton("Connect USB (List Devices)")
        self.wifi_ip_input = QLineEdit()
        self.wifi_ip_input.setPlaceholderText("Enter device IP:port")
        self.wifi_button = QPushButton("Connect WiFi")

        # Custom adb command
        self.custom_cmd_input = QLineEdit()
        self.custom_cmd_input.setPlaceholderText("Enter custom adb command (without 'adb')")
        self.custom_cmd_btn = QPushButton("Run Command")

        layout.addWidget(self.usb_button)
        layout.addWidget(self.wifi_ip_input)
        layout.addWidget(self.wifi_button)
        layout.addStretch()
        layout.addWidget(QLabel("Custom Command:"))
        layout.addWidget(self.custom_cmd_input)
        layout.addWidget(self.custom_cmd_btn)

        self.usb_button.clicked.connect(self.adb_connect_usb)
        self.wifi_button.clicked.connect(self.adb_connect_wifi)
        self.custom_cmd_btn.clicked.connect(self.run_custom_command)

        return widget

    def _build_install_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("<b>Install APK Package:</b>"))
        apk_h_layout = QHBoxLayout()
        self.install_apk_input = QLineEdit()
        self.install_apk_input.setPlaceholderText("Enter path to APK/APKM/XAPK/APKS")
        self.browse_apk_btn = QPushButton("Browse...")
        apk_h_layout.addWidget(self.install_apk_input)
        apk_h_layout.addWidget(self.browse_apk_btn)
        self.install_btn = QPushButton("Install Package")

        layout.addLayout(apk_h_layout)
        layout.addWidget(self.install_btn)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine); separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        layout.addWidget(QLabel("<b>Push Folder to Android/obb:</b>"))
        obb_h_layout = QHBoxLayout()
        self.obb_folder_input = QLineEdit()
        self.obb_folder_input.setPlaceholderText("Select source folder to push")
        self.browse_obb_btn = QPushButton("Browse...")
        obb_h_layout.addWidget(self.obb_folder_input)
        obb_h_layout.addWidget(self.browse_obb_btn)
        self.push_obb_btn = QPushButton("Push Folder to OBB")

        layout.addLayout(obb_h_layout)
        layout.addWidget(self.push_obb_btn)
        layout.addStretch()

        self.browse_apk_btn.clicked.connect(self.open_file_dialog)
        self.install_btn.clicked.connect(self.install_app)
        self.browse_obb_btn.clicked.connect(self.open_folder_dialog)
        self.push_obb_btn.clicked.connect(self.push_obb_folder)

        return widget

    def _build_apps_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.refresh_btn = QPushButton("Refresh Apps")
        self.app_search_input = QLineEdit()
        self.app_search_input.setPlaceholderText("Search apps...")
        self.app_search_input.textChanged.connect(self.filter_app_list)
        self.apps_list = QListWidget()

        h_layout = QHBoxLayout()
        self.enable_btn = QPushButton("Enable Selected")
        self.disable_btn = QPushButton("Disable Selected")
        h_layout.addWidget(self.enable_btn)
        h_layout.addWidget(self.disable_btn)

        layout.addWidget(self.refresh_btn)
        layout.addWidget(self.app_search_input)
        layout.addWidget(self.apps_list)
        layout.addLayout(h_layout)

        self.refresh_btn.clicked.connect(self.refresh_app_list)
        self.enable_btn.clicked.connect(self.enable_app)
        self.disable_btn.clicked.connect(self.disable_app)

        return widget

    def _build_display_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("Set Device DPI:"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(100, 800)
        self.set_dpi_btn = QPushButton("Apply DPI")

        layout.addWidget(self.dpi_spin)
        layout.addWidget(self.set_dpi_btn)
        layout.addStretch()

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
        layout.addStretch()

        self.reboot_sys_btn.clicked.connect(lambda: self.reboot_device(""))
        self.reboot_rec_btn.clicked.connect(lambda: self.reboot_device("recovery"))
        self.reboot_boot_btn.clicked.connect(lambda: self.reboot_device("bootloader"))

        return widget

    def _build_logcat_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.logcat_output = QTextEdit()
        self.logcat_output.setReadOnly(True)

        h_layout = QHBoxLayout()
        self.start_logcat_btn = QPushButton("Start Logcat")
        self.stop_logcat_btn = QPushButton("Stop Logcat")
        h_layout.addWidget(self.start_logcat_btn)
        h_layout.addWidget(self.stop_logcat_btn)

        layout.addLayout(h_layout)
        layout.addWidget(self.logcat_output)

        self.start_logcat_btn.clicked.connect(self.start_logcat)
        self.stop_logcat_btn.clicked.connect(self.stop_logcat)
        self.stop_logcat_btn.setEnabled(False)

        return widget

    def _build_scrcpy_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("<b>Shared Settings:</b>"))
        layout.addWidget(QLabel("Resolution (e.g., 1280x720):"))
        self.scrcpy_res_input = QLineEdit()
        self.scrcpy_res_input.setPlaceholderText("Leave empty for default")
        layout.addWidget(QLabel("Max FPS:"))
        self.scrcpy_fps_spin = QSpinBox()
        self.scrcpy_fps_spin.setRange(0, 120)
        self.scrcpy_fps_spin.setToolTip("Set to 0 for default")

        layout.addWidget(self.scrcpy_res_input)
        layout.addWidget(self.scrcpy_fps_spin)

        separator1 = QFrame()
        separator1.setFrameShape(QFrame.HLine); separator1.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator1)

        layout.addWidget(QLabel("<b>Mirror Primary Display:</b>"))
        self.mirror_btn = QPushButton("Mirror Device")
        self.mirror_btn.setToolTip("Mirrors the device's main screen using the settings above.")
        layout.addWidget(self.mirror_btn)

        separator2 = QFrame()
        separator2.setFrameShape(QFrame.HLine); separator2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator2)

        layout.addWidget(QLabel("<b>Create Secondary Display:</b>"))
        layout.addWidget(QLabel("New Display DPI:"))
        self.scrcpy_dpi_spin = QSpinBox()
        self.scrcpy_dpi_spin.setRange(0, 800)
        self.scrcpy_dpi_spin.setToolTip("Set to 0 for default")
        layout.addWidget(self.scrcpy_dpi_spin)

        self.new_display_btn = QPushButton("New Display")
        self.new_display_btn.setToolTip("Uses --new-display with the Resolution/DPI/FPS settings.")
        layout.addWidget(self.new_display_btn)
        layout.addStretch()

        self.mirror_btn.clicked.connect(self.launch_scrcpy_mirror)
        self.new_display_btn.clicked.connect(self.launch_scrcpy_new_display)
        return widget

    # ------------- Actions -------------
    def _log(self, command, output):
        """Helper to add timestamped entries to the main GUI log and debug.txt."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_log_entry = ""
        if command:
            cmd_entry = f"[{timestamp}] $ {command}"
            self.log_output.append(cmd_entry)
            full_log_entry += cmd_entry + "\n"
        if output:
            cleaned_output = output.strip()
            if cleaned_output:
                self.log_output.append(f"[{timestamp}] > {cleaned_output}")
                for line in cleaned_output.splitlines():
                    full_log_entry += f"[{timestamp}] > {line}\n"
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())
        try:
            with open(self.log_file_path, 'a', encoding='utf-8') as f:
                f.write(full_log_entry)
        except Exception as e:
            print(f"Failed to write to debug.txt: {e}")

    def adb_connect_usb(self):
        self.run_adb_command([self.adb_path, "devices"])

    def adb_connect_wifi(self):
        ip = self.wifi_ip_input.text().strip()
        if ip:
            self.run_adb_command([self.adb_path, "connect", ip])
        else:
            self._log("", "IP address cannot be empty.")

    def run_custom_command(self):
        cmd_text = self.custom_cmd_input.text().strip()
        if not cmd_text:
            self._log("", "No command entered.")
            return
        import shlex
        args = [self.adb_path] + shlex.split(cmd_text)
        self.run_adb_command(args)

    def open_file_dialog(self):
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getOpenFileName(
            self, "Select APK File", "", "Android Packages (*.apk *.apkm *.xapk *.apks)", options=options
        )
        if fileName:
            self.install_apk_input.setText(fileName)

    def open_folder_dialog(self):
        folderName = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folderName:
            self.obb_folder_input.setText(folderName)

    # ------------------ INSTALLER (Improvement #6 + OBB auto-push) ------------------
    def _bundletool_path(self):
        """Return the expected bundletool.jar path in the script folder."""
        return os.path.join(self.base_path, "bundletool.jar")

    def _extract_zip_to_temp(self, pkg_path):
        """Extract a ZIP-like package (.apkm/.xapk) to a temp folder and return its path."""
        temp_dir = tempfile.mkdtemp(prefix="sageadb_")
        with zipfile.ZipFile(pkg_path, 'r') as zf:
            zf.extractall(temp_dir)
        return temp_dir

    def _collect_apk_files(self, root_dir):
        """Find all .apk files under root_dir. Return a list with base apk first if present."""
        apk_files = []
        for r, _, files in os.walk(root_dir):
            for fname in files:
                if fname.lower().endswith(".apk"):
                    apk_files.append(os.path.join(r, fname))
        def sort_key(p):
            name = os.path.basename(p).lower()
            return (0 if "base" in name or name == "base.apk" else 1, name)
        apk_files.sort(key=sort_key)
        return apk_files

    def _find_obb_package_dirs(self, root_dir):
        """
        Detect OBB package directories inside an extracted archive.
        Returns a dict: { package_name: local_dir_path }
        Looks for paths like .../Android/obb/<package>/ with at least one *.obb inside.
        Case-insensitive match on 'Android/obb'.
        """
        obb_pkg_dirs = {}
        # Collect any directory that contains .obb files
        for r, dirs, files in os.walk(root_dir):
            # Quick check for any .obb files in this directory
            obb_files_here = [f for f in files if f.lower().endswith(".obb")]
            if not obb_files_here:
                continue

            # Normalize path parts for detection
            parts = []
            rp = r
            while True:
                rp, tail = os.path.split(rp)
                if tail:
                    parts.append(tail)
                else:
                    if rp:
                        parts.append(rp)
                    break
            parts = [p.lower() for p in parts][::-1]  # from root to leaf

            # Try to find ".../android/obb/<package>"
            try:
                if "android" in parts:
                    idx_android = parts.index("android")
                    # Ensure 'obb' exists right after (or somewhere after) android
                    if "obb" in parts[idx_android+1:]:
                        idx_obb = parts.index("obb", idx_android+1)
                        # Package directory should be next segment if present
                        if len(parts) > idx_obb + 1:
                            package_name = parts[idx_obb + 1]  # lowercased
                            # Rebuild the actual case-correct path for that package dir
                            # Find the actual path level for the package dir
                            # r may be ".../<package>" or deeper; we want the directory that is exactly <package>
                            path_segments = r.split(os.sep)
                            # locate the 'obb' segment from the end and pick the next as package dir
                            for i, seg in enumerate(path_segments):
                                if seg.lower() == "obb" and i + 1 < len(path_segments):
                                    pkg_dir_real = os.path.join(*path_segments[:i+2])
                                    # ensure it actually contains .obb files
                                    has_obb = any(f.lower().endswith(".obb") for f in os.listdir(pkg_dir_real))
                                    if has_obb:
                                        obb_pkg_dirs[os.path.basename(pkg_dir_real)] = pkg_dir_real
                                    break
            except Exception:
                # Best-effort; ignore path parsing errors
                pass
        return obb_pkg_dirs

    def _push_obb_dirs(self, obb_pkg_dirs):
        """
        Push each local OBB package directory to /sdcard/Android/obb/<package>.
        """
        if not obb_pkg_dirs:
            return

        for pkg, local_dir in obb_pkg_dirs.items():
            remote_pkg_dir = f"/sdcard/Android/obb/{pkg}"
            # Ensure remote dir exists
            self.run_adb_command([self.adb_path, "shell", "mkdir", "-p", remote_pkg_dir])
            # Push directory (recursive)
            self._log("", f"Pushing OBB assets for {pkg}...")
            self.run_adb_command([self.adb_path, "push", local_dir, remote_pkg_dir])

    def install_app(self):
        path = self.install_apk_input.text().strip()
        if not path:
            self._log("", "No APK path specified.")
            return

        ext = os.path.splitext(path)[1].lower()

        # Case 1: Plain APK -> adb install
        if ext == ".apk":
            self.run_adb_command([self.adb_path, "install", path])
            return
        # Case 2: .apks -> bundletool install-apks
        if ext == ".apks":
            bt = self._bundletool_path()
            if not os.path.exists(bt):
                QMessageBox.critical(self, "Error", f"bundletool.jar not found in:\n{self.base_path}")
                self._log("", "bundletool.jar is required to install .apks archives.")
                return
            cmd = [
                "java", "-jar", bt,
                "install-apks",
                f"--apks={path}",
                f"--adb={self.adb_path}",
            ]
            try:
                result = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                output = result.stdout.strip() + "\n" + result.stderr.strip()
                self._log(" ".join(cmd), output)
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
                self._log(" ".join(cmd), f"Error running bundletool: {e}")
            return

        # Case 3: .apkm / .xapk -> extract and install-multiple + OBB push
        if ext in (".apkm", ".xapk"):
            temp_dir = None
            try:
                temp_dir = self._extract_zip_to_temp(path)

                # Install split APKs
                apk_files = self._collect_apk_files(temp_dir)
                if not apk_files:
                    self._log("", f"No .apk files found inside {ext} package.")
                else:
                    cmd = [self.adb_path, "install-multiple"] + apk_files
                    result = subprocess.run(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    output = result.stdout.strip() + "\n" + result.stderr.strip()
                    self._log(" ".join(cmd), output)

                # Detect and push OBBs (best-effort)
                obb_pkg_dirs = self._find_obb_package_dirs(temp_dir)
                if obb_pkg_dirs:
                    pkgs = ", ".join(sorted(obb_pkg_dirs.keys()))
                    self._log("", f"Detected OBB packages: {pkgs}")
                    self._push_obb_dirs(obb_pkg_dirs)
                else:
                    self._log("", "No OBB assets detected in this package.")

            except zipfile.BadZipFile:
                QMessageBox.critical(self, "Error", f"Invalid {ext} file (not a valid ZIP archive).")
                self._log("", f"Failed to read {path}: invalid archive.")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
                self._log("", f"Error installing split package: {e}")
            finally:
                if temp_dir:
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                    except Exception:
                        pass
            return

        # Unknown format
        self._log("", f"Unsupported file type: {ext}. Supported: .apk, .apkm, .xapk, .apks")

    # ---------------------------------------------------------------

    def push_obb_folder(self):
        source_path = self.obb_folder_input.text().strip()
        if not source_path:
            self._log("", "No source folder specified.")
            return
        if not os.path.isdir(source_path):
            self._log("", f"Error: The specified path is not a valid folder: {source_path}")
            return
        remote_path = "/sdcard/Android/obb/"
        self.run_adb_command([self.adb_path, "push", source_path, remote_path])

    def refresh_app_list(self):
        self.apps_list.clear()
        self.apps_list.addItem("Loading...")
        QApplication.processEvents()

        all_apps = self.run_adb_command([self.adb_path, "shell", "pm", "list", "packages"], return_output=True)
        disabled_apps = self.run_adb_command([self.adb_path, "shell", "pm", "list", "packages", "-d"], return_output=True)

        self.apps_list.clear()
        disabled_set = set()
        if disabled_apps:
            disabled_set = {line.replace("package:", "").strip() for line in disabled_apps.splitlines()}
        if all_apps:
            all_package_names = [line.replace("package:", "").strip() for line in all_apps.splitlines()]
            for pkg in sorted(all_package_names):
                item = QListWidgetItem(pkg)
                if pkg in disabled_set:
                    item.setForeground(Qt.red)
                self.apps_list.addItem(item)
        else:
            self.apps_list.addItem("Could not retrieve apps.")
        self.filter_app_list()

    def filter_app_list(self):
        search_text = self.app_search_input.text().lower()
        for i in range(self.apps_list.count()):
            item = self.apps_list.item(i)
            package_name = item.text().lower()
            item.setHidden(search_text not in package_name)

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
        self.run_adb_command([self.adb_path, "shell", "wm", "density", dpi])
        self._log("", "Note: You may need to reboot your device for DPI changes to apply system-wide.")

    def reboot_device(self, mode):
        cmd = [self.adb_path, "reboot"]
        if mode:
            cmd.append(mode)
        self.run_adb_command(cmd)

    def start_logcat(self):
        self.logcat_output.clear()
        self.logcat_thread = QThread()
        self.logcat_worker = LogcatWorker(self.adb_path)
        self.logcat_worker.moveToThread(self.logcat_thread)
        self.logcat_worker.newLine.connect(self.update_logcat_and_debug_file)
        self.logcat_thread.started.connect(self.logcat_worker.run)
        self.logcat_thread.finished.connect(self.logcat_thread.deleteLater)
        self.logcat_thread.start()
        self.start_logcat_btn.setEnabled(False)
        self.stop_logcat_btn.setEnabled(True)

    def update_logcat_and_debug_file(self, line):
        """Appends to the logcat GUI and writes to the debug file."""
        self.logcat_output.append(line)
        self.logcat_output.verticalScrollBar().setValue(self.logcat_output.verticalScrollBar().maximum())
        try:
            with open(self.log_file_path, 'a', encoding='utf-8') as f:
                timestamp = datetime.now().strftime('%H:%M:%S')
                f.write(f"[{timestamp}] [LOGCAT] {line}\n")
        except Exception as e:
            print(f"Failed to write logcat line to debug.txt: {e}")

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

    def launch_scrcpy_mirror(self):
        if not os.path.exists(self.scrcpy_path):
            QMessageBox.critical(self, "Error", f"scrcpy.exe not found at:\n{self.scrcpy_path}")
            return
        cmd = [self.scrcpy_path]
        resolution = self.scrcpy_res_input.text().strip().lower()
        if 'x' in resolution:
            parts = resolution.split('x')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                max_size = max(int(parts[0]), int(parts[1]))
                cmd.extend(['-m', str(max_size)])
        fps = self.scrcpy_fps_spin.value()
        if fps > 0:
            cmd.extend(['--max-fps', str(fps)])
        self._log(" ".join(cmd), "Starting scrcpy (Mirror Mode)...")
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)

    def launch_scrcpy_new_display(self):
        if not os.path.exists(self.scrcpy_path):
            QMessageBox.critical(self, "Error", f"scrcpy.exe not found at:\n{self.scrcpy_path}")
            return
        cmd = [self.scrcpy_path]
        resolution = self.scrcpy_res_input.text().strip().lower()
        dpi = self.scrcpy_dpi_spin.value()
        if resolution or dpi > 0:
            param_value = ""
            if resolution:
                param_value += resolution
            if dpi > 0:
                param_value += f"/{dpi}"
            cmd.append(f"--new-display={param_value}")
        else:
            cmd.append("--new-display")

        fps = self.scrcpy_fps_spin.value()
        if fps > 0:
            cmd.extend(['--max-fps', str(fps)])
        self._log(" ".join(cmd), "Starting scrcpy (New Display Mode)...")
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)

    # ------------- Core Command Runner -------------
    def run_adb_command(self, args, return_output=False):
        try:
            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            output = result.stdout.strip() + "\n" + result.stderr.strip()
            self._log(" ".join(args), output)
            if return_output:
                return result.stdout
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self._log(f"Error running command: {' '.join(args)}", str(e))
        return None

    def closeEvent(self, event):
        """Ensure background threads are stopped when closing the app."""
        self.stop_logcat()
        event.accept()

# ---------------- Main ----------------
def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    dark_stylesheet = """
    QWidget { background-color: #2b2b2b; color: #f0f0f0; }
    QLabel { font-size: 10pt; }
    QLineEdit, QTextEdit, QListWidget, QSpinBox {
        background-color: #3c3f41; color: #f0f0f0; border: 1px solid #555;
        border-radius: 4px; padding: 4px; font-size: 10pt;
    }
    QPushButton {
        background-color: #555; color: #fff; border-radius: 4px;
        padding: 6px 10px; border: 1px solid #666; font-size: 10pt;
    }
    QPushButton:hover { background-color: #666; }
    QPushButton:pressed { background-color: #777; }
    QPushButton:disabled { background-color: #444; color: #999; }
    QTabWidget::pane { border: 1px solid #555; }
    QTabBar::tab {
        background: #3c3c3c;
        color: #fff;
        padding: 8px 22px;
        font-size: 10pt;
        min-width: 90px;
    }
    QTabBar::tab:selected {
        background: #555;
        border-bottom: 2px solid #007bff;
    }
    QFrame { border: 1px inset #444; }
    """
    app.setStyleSheet(dark_stylesheet)
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
