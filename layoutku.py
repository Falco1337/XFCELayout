
import os
import json
import sys
import subprocess
import time
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
from Xlib import display, X
from PIL import Image
from Xlib.error import BadDrawable, BadMatch, BadWindow
from Xlib.error import XError

GAP = 8

LAYOUTS = [
    ("2 Windows", [(0, 0, 0.5, 1), (0.5, 0, 0.5, 1)]),
    ("2 Windows", [(0, 0, 0.67, 1), (0.67, 0, 0.33, 1)]),
    ("3 Windows", [(0, 0, 0.33, 1), (0.33, 0, 0.34, 1), (0.67, 0, 0.33, 1)]),
    ("3 Windows", [(0, 0, 0.5, 1), (0.5, 0, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)]),
    ("4 Windows", [(0, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5), (0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)]),
    ("6 Windows", [(x / 3, y / 2, 1 / 3, 0.5) for y in range(2) for x in range(3)])
]


CUSTOM_LAYOUT_FILE = str(Path.home() / ".config/snaplayout/custom-layouts.json")

def load_custom_layouts():
    try:
        with open(CUSTOM_LAYOUT_FILE, "r") as f:
            records = json.load(f)
    except (OSError, ValueError):
        return []

    layouts = []

    if not isinstance(records, list):
        return layouts

    for record in records:
        if not isinstance(record, dict):
            continue

        name = record.get("name")
        slots = record.get("slots")

        if not isinstance(name, str) or not isinstance(slots, list):
            continue

        if not 2 <= len(slots) <= 8:
            continue

        valid = True
        converted = []

        for slot in slots:
            if not isinstance(slot, list) or len(slot) != 4:
                valid = False
                break

            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in slot):
                valid = False
                break

            x, y, w, h = slot

            if not (
                0 <= x < 1 and
                0 <= y < 1 and
                0 < w <= 1 and
                0 < h <= 1 and
                x + w <= 1.00001 and
                y + h <= 1.00001
            ):
                valid = False
                break

            converted.append(tuple(slot))

        if valid:
            layouts.append((name[:40], converted))

    return layouts


def save_custom_layout(name, slots):
    os.makedirs(os.path.dirname(CUSTOM_LAYOUT_FILE), exist_ok=True)

    try:
        with open(CUSTOM_LAYOUT_FILE, "r") as f:
            records = json.load(f)
        if not isinstance(records, list):
            records = []
    except (OSError, ValueError):
        records = []

    records.append({
        "name": name,
        "slots": [list(slot) for slot in slots]
    })

    temp = CUSTOM_LAYOUT_FILE + ".tmp"

    with open(temp, "w") as f:
        json.dump(records, f, indent=2)

    os.replace(temp, CUSTOM_LAYOUT_FILE)


LAYOUTS.extend(load_custom_layouts())

CSS = """
#tile.tile-active {
    background: #3b82f6;
    border: 2px solid #bfdbfe;
}

window {
    background-color: #111827;
}

#main {
    background-color: #111827;
    border: 1px solid #334155;
    border-radius: 14px;
}

#heading {
    color: #f8fafc;
    font-size: 18px;
    font-weight: bold;
}

#subtitle {
    color: #94a3b8;
    font-size: 11px;
}

#layout-button {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 10px;
}

#layout-button.layout-current {
    background: #17345b;
    border: 2px solid #60a5fa;
}

#layout-button:hover {
    background: #334155;
    border-color: #60a5fa;
}

#layout-label {
    color: #cbd5e1;
    font-size: 11px;
}

#tile {
    background: #475569;
    border: 1px solid #64748b;
    border-radius: 3px;
}

#tile:hover {
    background: #3b82f6;
    border-color: #93c5fd;
}

#footer {
    color: #64748b;
    font-size: 10px;
}
"""

def active_layout_path():
    return str(Path.home() / ".config/snaplayout/active-layouts.json")


def read_active_layouts():
    try:
        with open(active_layout_path()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def remember_active_layout(window_id, layout):
    index = next((i for i, (_,slots) in enumerate(LAYOUTS) if slots is layout), None)
    if index is None:
        return
    state = read_active_layouts()
    state[str(int(window_id))] = index
    path = active_layout_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w") as f:
        json.dump(state, f)
    os.replace(temp, path)


class WindowManager:
    def __init__(self):
        self.connection = display.Display()
        self.root = self.connection.screen().root
        self.active_atom = self.connection.intern_atom("_NET_ACTIVE_WINDOW")
        self.workarea_atom = self.connection.intern_atom("_NET_WORKAREA")
        self.desktop_atom = self.connection.intern_atom("_NET_CURRENT_DESKTOP")

    def active_window(self):
        prop = self.root.get_full_property(
            self.active_atom,
            X.AnyPropertyType
        )

        if prop is None or not len(prop.value):
            return None

        return int(prop.value[0])

    def workarea(self):
        desktop = self.root.get_full_property(
            self.desktop_atom,
            X.AnyPropertyType
        )

        area = self.root.get_full_property(
            self.workarea_atom,
            X.AnyPropertyType
        )

        if area is not None and len(area.value) >= 4:
            index = int(desktop.value[0]) if desktop is not None else 0
            offset = index * 4

            if len(area.value) >= offset + 4:
                return tuple(
                    int(v)
                    for v in area.value[offset:offset + 4]
                )

        screen = self.connection.screen()

        return (
            0,
            0,
            screen.width_in_pixels,
            screen.height_in_pixels
        )

    def get_window_geometry(self, window_id):
        """Return outer window geometry including XFCE decorations."""
        try:
            window = self.connection.create_resource_object(
                "window", window_id
            )

            geometry = window.get_geometry()
            origin = self.root.translate_coords(window, 0, 0)

            left = right = top = bottom = 0
            atom = self.connection.intern_atom("_NET_FRAME_EXTENTS")
            ext = window.get_full_property(atom, X.AnyPropertyType)

            if ext is not None and len(ext.value) >= 4:
                left, right, top, bottom = map(int, ext.value[:4])

            return (
                int(origin.x) - left,
                int(origin.y) - top,
                int(geometry.width) + left + right,
                int(geometry.height) + top + bottom
            )

        except (XError, AttributeError, ValueError):
            return None

    def place(self, window_id, rect):
        x, y, w, h = self.workarea()
        rx, ry, rw, rh = rect

        px = x + round(rx * w) + GAP
        py = y + round(ry * h) + GAP
        pw = max(100, round(rw * w) - GAP * 2)
        ph = max(100, round(rh * h) - GAP * 2)

        wid = hex(window_id)

        subprocess.run(
            [
                "wmctrl", "-ir", wid,
                "-b", "remove,maximized_vert,maximized_horz,fullscreen"
            ],
            check=False
        )

        # Read actual window decorations from X11.
        left = right = top = bottom = 0

        try:
            window = self.connection.create_resource_object(
                "window", window_id
            )
            atom = self.connection.intern_atom("_NET_FRAME_EXTENTS")
            ext = window.get_full_property(atom, X.AnyPropertyType)

            if ext is not None and len(ext.value) >= 4:
                left, right, top, bottom = map(int, ext.value[:4])
        except Exception:
            pass

        client_width = max(100, pw - left - right)
        client_height = max(100, ph - top - bottom)

        subprocess.run(
            [
                "wmctrl", "-ir", wid,
                "-e",
                f"0,{px},{py},{client_width},{client_height}"
            ],
            check=False
        )

        return True


    def animate_place(self, window_id, rect):
        """Animate snapping without changing normal place()."""
        x, y, w, h = self.workarea()
        rx, ry, rw, rh = rect

        target_x = x + round(rx * w) + GAP
        target_y = y + round(ry * h) + GAP
        target_w = max(100, round(rw * w) - GAP * 2)
        target_h = max(100, round(rh * h) - GAP * 2)

        wid = hex(window_id)

        subprocess.run(
            [
                "wmctrl", "-ir", wid,
                "-b", "remove,maximized_vert,maximized_horz,fullscreen"
            ],
            check=False
        )

        try:
            result = subprocess.check_output(
                ["xwininfo", "-id", wid],
                text=True,
                stderr=subprocess.DEVNULL
            )

            import re

            def read_value(pattern, fallback):
                match = re.search(pattern, result)
                return int(match.group(1)) if match else fallback

            start_x = read_value(r"Absolute upper-left X:\s*(-?\d+)", target_x)
            start_y = read_value(r"Absolute upper-left Y:\s*(-?\d+)", target_y)
            start_w = read_value(r"Width:\s*(\d+)", target_w)
            start_h = read_value(r"Height:\s*(\d+)", target_h)

        except (OSError, subprocess.CalledProcessError):
            return self.place(window_id, rect)

        started = time.monotonic()

        def frame():
            progress = min(
                1.0,
                (time.monotonic() - started) / (max(100, min(500, float(snap_settings()['animation_speed']))) / 1000)
            )
            eased = 1 - (1 - progress) ** 3

            values = [
                round(a + (b - a) * eased)
                for a, b in zip(
                    (start_x, start_y, start_w, start_h),
                    (target_x, target_y, target_w, target_h)
                )
            ]

            subprocess.run(
                [
                    "wmctrl", "-ir", wid, "-e",
                    "0,{},{},{},{}".format(*values)
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )

            if progress >= 1:
                self.place(window_id, rect)
                return False

            return True

        GLib.timeout_add(16, frame)
        return True


class SmartDivider(Gtk.Window):
    def __init__(self, manager, axis, boundary, begin, end):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.manager = manager
        self.axis = axis
        self.boundary = boundary
        self.begin = begin
        self.end = end
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_app_paintable(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None and screen.is_composited():
            self.set_visual(visual)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("draw", self.draw_handle)
        self.connect("button-press-event", self.press)
        self.update_position()

    def draw_handle(self, widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()

        cr.set_source_rgb(0.23, 0.51, 0.96)

        if self.axis == "x":
            cr.rectangle(0, 0, w, h)
        else:
            cr.rectangle(0, 0, w, h)

        cr.fill()
        return False

    def update_position(self):
        x, y, w, h = self.manager.wm.workarea()

        if self.axis == "x":
            center_x = x + round(self.boundary * w)
            center_y = y + round((self.begin + self.end) * h / 2)
            self.move(center_x - 2, center_y - 24)
            self.resize(4, 48)
        else:
            center_x = x + round((self.begin + self.end) * w / 2)
            center_y = y + round(self.boundary * h)
            self.move(center_x - 24, center_y - 2)
            self.resize(48, 4)

    def press(self, widget, event):
        if event.button == 1:
            self.manager.begin_drag(self)
            return True
        return False




def replace_existing_smart_divider(entries):
    import hashlib
    import tempfile
    import fcntl
    import signal

    ids = sorted(int(wid) for wid, rect in entries)
    signature = ",".join(map(str, ids))
    key = hashlib.sha256(signature.encode()).hexdigest()[:20]

    directory = os.path.join(
        os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()),
        "snaplayout-dividers"
    )
    path = os.path.join(directory, key + ".lock")

    if not os.path.exists(path):
        return True

    try:
        with open(path, "r") as f:
            pid = int(f.read().strip())

        if pid == os.getpid():
            return False

        with open(f"/proc/{pid}/cmdline", "rb") as f:
            command = [
                part.decode(errors="replace")
                for part in f.read().split(b"\0")
                if part
            ]

        if (
            os.path.abspath(__file__) not in command
            or "--resize-divider" not in command
        ):
            return False

        pos = command.index("--resize-divider")
        arguments = command[pos + 1:]

        if len(arguments) % 2:
            return False

        running_ids = sorted(
            int(arguments[i])
            for i in range(0, len(arguments), 2)
        )

        if running_ids != ids:
            return False

        os.kill(pid, signal.SIGTERM)

    except FileNotFoundError:
        pass
    except (OSError, ValueError, ProcessLookupError):
        return False

    deadline = time.monotonic() + 3.0

    while time.monotonic() < deadline:
        with open(path, "a+") as lock:
            try:
                fcntl.flock(
                    lock.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB
                )
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                return True
            except BlockingIOError:
                pass

        time.sleep(0.05)

    return False


def acquire_smart_divider_lock(entries):
    import fcntl
    import hashlib
    import tempfile

    window_ids = sorted(int(wid) for wid, rect in entries)
    signature = ",".join(map(str, window_ids))

    key = hashlib.sha256(signature.encode()).hexdigest()[:20]

    directory = os.path.join(
        os.environ.get(
            "XDG_RUNTIME_DIR",
            tempfile.gettempdir()
        ),
        "snaplayout-dividers"
    )

    os.makedirs(directory, mode=0o700, exist_ok=True)

    path = os.path.join(directory, key + ".lock")
    handle = open(path, "a+")

    try:
        fcntl.flock(
            handle.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB
        )
    except BlockingIOError:
        handle.close()
        return None

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()

    return handle


class SmartResizeManager:
    def __init__(self, entries):
        self.wm = WindowManager()
        self.divider_lock = acquire_smart_divider_lock(entries)

        if self.divider_lock is None:
            self.running = False
            return

        self.entries = [
            {"id": wid, "rect": list(rect)}
            for wid, rect in entries
        ]
        self.handles = []
        self.active = None
        self.last_value = None
        self.running = True
        self.build_handles()
        GLib.timeout_add(25, self.track_drag)
        GLib.timeout_add(80, self.track_manual_resize)
        GLib.timeout_add(100, self.track_hover)
        GLib.timeout_add(700, self.check_windows)

    def build_handles(self):
        eps = 0.002
        groups = {}

        for a in self.entries:
            ax, ay, aw, ah = a["rect"]
            for b in self.entries:
                if a is b:
                    continue

                bx, by, bw, bh = b["rect"]

                if abs(ax + aw - bx) < eps:
                    begin = max(ay, by)
                    end = min(ay + ah, by + bh)
                    if end - begin > eps:
                        key = ("x", round(bx, 5))
                        groups.setdefault(key, []).append((begin, end))

                if abs(ay + ah - by) < eps:
                    begin = max(ax, bx)
                    end = min(ax + aw, bx + bw)
                    if end - begin > eps:
                        key = ("y", round(by, 5))
                        groups.setdefault(key, []).append((begin, end))

        for (axis, boundary), spans in groups.items():
            spans.sort()
            merged = []

            for begin, end in spans:
                if merged and begin <= merged[-1][1] + eps:
                    merged[-1][1] = max(merged[-1][1], end)
                else:
                    merged.append([begin, end])

            for begin, end in merged:
                handle = SmartDivider(
                    self, axis, boundary, begin, end
                )
                self.handles.append(handle)

    def track_manual_resize(self):
        if not self.running:
            return False

        if self.active is not None:
            return True

        pointer = self.wm.root.query_pointer()
        pressed = bool(pointer.mask & X.Button1Mask)

        if not hasattr(self, "manual_snapshot"):
            self.manual_snapshot = {
                entry["id"]: self.wm.get_window_geometry(entry["id"])
                for entry in self.entries
            }
            return True

        if not pressed:
            self.manual_snapshot = {
                entry["id"]: self.wm.get_window_geometry(entry["id"])
                for entry in self.entries
            }
            return True

        wx, wy, ww, wh = self.wm.workarea()

        for entry in self.entries:
            wid = entry["id"]
            previous = self.manual_snapshot.get(wid)
            current = self.wm.get_window_geometry(wid)

            if previous is None or current is None:
                continue

            px, py, pw, ph = previous
            cx, cy, cw, ch = current

            changes = []

            if abs((cx + cw) - (px + pw)) > 3:
                changes.append(("x", cx + cw))

            if abs(cx - px) > 3:
                changes.append(("x", cx))

            if abs((cy + ch) - (py + ph)) > 3:
                changes.append(("y", cy + ch))

            if abs(cy - py) > 3:
                changes.append(("y", cy))

            for axis, position in changes:
                value = (
                    (position - wx) / max(1, ww)
                    if axis == "x"
                    else (position - wy) / max(1, wh)
                )

                candidates = [
                    handle for handle in self.handles
                    if handle.axis == axis
                    and abs(handle.boundary - value) < 0.12
                ]

                if candidates:
                    handle = min(
                        candidates,
                        key=lambda h: abs(h.boundary - value)
                    )
                    self.resize_boundary(handle, value)

            if changes:
                self.manual_snapshot = {
                    item["id"]: self.wm.get_window_geometry(item["id"])
                    for item in self.entries
                }
                break

        return True

    def track_hover(self):
        if not self.running:
            return False
        return True

    def begin_drag(self, handle):
        self.active = handle
        self.last_value = None

    def track_drag(self):
        if not self.running:
            return False

        pointer = self.wm.root.query_pointer()
        pressed = bool(pointer.mask & X.Button1Mask)

        x, y, w, h = self.wm.workarea()
        px, py = pointer.root_x, pointer.root_y

        if not hasattr(self, "was_pressed"):
            self.was_pressed = False

        just_pressed = pressed and not self.was_pressed
        self.was_pressed = pressed

        if self.active is None:
            if not just_pressed:
                return True

            for handle in self.handles:
                if handle.axis == "x":
                    hx = x + round(handle.boundary * w)
                    begin = y + round(handle.begin * h)
                    end = y + round(handle.end * h)
                    nearby = abs(px - hx) <= 12 and begin <= py <= end
                else:
                    hy = y + round(handle.boundary * h)
                    begin = x + round(handle.begin * w)
                    end = x + round(handle.end * w)
                    nearby = abs(py - hy) <= 12 and begin <= px <= end

                if nearby:
                    self.begin_drag(handle)
                    return True

            return True

        handle = self.active

        if not pressed:
            if self.last_value is not None:
                entries = [
                    (entry["id"], entry["rect"])
                    for entry in self.entries
                ]
                record_snap_history(entries, "Smart Resize")
                sync_snap_group_resize(entries)

            self.active = None
            self.last_value = None
            return True

        if handle.axis == "x":
            value = (px - x) / max(1, w)
        else:
            value = (py - y) / max(1, h)

        if self.last_value is None or abs(value - self.last_value) > 0.003:
            self.resize_boundary(handle, value)
            self.last_value = value

        return True

    def resize_boundary(self, handle, value):
        eps = 0.002
        axis = handle.axis
        old = handle.boundary
        begin, end = handle.begin, handle.end
        before = []
        after = []

        for entry in self.entries:
            x, y, w, h = entry["rect"]

            if axis == "x":
                overlaps = min(y + h, end) - max(y, begin) > eps
                if not overlaps:
                    continue
                if abs(x + w - old) < eps:
                    before.append(entry)
                elif abs(x - old) < eps:
                    after.append(entry)
            else:
                overlaps = min(x + w, end) - max(x, begin) > eps
                if not overlaps:
                    continue
                if abs(y + h - old) < eps:
                    before.append(entry)
                elif abs(y - old) < eps:
                    after.append(entry)

        if not before or not after:
            return

        minimum = 0.15

        if axis == "x":
            low = max(e["rect"][0] + minimum for e in before)
            high = min(
                e["rect"][0] + e["rect"][2] +
                e2["rect"][2] - minimum
                for e in before for e2 in after
            )
            high = min(
                high,
                *(e["rect"][0] + e["rect"][2] - minimum for e in after)
            )
        else:
            low = max(e["rect"][1] + minimum for e in before)
            high = min(
                e["rect"][1] + e["rect"][3] +
                e2["rect"][3] - minimum
                for e in before for e2 in after
            )
            high = min(
                high,
                *(e["rect"][1] + e["rect"][3] - minimum for e in after)
            )

        if low > high:
            return

        value = max(low, min(high, value))
        delta = value - old

        if abs(delta) < 0.001:
            return

        for entry in before:
            rect = entry["rect"]
            if axis == "x":
                rect[2] += delta
            else:
                rect[3] += delta

        for entry in after:
            rect = entry["rect"]
            if axis == "x":
                rect[0] += delta
                rect[2] -= delta
            else:
                rect[1] += delta
                rect[3] -= delta

        handle.boundary = value

        for entry in before + after:
            self.wm.place(entry["id"], tuple(entry["rect"]))

        for other in self.handles:
            if other is not handle and other.axis == axis:
                if abs(other.boundary - old) < eps:
                    other.boundary = value
            other.update_position()

    def check_windows(self):
        try:
            output = subprocess.check_output(
                ["wmctrl", "-l"], text=True
            )
            ids = {
                int(line.split()[0], 16)
                for line in output.splitlines()
                if line.split()
            }
            if any(entry["id"] not in ids for entry in self.entries):
                self.stop()
                return False
        except Exception:
            pass
        return True

    def stop(self):
        self.running = False
        for handle in self.handles:
            handle.destroy()
        self.handles.clear()

        if getattr(self, "divider_lock", None):
            self.divider_lock.close()
            self.divider_lock = None

        Gtk.main_quit()



def snap_group_path():
    return os.path.join(
        os.path.expanduser("~"),
        ".config", "snaplayout", "groups.json"
    )


def load_snap_groups():
    try:
        with open(snap_group_path(), "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_snap_groups(groups):
    path = snap_group_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w") as f:
        json.dump(groups, f, indent=2)
    os.replace(temporary, path)


def available_snap_windows():
    result = subprocess.run(
        ["wmctrl", "-lx"],
        capture_output=True, text=True
    )
    windows = {}
    for line in result.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            wid = int(parts[0], 16)
        except ValueError:
            continue
        windows[wid] = {
            "class": parts[2],
            "title": parts[4]
        }
    return windows


def record_snap_group(entries):
    windows = available_snap_windows()
    members = []

    for wid, rect in entries:
        info = windows.get(int(wid))
        if not info:
            return False
        members.append({
            "id": int(wid),
            "class": info["class"],
            "title": info["title"],
            "rect": list(rect)
        })

    if len(members) < 2:
        return False

    groups = load_snap_groups()
    signature = sorted(member["id"] for member in members)

    groups = [
        group for group in groups
        if sorted(
            member.get("id")
            for member in group.get("windows", [])
        ) != signature
    ]

    groups.insert(0, {
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "name": " + ".join(
            member["class"].split(".")[0]
            for member in members
        ),
        "windows": members
    })

    save_snap_groups(groups[:30])
    return True



def sync_snap_group_resize(entries):
    groups = load_snap_groups()
    if not groups:
        return False

    current = {
        int(wid): [round(float(v), 6) for v in rect]
        for wid, rect in entries
    }

    current_ids = set(current)
    active = available_snap_windows()
    changed = False

    for group in groups:
        members = group.get("windows", [])
        group_ids = {
            member.get("id")
            for member in members
        }

        if group_ids != current_ids:
            continue

        if not all(
            member.get("id") in active and
            active[member["id"]]["class"] == member.get("class")
            for member in members
        ):
            continue

        for member in members:
            wid = member["id"]
            new_rect = current[wid]

            if member.get("rect") != new_rect:
                member["rect"] = new_rect
                changed = True

    if changed:
        save_snap_groups(groups)

    return changed


class SnapGroupSwitcher(Gtk.Window):
    def __init__(self):
        super().__init__(title="Snap Groups")
        self.wm = WindowManager()
        self.set_default_size(540, 420)
        self.set_border_width(16)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)

        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12
        )
        self.add(root)

        title = Gtk.Label()
        title.set_markup(
            '<span size="x-large" weight="bold">Snap Groups</span>'
        )
        title.set_xalign(0)
        root.pack_start(title, False, False, 0)

        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        root.pack_start(self.status, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC
        )
        root.pack_start(scroll, True, True, 0)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self.listbox)

        self.refresh()

    def refresh(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)

        groups = load_snap_groups()
        active = available_snap_windows()

        if not groups:
            self.status.set_text("No Snap Groups available.")
            self.show_all()
            return

        self.status.set_text(
            f"{len(groups)} saved groups"
        )

        for index, group in enumerate(groups):
            members = group.get("windows", [])
            valid = all(
                member.get("id") in active and
                active[member["id"]]["class"] == member.get("class")
                for member in members
            )

            row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=10
            )
            row.set_border_width(8)

            info = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=4
            )

            name = Gtk.Label(
                label=group.get("name", "Snap Group")
            )
            name.set_xalign(0)
            name.set_ellipsize(3)
            info.pack_start(name, False, False, 0)

            detail = Gtk.Label(
                label=(
                    f'{len(members)} windows  •  '
                    f'{group.get("created", "")}'
                )
            )
            detail.set_xalign(0)
            info.pack_start(detail, False, False, 0)

            row.pack_start(info, True, True, 0)

            restore = Gtk.Button(label="Restore")
            restore.set_sensitive(valid)
            restore.connect(
                "clicked", self.restore_group, index
            )
            row.pack_start(restore, False, False, 0)

            delete = Gtk.Button(label="Delete")
            delete.connect(
                "clicked", self.delete_group, index
            )
            row.pack_start(delete, False, False, 0)

            self.listbox.add(row)

        self.show_all()

    def restore_group(self, button, index):
        groups = load_snap_groups()
        if index >= len(groups):
            return

        members = groups[index].get("windows", [])
        active = available_snap_windows()

        if not members or not all(
            member.get("id") in active and
            active[member["id"]]["class"] == member.get("class")
            for member in members
        ):
            self.status.set_text(
                "Restore failed: one or more windows have been closed."
            )
            return

        for member in members:
            wid = member["id"]
            subprocess.run(
                ["wmctrl", "-ia", hex(wid)],
                check=False
            )
            self.wm.place(wid, tuple(member["rect"]))

        self.status.set_text("Snap Group restored successfully.")

    def delete_group(self, button, index):
        groups = load_snap_groups()
        if index < len(groups):
            groups.pop(index)
            save_snap_groups(groups)
        self.refresh()



def snap_history_path():
    return os.path.join(
        os.path.expanduser("~"),
        ".config", "snaplayout", "history.json"
    )


def load_snap_history():
    try:
        with open(snap_history_path()) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {"states": [], "index": -1}


def save_snap_history(data):
    path = snap_history_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp, path)


def record_snap_history(entries, label="Snap Layout"):
    active = available_snap_windows()
    members = []

    for wid, rect in entries:
        wid = int(wid)
        if wid not in active:
            return False
        members.append({
            "id": wid,
            "class": active[wid]["class"],
            "rect": [round(float(v), 6) for v in rect]
        })

    if not members:
        return False

    data = load_snap_history()
    states = data.get("states", [])
    index = data.get("index", -1)
    states = states[:index + 1]

    if states and states[-1].get("windows") == members:
        return False

    states.append({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "label": label,
        "windows": members
    })

    states = states[-50:]
    save_snap_history({
        "states": states,
        "index": len(states) - 1
    })
    return True


def restore_snap_state(state):
    active = available_snap_windows()
    members = state.get("windows", [])

    if not members:
        return False

    for member in members:
        wid = member.get("id")
        if (
            wid not in active or
            active[wid]["class"] != member.get("class")
        ):
            return False

    wm = WindowManager()
    for member in members:
        wid = member["id"]
        subprocess.run(
            ["wmctrl", "-ia", hex(wid)],
            check=False
        )
        wm.place(wid, tuple(member["rect"]))

    return True


def navigate_snap_history(step):
    data = load_snap_history()
    states = data.get("states", [])
    index = data.get("index", -1)
    target = index + step

    if not 0 <= target < len(states):
        return False

    if not restore_snap_state(states[target]):
        return False

    data["index"] = target
    save_snap_history(data)
    return True


class SnapHistoryWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Window Switcher & Snap History")
        self.set_default_size(580, 480)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_border_width(16)
        self.connect("destroy", Gtk.main_quit)

        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12
        )
        self.add(root)

        heading = Gtk.Label()
        heading.set_markup(
            '<span size="x-large" weight="bold">'
            'Window Switcher &amp; Snap History'
            '</span>'
        )
        heading.set_xalign(0)
        root.pack_start(heading, False, False, 0)

        controls = Gtk.Box(spacing=8)
        root.pack_start(controls, False, False, 0)

        undo = Gtk.Button(label="Undo")
        undo.connect("clicked", self.navigate, -1)
        controls.pack_start(undo, True, True, 0)

        redo = Gtk.Button(label="Redo")
        redo.connect("clicked", self.navigate, 1)
        controls.pack_start(redo, True, True, 0)

        groups = Gtk.Button(label="Snap Groups")
        groups.connect("clicked", self.open_groups)
        controls.pack_start(groups, True, True, 0)

        self.status = Gtk.Label()
        self.status.set_xalign(0)
        root.pack_start(self.status, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC
        )
        root.pack_start(scroll, True, True, 0)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self.listbox)

        self.refresh()

    def refresh(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)

        data = load_snap_history()
        states = data.get("states", [])
        index = data.get("index", -1)

        self.status.set_text(
            f"{len(states)} history entries"
        )

        for position in range(len(states) - 1, -1, -1):
            state = states[position]
            row = Gtk.Box(spacing=10)
            row.set_border_width(8)

            label = Gtk.Label(
                label=(
                    f'{state.get("label", "Snap")}  •  '
                    f'{state.get("time", "")}'
                )
            )
            label.set_xalign(0)
            row.pack_start(label, True, True, 0)

            button = Gtk.Button(
                label="Current" if position == index else "Restore"
            )
            button.set_sensitive(position != index)
            button.connect(
                "clicked", self.restore_entry, position
            )
            row.pack_start(button, False, False, 0)

            self.listbox.add(row)

        self.show_all()

    def navigate(self, button, step):
        if not navigate_snap_history(step):
            self.status.set_text(
                "No history available, or a window has been closed."
            )
            return
        self.refresh()

    def restore_entry(self, button, position):
        data = load_snap_history()
        states = data.get("states", [])

        if position >= len(states):
            return

        if not restore_snap_state(states[position]):
            self.status.set_text(
                "Restore failed: window is unavailable."
            )
            return

        data["index"] = position
        save_snap_history(data)
        self.refresh()

    def open_groups(self, button):
        subprocess.Popen(
            [
                sys.executable,
                os.path.abspath(__file__),
                "--snap-groups"
            ],
            start_new_session=True
        )


def snap_settings():
    import json
    from pathlib import Path

    defaults = {
        "animation_speed": 180,
        "preview_color": "#3B82F6",
        "corner_radius": 12
    }

    try:
        path = Path(str(Path.home() / ".config/snaplayout/settings.json"))
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return defaults
        return {**defaults, **data}
    except (OSError, ValueError, TypeError):
        return defaults


class SnapPreview(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.connect("draw", self.on_draw)
        self.connect("realize", self.on_realize)

    def on_realize(self, widget):
        window = self.get_window()
        if window:
            window.set_pass_through(True)

    def on_draw(self, widget, cr):
        import math

        from gi.repository import Gdk

        settings = snap_settings()
        radius = max(0, min(30, int(settings["corner_radius"])))

        color = Gdk.RGBA()
        if not color.parse(str(settings["preview_color"])):
            color.parse("#3B82F6")

        w = self.get_allocated_width()
        h = self.get_allocated_height()

        # Clear transparent background.
        cr.set_operator(0)
        cr.paint()
        cr.set_operator(2)

        def rounded_rect(x, y, width, height, radius):
            radius = min(radius, width / 2, height / 2)

            cr.new_sub_path()
            cr.arc(x + width - radius, y + radius,
                   radius, -math.pi / 2, 0)
            cr.arc(x + width - radius, y + height - radius,
                   radius, 0, math.pi / 2)
            cr.arc(x + radius, y + height - radius,
                   radius, math.pi / 2, math.pi)
            cr.arc(x + radius, y + radius,
                   radius, math.pi, 3 * math.pi / 2)
            cr.close_path()

        rounded_rect(0, 0, w, h, radius)
        cr.set_source_rgba(color.red, color.green, color.blue, 0.20)
        cr.fill()

        rounded_rect(2, 2, max(1, w - 4), max(1, h - 4), max(0, radius - 2))
        cr.set_source_rgba(color.red, color.green, color.blue, 0.95)
        cr.set_line_width(3)
        cr.stroke()

        return False

    def show_rect(self, x, y, w, h):
        target = (int(x), int(y), max(1, int(w)), max(1, int(h)))

        if hasattr(self, "animation_id") and self.animation_id:
            GLib.source_remove(self.animation_id)
            self.animation_id = None

        if not self.get_visible():
            self.move(target[0], target[1])
            self.resize(target[2], target[3])
            self.show_all()
            self.current_rect = target
            self.queue_draw()
            return

        self.animation_from = getattr(self, "current_rect", target)
        self.animation_to = target
        self.animation_started = time.monotonic()
        self.animation_id = GLib.timeout_add(16, self.animate_rect)

    def animate_rect(self):
        progress = min(
            1.0,
            (time.monotonic() - self.animation_started) / (max(100, min(500, float(snap_settings()['animation_speed']))) / 1000)
        )
        eased = 1.0 - (1.0 - progress) ** 3

        current = tuple(
            round(a + (b - a) * eased)
            for a, b in zip(self.animation_from, self.animation_to)
        )

        self.move(current[0], current[1])
        self.resize(max(1, current[2]), max(1, current[3]))
        self.current_rect = current
        self.queue_draw()

        if progress >= 1.0:
            self.animation_id = None
            return False
        return True

    def hide_preview(self):
        if getattr(self, "animation_id", None):
            GLib.source_remove(self.animation_id)
            self.animation_id = None
        self.hide()


class SnapLayout(Gtk.Window):
    def __init__(self):
        super().__init__(title="XFCE Custom Layout")

        self.wm = WindowManager()
        self.preview = SnapPreview()
        self.target = self.wm.active_window()
        self.popup_mode = False
        self.assist_mode = False
        self.drag_mode = "--drag-mode" in sys.argv
        self.drag_tiles = []
        self.live_tiles = {}
        self.live_active = None
        self.live_last = 0.0
        self.composite_pixmap = None
        self.composite_window = None
        self.composite_size = None
        self.composite_error_shown = False
        self.drag_choice = None
        self.drag_seen_pressed = False
        self.edge_mode = None
        if "--edge" in sys.argv:
            pos = sys.argv.index("--edge")
            if len(sys.argv) > pos + 1:
                self.edge_mode = sys.argv[pos + 1]

        if "--target" in sys.argv:
            index = sys.argv.index("--target")

            if len(sys.argv) > index + 1:
                self.target = int(sys.argv[index + 1])

        if "--popup" in sys.argv:
            self.popup_mode = True
            index = sys.argv.index("--popup")

            if len(sys.argv) > index + 2:
                self.popup_x = int(sys.argv[index + 1])
                self.popup_y = int(sys.argv[index + 2])
            else:
                self.popup_mode = False

        self.current_layout = read_active_layouts().get(str(self.target))
        if not isinstance(self.current_layout, int) or not 0 <= self.current_layout < len(LAYOUTS):
            self.current_layout = None

        self.set_default_size(440, 420)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_border_width(0)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)

        if self.popup_mode:
            self.set_position(Gtk.WindowPosition.NONE)
            self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        else:
            self.set_position(Gtk.WindowPosition.CENTER)
            self.set_type_hint(Gdk.WindowTypeHint.UTILITY)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())

        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        main = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14
        )

        main.set_name("main")
        main.set_border_width(20)

        self.add(main)

        heading = Gtk.Label(label="XFCE Custom Layout")
        heading.set_name("heading")
        heading.set_xalign(0)

        main.pack_start(
            heading,
            False,
            False,
            0
        )

        subtitle = Gtk.Label(
            label="Select a layout, then click a tile"
        )

        subtitle.set_name("subtitle")
        subtitle.set_xalign(0)

        main.pack_start(
            subtitle,
            False,
            False,
            0
        )

        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(12)

        main.pack_start(
            grid,
            True,
            True,
            0
        )

        for index, (name, layout) in enumerate(LAYOUTS):
            widget = self.make_layout(name, layout)
            if index == self.current_layout:
                widget.get_style_context().add_class("layout-current")

            grid.attach(
                widget,
                index % 2,
                index // 2,
                1,
                1
            )

        create_button = Gtk.Button(label="+ Create Layout")
        create_button.set_tooltip_text("Create your own Snap Layout")
        create_button.connect("clicked", self.open_layout_builder)

        main.pack_start(
            create_button,
            False,
            False,
            0
        )

        footer = Gtk.Label(
            label="XFCE 4.20  •  X11  •  Custom Snap Layout"
        )

        footer.set_name("footer")

        main.pack_start(
            footer,
            False,
            False,
            0
        )

        self.connect(
            "delete-event",
            lambda widget, event: (
                None,
                True
            )[-1]
        )
        self.connect("destroy", self.on_popup_destroy)
        self.connect(
            "destroy",
            Gtk.main_quit
        )

        self.connect(
            "key-press-event",
            self.on_key
        )

        self.connect(
            "show",
            self.on_show
        )

    def animate_popup_fade(self):
        if self.drag_mode or self.edge_mode or self.assist_mode:
            return False

        window = self.get_window()
        if window is None:
            return False

        self.fade_started = time.monotonic()
        window.set_opacity(0.0)
        GLib.timeout_add(16, self.fade_popup_frame)
        return False

    def fade_popup_frame(self):
        if not self.get_visible() or self.assist_mode:
            return False

        window = self.get_window()
        if window is None:
            return False

        progress = min(
            1.0,
            (time.monotonic() - self.fade_started) / 0.18
        )

        # Smooth ease-out quint
        eased = 1.0 - (1.0 - progress) ** 5
        window.set_opacity(eased)

        if progress >= 1.0:
            window.set_opacity(1.0)
            return False

        return True

    def on_show(self, widget):
        GLib.idle_add(self.animate_popup_fade)
        if self.edge_mode:
            GLib.idle_add(self.start_edge_snap)
            return

        if self.drag_mode:
            self.set_keep_above(True)
            self.set_accept_focus(False)
            GLib.idle_add(self.position_drag_popup)
            GLib.timeout_add(25, self.track_drag_selection)
            GLib.timeout_add(100, self.refresh_live_tile)
            return

        if not self.popup_mode:
            return

        gdk_display = Gdk.Display.get_default()
        monitor = gdk_display.get_monitor_at_point(
            self.popup_x,
            self.popup_y
        )
        geometry = monitor.get_geometry()

        width, height = self.get_size()

        # Position below maximize button.
        x = self.popup_x - width // 2
        y = self.popup_y + 8

        # Keep popup entirely inside the monitor.
        min_x = geometry.x + 8
        max_x = geometry.x + geometry.width - width - 8
        min_y = geometry.y + 8
        max_y = geometry.y + geometry.height - height - 8

        x = max(min_x, min(x, max_x))
        y = max(min_y, min(y, max_y))

        self.move(x, y)
        self.pointer_out_since = None
        self.auto_close_started = time.monotonic()
        if not self.drag_mode:
            GLib.timeout_add(50, self.check_auto_close)
            GLib.timeout_add(100, self.refresh_live_tile)

    def position_drag_popup(self):
        screen = Gdk.Screen.get_default()
        width = screen.get_width()
        _, work_y, _, _ = self.wm.workarea()

        popup_width, _ = self.get_size()

        self.move(
            max(0, (width - popup_width) // 2),
            work_y + 12
        )

        self.present()
        win = self.get_window()
        if win:
            win.set_pass_through(True)
        return False

    def track_drag_selection(self):
        if not self.get_visible() or self.assist_mode:
            return False
        pointer = self.wm.root.query_pointer()
        px, py = pointer.root_x, pointer.root_y
        pressed = bool(pointer.mask & X.Button1Mask)
        if pressed:
            self.drag_seen_pressed = True

        choice = None
        for button, rect, layout in self.drag_tiles:
            if not button.get_mapped():
                continue

            gdk_window = button.get_window()
            if gdk_window is None:
                continue

            _, bx, by = gdk_window.get_origin()
            bw = button.get_allocated_width()
            bh = button.get_allocated_height()

            if bx <= px < bx + bw and by <= py < by + bh:
                choice = (button, rect, layout)
                break

        if choice != self.drag_choice:
            if self.drag_choice:
                self.drag_choice[0].get_style_context().remove_class("tile-active")
                self.clear_live_tile(self.drag_choice[0])
            self.drag_choice = choice
            if choice:
                self.live_active = choice[0]
                choice[0].get_style_context().add_class("tile-active")
                self.show_snap_preview(choice[1])
                GLib.idle_add(self.update_live_tile, choice[0])
            else:
                self.live_active = None
                self.hide_snap_preview()

        if self.drag_seen_pressed and not pressed:
            if choice and self.target:
                _, rect, layout = choice
                self.hide_snap_preview()
                self.wm.animate_place(self.target, rect)
                remember_active_layout(self.target, layout)
                self.used_ids = {self.target}
                self.remaining = [slot for slot in layout if slot is not rect]
                self.show_snap_assist()
                GLib.timeout_add(200, self.finish_edge_snap, self.target, rect)
            else:
                self.drag_seen_pressed = False
                self.hide_snap_preview()
                self.destroy()
                return False
            return False
        return True

    def check_auto_close(self):
        if self.assist_mode:
            return False

        if not self.get_visible():
            return False

        pointer = self.wm.root.query_pointer()
        px, py = pointer.root_x, pointer.root_y

        x, y = self.get_position()
        w, h = self.get_size()

        inside_popup = (
            x <= px < x + w
            and y <= py < y + h
        )

        inside_button = (
            self.popup_x - 55 <= px <= self.popup_x + 10
            and self.popup_y - 45 <= py <= self.popup_y + 8
        )

        bridge = (
            min(x, self.popup_x - 55) <= px <= max(x + w, self.popup_x + 10)
            and min(y, self.popup_y - 45) <= py <= max(y + h, self.popup_y + 8)
        )

        if inside_popup or inside_button or bridge:
            self.pointer_out_since = None
            return True

        if self.pointer_out_since is None:
            self.pointer_out_since = time.monotonic()

        if time.monotonic() - self.pointer_out_since >= 1.0:
            self.destroy()
            return False

        return True


    def open_layout_builder(self, button):
        dialog = Gtk.Dialog(
            title="Custom Layout Builder",
            transient_for=self,
            modal=True,
            destroy_with_parent=True
        )
        dialog.set_default_size(500, 460)
        dialog.set_resizable(False)

        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
        #builder-dialog {
            background: #101827;
        }
        #builder-heading {
            color: #f8fafc;
            font-size: 21px;
            font-weight: bold;
        }
        #builder-subtitle {
            color: #94a3b8;
            font-size: 12px;
        }
        #builder-label {
            color: #cbd5e1;
            font-size: 12px;
            font-weight: bold;
        }
        #builder-entry {
            background: #1e293b;
            color: #f8fafc;
            border: 1px solid #334155;
            border-radius: 9px;
            padding: 10px;
        }
        #builder-spin {
            background: #1e293b;
            color: #f8fafc;
            border: 1px solid #334155;
            border-radius: 9px;
        }
        #builder-preview {
            background: #0b1220;
            border: 1px solid #334155;
            border-radius: 12px;
        }
        #builder-cancel {
            background: #1e293b;
            color: #cbd5e1;
            border: 1px solid #334155;
            border-radius: 9px;
            padding: 9px 18px;
        }
        #builder-save {
            background: #2563eb;
            color: white;
            border: 1px solid #3b82f6;
            border-radius: 9px;
            padding: 9px 18px;
            font-weight: bold;
        }
        #builder-save:hover {
            background: #3b82f6;
        }
        #builder-cancel:hover {
            background: #334155;
        }
        #builder-scale trough {
            background: #334155;
            border-radius: 8px;
            min-height: 6px;
        }
        #builder-scale highlight {
            background: #3b82f6;
            border-radius: 8px;
        }
        #builder-scale slider {
            background: #93c5fd;
            border: 2px solid #2563eb;
            border-radius: 50%;
            min-width: 15px;
            min-height: 15px;
        }
        """)

        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        dialog.set_name("builder-dialog")

        area = dialog.get_content_area()
        area.set_spacing(14)
        area.set_border_width(22)

        heading = Gtk.Label(label="Create your layout")
        heading.set_name("builder-heading")
        heading.set_xalign(0)
        area.pack_start(heading, False, False, 0)

        subtitle = Gtk.Label(
            label="Design your perfect workspace"
        )
        subtitle.set_name("builder-subtitle")
        subtitle.set_xalign(0)
        area.pack_start(subtitle, False, False, 0)

        name_label = Gtk.Label(label="LAYOUT NAME")
        name_label.set_name("builder-label")
        name_label.set_xalign(0)
        area.pack_start(name_label, False, False, 0)

        name_entry = Gtk.Entry()
        name_entry.set_name("builder-entry")
        name_entry.set_text("My Custom Layout")
        area.pack_start(name_entry, False, False, 0)

        count_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12
        )

        count_label = Gtk.Label(label="Number of Windows")
        count_label.set_name("builder-label")
        count_label.set_xalign(0)
        count_row.pack_start(count_label, True, True, 0)

        count_spin = Gtk.SpinButton.new_with_range(2, 8, 1)
        count_spin.set_name("builder-spin")
        count_spin.set_value(3)
        count_row.pack_end(count_spin, False, False, 0)

        area.pack_start(count_row, False, False, 0)

        ratio_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12
        )

        ratio_label = Gtk.Label(label="First window width")
        ratio_label.set_name("builder-label")
        ratio_label.set_xalign(0)
        ratio_row.pack_start(ratio_label, True, True, 0)

        ratio_value = Gtk.Label(label="50%")
        ratio_value.set_name("builder-subtitle")
        ratio_row.pack_end(ratio_value, False, False, 0)

        area.pack_start(ratio_row, False, False, 0)

        ratio = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 20, 80, 1
        )
        ratio.set_name("builder-scale")
        ratio.set_value(50)
        ratio.set_draw_value(False)
        area.pack_start(ratio, False, False, 0)

        preview_label = Gtk.Label(label="LIVE PREVIEW")
        preview_label.set_name("builder-label")
        preview_label.set_xalign(0)
        area.pack_start(preview_label, False, False, 0)

        preview = Gtk.DrawingArea()
        preview.set_name("builder-preview")
        preview.set_size_request(420, 140)
        area.pack_start(preview, True, True, 0)


        editor = {
            "slots": [],
            "selected": None,
            "merge": False,
            "drag": None,
            "updating": False
        }

        def default_slots():
            count = count_spin.get_value_as_int()
            first = ratio.get_value() / 100.0
            slots = [(0, 0, first, 1)]
            remaining = count - 1
            for i in range(remaining):
                slots.append((
                    first, i / remaining,
                    1 - first, 1 / remaining
                ))
            return slots

        editor["slots"] = default_slots()

        def generate_slots():
            return [tuple(slot) for slot in editor["slots"]]

        def select_zone(index):
            editor["selected"] = index
            preview.queue_draw()

        def zone_at(px, py):
            width = max(1, preview.get_allocated_width())
            height = max(1, preview.get_allocated_height())
            nx, ny = px / width, py / height

            for i, (x, y, w, h) in enumerate(editor["slots"]):
                if x <= nx <= x + w and y <= ny <= y + h:
                    return i
            return None

        def draw_preview(widget, cr):
            width = widget.get_allocated_width()
            height = widget.get_allocated_height()

            cr.set_source_rgb(0.043, 0.071, 0.125)
            cr.paint()
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(15)

            for index, (x, y, w, h) in enumerate(editor["slots"]):
                px = x * width + 5
                py = y * height + 5
                pw = max(1, w * width - 10)
                ph = max(1, h * height - 10)

                selected = editor["selected"] == index

                if selected:
                    cr.set_source_rgb(0.22, 0.55, 1.0)
                else:
                    cr.set_source_rgb(0.145, 0.388, 0.922)

                cr.rectangle(px, py, pw, ph)
                cr.fill()

                cr.set_source_rgb(
                    0.75 if selected else 0.58,
                    0.88 if selected else 0.78,
                    1.0
                )
                cr.set_line_width(2 if selected else 1.5)
                cr.rectangle(px, py, pw, ph)
                cr.stroke()

                text = str(index + 1)
                ext = cr.text_extents(text)
                tx = px + (pw - ext.width) / 2 - ext.x_bearing
                ty = py + (ph - ext.height) / 2 - ext.y_bearing

                cr.set_source_rgb(1, 1, 1)
                cr.move_to(tx, ty)
                cr.show_text(text)

            return False

        preview.connect("draw", draw_preview)
        preview.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK
        )

        def shared_edge(a, b):
            ax, ay, aw, ah = a
            bx, by, bw, bh = b
            eps = 0.001

            if abs(ay - by) < eps and abs(ah - bh) < eps:
                if abs(ax + aw - bx) < eps or abs(bx + bw - ax) < eps:
                    return (
                        min(ax, bx), ay,
                        aw + bw, ah
                    )

            if abs(ax - bx) < eps and abs(aw - bw) < eps:
                if abs(ay + ah - by) < eps or abs(by + bh - ay) < eps:
                    return (
                        ax, min(ay, by),
                        aw, ah + bh
                    )
            return None

        def split_zone(vertical):
            index = editor["selected"]
            if index is None:
                return
            if len(editor["slots"]) >= 8:
                return

            x, y, w, h = editor["slots"][index]

            if vertical:
                first = (x, y, w / 2, h)
                second = (x + w / 2, y, w / 2, h)
            else:
                first = (x, y, w, h / 2)
                second = (x, y + h / 2, w, h / 2)

            editor["slots"][index] = first
            editor["slots"].insert(index + 1, second)
            editor["selected"] = index
            preview.queue_draw()

        def begin_merge():
            if editor["selected"] is not None:
                editor["merge"] = True

        def on_preview_press(widget, event):
            if event.button != 1:
                return False

            index = zone_at(event.x, event.y)

            if editor["merge"]:
                editor["merge"] = False
                first = editor["selected"]

                if first is not None and index is not None and first != index:
                    merged = shared_edge(
                        editor["slots"][first],
                        editor["slots"][index]
                    )

                    if merged is not None:
                        editor["slots"][first] = merged
                        editor["slots"].pop(index)
                        editor["selected"] = (
                            first - 1 if index < first else first
                        )

                preview.queue_draw()
                return True

            width = max(1, widget.get_allocated_width())
            boundary = ratio.get_value() / 100.0

            # Preserve dragging of the main vertical divider.
            if abs(event.x / width - boundary) <= 0.025:
                editor["drag"] = True
                return True

            select_zone(index)
            return True

        def on_preview_motion(widget, event):
            if not editor["drag"]:
                return False

            width = max(1, widget.get_allocated_width())
            value = max(20, min(80, round(event.x / width * 100)))
            ratio.set_value(value)
            return True

        def on_preview_release(widget, event):
            if event.button == 1:
                editor["drag"] = None
            return False

        preview.connect("button-press-event", on_preview_press)
        preview.connect("motion-notify-event", on_preview_motion)
        preview.connect("button-release-event", on_preview_release)

        tools = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )

        split_v = Gtk.Button(label="Split Vertical")
        split_h = Gtk.Button(label="Split Horizontal")
        merge = Gtk.Button(label="Merge")

        for button in (split_v, split_h, merge):
            button.set_name("builder-cancel")
            tools.pack_start(button, True, True, 0)

        split_v.connect("clicked", lambda b: split_zone(True))
        split_h.connect("clicked", lambda b: split_zone(False))
        merge.connect("clicked", lambda b: begin_merge())

        area.pack_start(tools, False, False, 0)

        def reset_layout(widget):
            if editor["updating"]:
                return
            editor["slots"] = default_slots()
            editor["selected"] = None
            preview.queue_draw()

        count_spin.connect("value-changed", reset_layout)

        def on_ratio_changed(widget):
            value = widget.get_value() / 100.0
            ratio_value.set_text(f"{round(value * 100)}%")

            if editor["updating"]:
                return

            slots = editor["slots"]
            if len(slots) < 2:
                return

            old = slots[0][2]
            if old <= 0 or old >= 1:
                return

            updated = []
            for x, y, w, h in slots:
                if x + w <= old + 0.00001:
                    updated.append((x * value / old, y, w * value / old, h))
                elif x >= old - 0.00001:
                    scale = (1 - value) / (1 - old)
                    updated.append((
                        value + (x - old) * scale,
                        y, w * scale, h
                    ))
                else:
                    updated.append((x, y, w, h))

            editor["slots"] = updated
            preview.queue_draw()

        ratio.connect("value-changed", on_ratio_changed)

        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save Layout", Gtk.ResponseType.OK)

        cancel_button = dialog.get_widget_for_response(
            Gtk.ResponseType.CANCEL
        )
        save_button = dialog.get_widget_for_response(
            Gtk.ResponseType.OK
        )

        cancel_button.set_name("builder-cancel")
        save_button.set_name("builder-save")

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            name = name_entry.get_text().strip()[:40]
            slots = generate_slots()

            if not name:
                name = "Custom Layout"

            try:
                save_custom_layout(name, slots)
            except OSError as error:
                error_dialog = Gtk.MessageDialog(
                    transient_for=dialog,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="Failed to save layout"
                )
                error_dialog.format_secondary_text(str(error))
                error_dialog.run()
                error_dialog.destroy()
            else:
                LAYOUTS.append((name, slots))
                print("Custom Layout saved:", name)
                dialog.destroy()
                self.destroy()
                return

        dialog.destroy()

    def show_snap_preview(self, rect):
        x, y, width, height = self.wm.workarea()
        rx, ry, rw, rh = rect

        px = x + round(rx * width) + GAP
        py = y + round(ry * height) + GAP
        pw = max(100, round(rw * width) - GAP * 2)
        ph = max(100, round(rh * height) - GAP * 2)

        self.preview.show_rect(px, py, pw, ph)

    def hide_snap_preview(self):
        self.preview.hide_preview()

    def on_popup_destroy(self, widget):
        self.release_composite()
        self.preview.destroy()

    def make_layout(self, name, layout):
        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=7
        )

        outer.set_name("layout-button")

        fixed = Gtk.Fixed()
        fixed.set_size_request(175, 72)

        for rect in layout:
            x, y, w, h = rect

            button = Gtk.EventBox()
            button.set_name("tile")
            button.set_visible_window(True)

            px = round(x * 175) + 2
            py = round(y * 72) + 2
            pw = max(10, round(w * 175) - 4)
            ph = max(10, round(h * 72) - 4)

            button.set_size_request(pw, ph)
            live_image = Gtk.Image()
            live_image.set_size_request(pw, ph)
            button.add(live_image)
            self.live_tiles[button] = (live_image, pw, ph)
            button.add_events(
                Gdk.EventMask.ENTER_NOTIFY_MASK |
                Gdk.EventMask.LEAVE_NOTIFY_MASK
            )
            if self.drag_mode:
                self.drag_tiles.append((button, rect, layout))
            button.connect("enter-notify-event", self.on_tile_enter, rect)
            button.connect("leave-notify-event", self.on_tile_leave)

            fixed.put(
                button,
                px,
                py
            )

            button.connect(
                "button-press-event",
                self.on_tile,
                rect,
                layout
            )

        outer.pack_start(
            fixed,
            False,
            False,
            0
        )

        index = next((i for i, (_, slots) in enumerate(LAYOUTS) if slots is layout), None)
        label = Gtk.Label(label=(name + "  ✓ Active") if index == self.current_layout else name)
        label.set_name("layout-label")

        outer.pack_start(
            label,
            False,
            False,
            0
        )

        return outer

    def clear_live_tile(self, button):
        if button in self.live_tiles:
            self.live_tiles[button][0].clear()

    def release_composite(self):
        if self.composite_pixmap is not None:
            try:
                self.composite_pixmap.free()
                self.wm.connection.sync()
            except Exception:
                pass
        self.composite_pixmap = None
        self.composite_window = None
        self.composite_size = None

    def composite_thumbnail(self, window_id, width, height):
        try:
            from Xlib.ext import composite
            conn = self.wm.connection
            window = conn.create_resource_object("window", int(window_id))
            geo = window.get_geometry()
            source_size = (geo.width, geo.height, geo.depth)
            if geo.width < 1 or geo.height < 1:
                return None

            if (self.composite_pixmap is None or
                    self.composite_window != window_id or
                    self.composite_size != source_size):
                self.release_composite()

                try:
                    window.composite_redirect_window(
                        composite.RedirectAutomatic
                    )
                    conn.sync()
                except Exception as exc:
                    print(
                        f"XComposite redirect: {exc}",
                        flush=True
                    )

                self.composite_pixmap = window.composite_name_window_pixmap()
                conn.sync()

                self.composite_window = window_id
                self.composite_size = source_size

            raw = self.composite_pixmap.get_image(
                0, 0, geo.width, geo.height, X.ZPixmap, 0xffffffff
            )
            if not raw or not raw.data:
                return None

            # Most X11 TrueColor desktops use 32-bit little-endian BGRX.
            if len(raw.data) != geo.width * geo.height * 4:
                return None
            frame = Image.frombytes(
                "RGB", (geo.width, geo.height), raw.data, "raw", "BGRX"
            )
            frame = frame.resize((width, height), Image.Resampling.BILINEAR)
            rgb = frame.tobytes()
            pixels = GLib.Bytes.new(rgb)
            return GdkPixbuf.Pixbuf.new_from_bytes(
                pixels, GdkPixbuf.Colorspace.RGB, False, 8,
                frame.width, frame.height, frame.width * 3
            )
        except Exception as exc:
            self.release_composite()
            if not self.composite_error_shown:
                print(f"XComposite preview: {type(exc).__name__}: {exc}", flush=True)
                self.composite_error_shown = True
            return None

    def update_live_tile(self, button):
        if not self.target or button not in self.live_tiles:
            return
        image, width, height = self.live_tiles[button]
        thumbnail = self.composite_thumbnail(self.target, width, height)
        if thumbnail:
            image.set_from_pixbuf(thumbnail)
        else:
            image.clear()

    def refresh_live_tile(self):
        if not self.get_visible() or self.assist_mode:
            return False
        if self.live_active:
            self.update_live_tile(self.live_active)
        return True

    def on_tile_enter(self, widget, event, rect):
        if self.drag_mode:
            return False

        if self.live_active is not None and self.live_active is not widget:
            self.clear_live_tile(self.live_active)
            self.live_active.get_style_context().remove_class("tile-active")

        self.live_active = widget
        widget.get_style_context().add_class("tile-active")
        self.show_snap_preview(rect)
        return False

    def on_tile_leave(self, widget, event):
        if self.drag_mode:
            return False

        if self.live_active is widget:
            self.live_active = None

        self.clear_live_tile(widget)
        widget.get_style_context().remove_class("tile-active")
        self.hide_snap_preview()
        return False

    def start_edge_snap(self):
        if self.edge_mode not in ("left", "right") or not self.target:
            self.destroy()
            return False

        layout = LAYOUTS[0][1]
        remember_active_layout(self.target, layout)
        rect = layout[0] if self.edge_mode == "left" else layout[1]

        self.wm.animate_place(self.target, rect)
        self.first_snap_rect = rect
        self.snap_selected = {}
        self.used_ids = {self.target}
        self.first_snap_rect = rect
        self.snap_selected = {}
        self.remaining = [slot for slot in layout if slot != rect]
        self.show_snap_assist()

        GLib.timeout_add(
            200,
            self.finish_edge_snap,
            self.target,
            rect
        )
        return False

    def finish_edge_snap(self, window_id, rect):
        self.wm.place(window_id, rect)
        return False

    def candidate_windows(self):
        result = subprocess.run(
            ["wmctrl", "-lx"], capture_output=True, text=True
        )
        if result.returncode != 0:
            return []

        candidates = []
        ignored = (
            "xfdesktop", "xfce4-panel", "plank",
            "snaplayout", "layoutku"
        )

        for line in result.stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue

            wid, desktop, wmclass, host, title = parts

            try:
                window_id = int(wid, 16)
                desktop_num = int(desktop)
            except ValueError:
                continue

            if desktop_num < 0 or window_id in self.used_ids:
                continue

            if any(value in wmclass.lower() for value in ignored):
                continue

            if not title.strip() or title == "XFCE Custom Layout":
                continue

            candidates.append((window_id, title.strip(), wmclass))

        return candidates

    def position_assist(self, rect):
        x, y, w, h = self.wm.workarea()
        rx, ry, rw, rh = rect

        sx = x + round(rx * w)
        sy = y + round(ry * h)
        sw = round(rw * w)
        sh = round(rh * h)

        pw, ph = self.get_size()

        self.move(
            sx + max(0, (sw - pw) // 2),
            sy + max(0, (sh - ph) // 2)
        )
        return False

    def get_window_thumbnail(self, window_id):
        try:
            from gi.repository import GdkX11

            gdk_window = GdkX11.X11Window.foreign_new_for_display(
                Gdk.Display.get_default(),
                window_id
            )

            if gdk_window:
                width = gdk_window.get_width()
                height = gdk_window.get_height()

                if width > 0 and height > 0:
                    pixbuf = Gdk.pixbuf_get_from_window(
                        gdk_window,
                        0,
                        0,
                        width,
                        height
                    )

                    if pixbuf:
                        return pixbuf.scale_simple(
                            190,
                            108,
                            GdkPixbuf.InterpType.BILINEAR
                        )
        except Exception:
            pass

        return None

    def show_snap_assist(self):
        if not self.remaining:
            self.destroy()
            return

        self.assist_mode = True
        self.release_composite()
        self.hide_snap_preview()

        old = self.get_child()
        if old:
            self.remove(old)

        self.set_title("Snap Assist")
        self.set_resizable(True)
        self.resize(470, 440)

        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12
        )
        root.set_name("main")
        root.set_border_width(18)
        self.add(root)

        heading = Gtk.Label(label="Snap Assist")
        heading.set_name("heading")
        heading.set_xalign(0)
        root.pack_start(heading, False, False, 0)

        subtitle = Gtk.Label(
            label=f"Pilih aplikasi untuk ruang seterusnya ({len(self.remaining)} kosong)"
        )
        subtitle.set_name("subtitle")
        subtitle.set_xalign(0)
        root.pack_start(subtitle, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC
        )
        root.pack_start(scroll, True, True, 0)

        items = Gtk.FlowBox()
        items.set_selection_mode(Gtk.SelectionMode.NONE)
        items.set_max_children_per_line(2)
        items.set_min_children_per_line(1)
        items.set_row_spacing(10)
        items.set_column_spacing(10)
        items.set_homogeneous(True)
        scroll.add(items)

        candidates = self.candidate_windows()

        if not candidates:
            label = Gtk.Label(
                label="Tiada aplikasi lain yang tersedia"
            )
            items.add(label)

        for window_id, title, wmclass in candidates:
            button = Gtk.Button()
            row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=10
            )

            card = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=8
            )

            thumbnail = self.get_window_thumbnail(window_id)

            if thumbnail:
                image = Gtk.Image.new_from_pixbuf(thumbnail)
            else:
                image = Gtk.Image.new_from_icon_name(
                    "application-x-executable",
                    Gtk.IconSize.DIALOG
                )

            image.set_halign(Gtk.Align.CENTER)
            card.pack_start(image, False, False, 0)

            label = Gtk.Label(label=title)
            label.set_ellipsize(3)
            label.set_max_width_chars(28)
            label.set_xalign(0.5)
            card.pack_start(label, False, False, 0)

            button.add(card)
            button.connect(
                "clicked",
                self.on_assist_select,
                window_id
            )
            items.add(button)

        close = Gtk.Button(label="Selesai / Tutup")
        close.connect(
            "clicked",
            lambda button: self.destroy()
        )
        root.pack_start(close, False, False, 0)

        self.show_all()
        GLib.idle_add(
            self.position_assist,
            self.remaining[0]
        )

    def on_assist_select(self, button, window_id):
        if not self.remaining or window_id in self.used_ids:
            return

        rect = self.remaining.pop(0)
        self.used_ids.add(window_id)
        if not hasattr(self, "snap_selected"):
            self.snap_selected = {}
        self.snap_selected[rect] = window_id

        subprocess.run(
            ["wmctrl", "-ia", hex(window_id)],
            check=False
        )

        subprocess.run(
            [
                "wmctrl", "-ir", hex(window_id),
                "-b", "remove,hidden,shaded,maximized_vert,maximized_horz,fullscreen"
            ],
            check=False
        )

        self.wm.animate_place(window_id, rect)

        GLib.timeout_add(
            200,
            self.finish_assist_selection,
            window_id,
            rect
        )

    def finish_assist_selection(self, window_id, rect):
        self.wm.place(window_id, rect)
        if not self.remaining and hasattr(self, "snap_selected"):
            self.launch_smart_divider()
            if hasattr(self, "first_snap_rect"):
                entries = [(self.target, self.first_snap_rect)]
                entries.extend(
                    (wid, slot)
                    for slot, wid in self.snap_selected.items()
                )
                record_snap_group(entries)
                record_snap_history(entries, "Snap Layout")
        self.show_snap_assist()
        return False

    def launch_smart_divider(self):
        with open(
            os.path.expanduser("~/.cache/snaplayout-debug.log"),
            "a"
        ) as log:
            log.write(
                f"launch called: target={self.target}, "
                f"first_rect={getattr(self, 'first_snap_rect', None)}, "
                f"selected={getattr(self, 'snap_selected', None)}\\n"
            )

        if not hasattr(self, "first_snap_rect"):
            return

        entries = [(self.target, self.first_snap_rect)]
        entries.extend(
            (wid, rect)
            for rect, wid in self.snap_selected.items()
        )

        if len(entries) < 2:
            return

        args = [
            sys.executable,
            os.path.abspath(__file__),
            "--resize-divider"
        ]

        for wid, rect in entries:
            args.append(str(wid))
            args.append(",".join(str(v) for v in rect))

        log_path = os.path.expanduser(
            "~/.cache/snaplayout-divider.log"
        )
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        if not replace_existing_smart_divider(entries):
            with open(log_path, "a") as log:
                log.write("Auto Replace: lock masih aktif\\n")
            return

        with open(log_path, "a") as log:
            subprocess.Popen(
                args,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )

    def on_tile(self, widget, event, rect, layout):
        if event.button != 1:
            return False

        self.hide_snap_preview()

        if not self.target:
            self.destroy()
            return True

        self.wm.animate_place(self.target, rect)
        remember_active_layout(self.target, layout)

        self.used_ids = {self.target}
        self.first_snap_rect = rect
        self.snap_selected = {}
        self.remaining = [
            slot for slot in layout
            if slot is not rect
        ]

        self.show_snap_assist()
        return True

    def on_key(self, widget, event):
        if Gdk.keyval_name(event.keyval) == "Escape":
            self.destroy()
            return True

        return False


def main():
    if "--snap-history" in sys.argv:
        window = SnapHistoryWindow()
        window.show_all()
        Gtk.main()
        return

    if "--snap-undo" in sys.argv:
        print("Undo:", navigate_snap_history(-1))
        return

    if "--snap-redo" in sys.argv:
        print("Redo:", navigate_snap_history(1))
        return

    if "--snap-groups" in sys.argv:
        window = SnapGroupSwitcher()
        window.show_all()
        Gtk.main()
        return

    if "--resize-divider" in sys.argv:
        i = sys.argv.index("--resize-divider") + 1
        args = sys.argv[i:]
        entries = []

        for pos in range(0, len(args), 2):
            wid = int(args[pos])
            rect = tuple(float(v) for v in args[pos + 1].split(","))
            entries.append((wid, rect))

        manager = SmartResizeManager(entries)

        if not manager.running:
            return

        Gtk.main()
        return

    if not os.environ.get("DISPLAY"):
        print("X11 display not found")
        sys.exit(1)

    try:
        window = SnapLayout()
        window.show_all()
        Gtk.main()

    except (XError, RuntimeError, ValueError) as error:
        print(error)
        sys.exit(1)


if __name__ == "__main__":
    main()
