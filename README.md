# SageADB

A portable PyQt5 desktop GUI for common ADB tasks on Windows: connecting, installing, managing apps, battery and deep-sleep diagnostics, device analysis, logcat and scrcpy launching.

**Current version:** v17

## Requirements

- Windows (Linux/macOS should also work; the `CREATE_NO_WINDOW` flag is only used on Windows)
- Python 3.8+
- PyQt5: `pip install PyQt5`
- `adb.exe` placed in the same folder as the script. If it isn't there, `adb` from your PATH is used.
- `scrcpy.exe` (optional) in the same folder, or on PATH. It can also be set from the Scrcpy tab.
- USB debugging enabled on the device, or wireless debugging for Wi-Fi connections.

## Running

```
pythonw SageADB17.pyw
```

Double-clicking the `.pyw` file also works if `.pyw` is associated with `pythonw`.

### Optional custom icon

The title-bar and taskbar icon is drawn in code. To use your own, put a file named `SageADB.ico` next to the script.

## Tabs

| Tab | What it does |
|---|---|
| Connect | USB device list, Wi-Fi connect/disconnect, free-form custom `adb` command |
| Install | Install `.apk`, `.apkm`, `.xapk` and `.apks` packages. `.apkm` bundles are extracted and filtered to the device ABI |
| Apps | List, search, filter (All/Enabled/Disabled) and sort packages. Load APK sizes. Enable, Disable and Force Stop |
| Display | DPI set/reset and animation scale presets (0x / 0.5x / 1x) |
| Battery | Battery-drain and deep-sleep diagnostics (see below) |
| Reboot | Reboot system, recovery or bootloader |
| Analysis | Preset `dumpsys`/`top`/`df` commands, per-package analysis and a custom shell command box. Output can be saved |
| Logcat | Live logcat with keyword filter, level colouring, auto-scroll and save |
| Scrcpy | Mirror, record and audio presets, plus custom flags |

## Battery tab

Use it to find which apps drain the battery and what stops the device entering deep sleep.

| Button | Source command | Purpose |
|---|---|---|
| Top Battery Users (mAh) | `dumpsys batterystats --charged` | Ranks apps by estimated mAh, with UIDs resolved to package names |
| Active Wake Locks (Live) | `dumpsys power` | Wake locks held right now. This is the best test when the screen is off but the device won't sleep |
| Kernel Wakelocks | `dumpsys batterystats --charged` | Kernel/driver wakelocks since last charge, as a sortable table |
| Partial Wakelocks | `dumpsys batterystats --charged` | App wakelocks that keep the CPU awake, as a sortable table with the owning package |
| Doze / Deep Sleep State | `dumpsys deviceidle` | Current idle state and Doze whitelist |
| Alarm Wakeups | `dumpsys alarm` | "Top Alarms" section |
| Battery Info | `dumpsys battery` | Level, temperature, charging state |
| Reset Battery Stats | `dumpsys batterystats --reset` | Clears counters, with a confirmation prompt |

### Wakelock tables

- **Columns:** Wakelock, Owner (Partial only), Time held, Count, Avg / hold.
- **Sorting:** the default is Time held, highest first. Use the Sort dropdown (Time, Count, Avg per hold, Name) or click any column header. Numeric columns sort by value, not text.
- **Filter:** type in the Filter box to match wakelock name or package.
- **Colour by time held:**
  - Red and bold: 30 min or more
  - Orange: 5 min or more
  - Yellow: 1 min or more
  - Grey: under 1 min
  - Cyan count: 1000 or more acquisitions
- **Summary line:** shows the entry count and total held time.

Tips:
- Unplug the phone and leave it for a while before reading "since charge" data. Right after a charge or reboot there is little to show.
- Kernel wakelock times can overlap, so the total is not real elapsed time.
- If a device formats `batterystats` differently and no table rows appear, the raw wakelock lines are written to the Output box under the table.

## Enabling and disabling apps

- **Disable** runs `pm disable-user --user 0 <package>`.
- **Enable** runs `pm enable --user 0 <package>`.

If Enable fails with `SecurityException: Shell cannot change component state for null to 1`, the package is in the hard `DISABLED` state (check `enabled=2` in `dumpsys package <pkg>`).

Shell can only move a package between the default, enabled and user-disabled states, and only when it is already in one of them. Apps can put themselves into the hard-disabled state, and shell can't undo that. Samsung system apps such as `com.mygalaxy.service` can do this on boot.

Options when it happens:
1. Try `pm uninstall -k --user 0 <pkg>`, then `pm install-existing --user 0 <pkg>`, then `pm enable --user 0 <pkg>`.
2. Use root (for example Magisk) or Shizuku, which are not limited by the shell-UID check.

## Notes

- All ADB commands run on the PC through the bundled or PATH `adb`. Nothing is installed on the device.
- The bottom Command Log shows each command run, with stdout and stderr colour-coded. Use Save Log to export it.
- Long-running tasks (logcat, size loading, analysis, battery dumps) run in background threads, so the UI stays responsive.

## Changelog

### v17
- Added a title-bar and taskbar icon. It is drawn in code, and `SageADB.ico` overrides it if present.
- Replaced "Wake Lock History" with separate **Kernel Wakelocks** and **Partial Wakelocks** buttons.
- Wakelocks are shown in a sortable, filterable, colour-coded table with Time, Count and Avg / hold columns and package-name resolution.
- Battery commands now time out after 60 s, up from 30 s.

### v16
- Added the Battery tab: top battery users, live wake locks, Doze state, alarm wakeups, battery info and stats reset.
- Enable now passes `--user 0`, matching Disable.

### v15
- Baseline: Connect, Install, Apps, Display, Reboot, Analysis, Logcat and Scrcpy tabs.
