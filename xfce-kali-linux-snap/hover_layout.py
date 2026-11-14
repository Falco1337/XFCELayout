import os
import sys
import time
import subprocess
from pathlib import Path
from Xlib import display, X, error

HOVER_DELAY = 0.5
POLL_INTERVAL = 0.04
BUTTON_WIDTH = 30
BUTTON_HEIGHT = 30

class HoverDetector:
    def __init__(self):
        self.display = display.Display()
        self.root = self.display.screen().root
        self.active_atom = self.display.intern_atom("_NET_ACTIVE_WINDOW")
        self.client_list_atom = self.display.intern_atom("_NET_CLIENT_LIST_STACKING")
        self.extents_atom = self.display.intern_atom("_NET_FRAME_EXTENTS")
        self.pid_atom = self.display.intern_atom("_NET_WM_PID")
        self.hover_start = None
        self.hover_window = None
        self.triggered = False
        self.popup = None
        self.drag = None
        self.was_pressed = False

    def pointer(self):
        p = self.root.query_pointer()
        return p.root_x, p.root_y

    def window_list(self):
        prop = self.root.get_full_property(
            self.client_list_atom,
            X.AnyPropertyType
        )
        if prop is None:
            return []
        return [int(v) for v in prop.value]

    def window_info(self, window_id):
        window = self.display.create_resource_object(
            "window", window_id
        )

        if window.get_attributes().map_state != X.IsViewable:
            return None

        client = window.get_geometry()
        parent = window.query_tree().parent

        if parent.id == self.root.id:
            frame = window
        else:
            frame = parent

        frame_geometry = frame.get_geometry()

        # Convert frame coordinates into root coordinates.
        translated = self.root.translate_coords(frame, 0, 0)

        frame_x = int(translated.x)
        frame_y = int(translated.y)
        frame_w = int(frame_geometry.width)
        frame_h = int(frame_geometry.height)

        ext = window.get_full_property(
            self.extents_atom, X.AnyPropertyType
        )

        if ext is not None and len(ext.value) >= 4:
            left, right, top, bottom = map(int, ext.value[:4])
        else:
            left = right = top = bottom = 0

        return {
            "id": window_id,
            "x": frame_x + left,
            "y": frame_y + top,
            "width": int(client.width),
            "height": int(client.height),
            "left": left,
            "right": right,
            "top": top,
            "bottom": bottom
        }


    def maximize_area(self, info):
        import configparser
        import struct
        import glob

        def xfconf(property_name, fallback):
            try:
                return subprocess.check_output(
                    ["xfconf-query", "-c", "xfwm4",
                     "-p", "/general/" + property_name],
                    text=True,
                    stderr=subprocess.DEVNULL
                ).strip()
            except (OSError, subprocess.CalledProcessError):
                return fallback

        theme = xfconf("theme", "Kali-Dark")
        layout = xfconf("button_layout", "O|HMC")

        theme_dir = Path("/usr/share/themes") / theme / "xfwm4"

        config = configparser.ConfigParser()
        settings = {}

        config_path = theme_dir / "themerc"

        if config_path.exists():
            for line in config_path.read_text().splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    settings[key.strip()] = value.strip()

        spacing = int(settings.get("button_spacing", 0))
        offset = int(settings.get("button_offset", 0))

        def image_width(name):
            path = theme_dir / (name + "-active.png")
            if path.exists():
                with open(path, "rb") as f:
                    header = f.read(24)
                if header[:8] == bytes([137, 80, 78, 71, 13, 10, 26, 10]):
                    return struct.unpack(">I", header[16:20])[0]
            return 20

        button_names = {
            "H": "hide",
            "M": "maximize",
            "C": "close",
            "S": "shade",
            "O": "menu",
        }

        # Client-side decorated windows do not use Xfwm4 buttons.
        if (
            info["top"] == 0
            and info["left"] == 0
            and info["right"] == 0
        ):
            frame_right = info["x"] + info["width"]
            frame_top = info["y"]

            return (
                frame_right - 65,
                frame_top,
                45,
                35
            )

        right_buttons = layout.split("|")[-1]

        right = info["x"] + info["width"] + info["right"]
        top = info["y"] - info["top"]

        cursor = right - offset

        for button in reversed(right_buttons):
            name = button_names.get(button)
            if not name:
                continue

            width = image_width(name)
            cursor -= width

            if button == "M":
                return (
                    int(cursor),
                    int(top),
                    int(width),
                    int(max(info["top"], width))
                )

            cursor -= spacing

        return None

    def inside(self, px, py, rect):
        x, y, w, h = rect
        return x <= px < x + w and y <= py < y + h

    def find_hovered_window(self, px, py):
        try:
            for window_id in reversed(self.window_list()):
                try:
                    window = self.display.create_resource_object(
                        "window", window_id
                    )

                    if window.get_attributes().map_state != X.IsViewable:
                        continue

                    parent = window.query_tree().parent
                    frame = (
                        window
                        if parent.id == self.root.id
                        else parent
                    )

                    geometry = frame.get_geometry()
                    position = self.root.translate_coords(
                        frame, 0, 0
                    )

                    fx = int(position.x)
                    fy = int(position.y)
                    fw = int(geometry.width)
                    fh = int(geometry.height)

                    if fx <= px < fx + fw and fy <= py < fy + fh:
                        return self.window_info(window_id)

                except (error.XError, ValueError, KeyError, TypeError):
                    continue

        except error.XError:
            pass

        return None

    def popup_running(self):
        return self.popup is not None and self.popup.poll() is None

    def open_popup(self, window_id, rect):
        if self.popup_running():
            return

        x, y, w, h = rect

        print("Maximize hover:", hex(window_id), rect, flush=True)

        self.popup = subprocess.Popen([
            sys.executable,
            str(Path(__file__).resolve().parent / "layoutku.py"),
            "--target", str(window_id),
            "--popup", str(x + w), str(y + h)
        ])

    def process_drag(self, px, py, pressed):
        if self.popup_running():
            if not pressed:
                self.drag = None
            self.was_pressed = pressed
            return True

        if pressed and not self.was_pressed:
            self.drag = None
            info = self.find_hovered_window(px, py)

            if info:
                fx = info["x"] - info["left"]
                fy = info["y"] - info["top"]
                fw = info["width"] + info["left"] + info["right"]

                titlebar_height = max(40, info["top"])

                valid = (
                    fx <= px < fx + fw
                    and info["y"] - titlebar_height - 45 <= py
                    < info["y"] + 12
                )



                if valid:
                    self.drag = {
                        "id": info["id"],
                        "start": (px, py),
                        "geometry": (
                            info["x"],
                            info["y"],
                            info["width"],
                            info["height"]
                        )
                    }

        if pressed and self.drag:
            sx, sy = self.drag["start"]
            if (abs(px - sx) + abs(py - sy) >= 75
                    and py <= 80 and not self.popup_running()):
                self.popup = subprocess.Popen([
                    sys.executable, str(Path(__file__).resolve().parent / "layoutku.py"),
                    "--target", str(self.drag["id"]),
                    "--popup", str(self.display.screen().width_in_pixels // 2 + 220),
                    "40", "--drag-mode"
                ])
                print("Interactive Top Snap:", hex(self.drag["id"]), flush=True)
                self.drag = None
                self.was_pressed = pressed
                return True

        if not pressed and self.was_pressed and self.drag:
            drag = self.drag
            self.drag = None
            self.was_pressed = False

            sx, sy = drag["start"]
            distance = abs(px - sx) + abs(py - sy)

            if distance < 40:
                return False

            try:
                current = self.window_info(drag["id"])
            except Exception:
                return False

            if not current:
                return False

            previous = drag["geometry"]
            moved = (
                abs(current["x"] - previous[0]) > 15
                or abs(current["y"] - previous[1]) > 15
            )

            if not moved:
                print(
                    "Drag detected without window movement:",
                    hex(drag["id"]),
                    flush=True
                )

            screen = self.display.screen()
            sw = screen.width_in_pixels

            edge = None

            if px <= 35:
                edge = "left"
            elif px >= sw - 35:
                edge = "right"


            if edge:
                args = [
                    sys.executable,
                    str(Path(__file__).resolve().parent / "layoutku.py"),
                    "--target",
                    str(drag["id"])
                ]

                if edge == "top":
                    args += [
                        "--popup",
                        str(sw // 2 + 220),
                        "40",
                        "--drag-mode"
                    ]
                else:
                    args += ["--edge", edge]

                self.popup = subprocess.Popen(args)

                print(
                    "Drag-to-Snap:",
                    edge,
                    hex(drag["id"]),
                    flush=True
                )

                self.reset()
                return True

        self.was_pressed = pressed
        return pressed

    def reset(self):
        self.hover_start = None
        self.hover_window = None
        self.triggered = False

    def hover_delay(self):
        import json
        try:
            path = Path(str(Path.home() / ".config/snaplayout/settings.json"))
            return float(json.loads(path.read_text()).get("hover_delay", 0.5))
        except (OSError, ValueError, TypeError):
            return 0.5

    def tick(self):
        try:
            if self.popup_running():
                self.reset()
                return True

            pointer = self.root.query_pointer()
            px, py = pointer.root_x, pointer.root_y
            pressed = bool(pointer.mask & X.Button1Mask)

            if self.process_drag(px, py, pressed):
                self.reset()
                return True

            info = self.find_hovered_window(px, py)

            if info is None:
                self.reset()
                return True

            rect = self.maximize_area(info)

            if self.inside(px, py, rect):
                if self.hover_window != info["id"]:
                    self.hover_window = info["id"]
                    self.hover_start = time.monotonic()
                    self.triggered = False

                if self.hover_start is None:
                    self.hover_start = time.monotonic()

                if (
                    time.monotonic() - self.hover_start >= self.hover_delay()
                    and not self.triggered
                ):
                    self.triggered = True
                    self.open_popup(info["id"], rect)
            else:
                self.reset()

        except (
            error.XError,
            subprocess.CalledProcessError,
            ValueError,
            KeyError
        ) as e:
            print("Error:", e, flush=True)
            self.reset()

        return True

    def run(self):
        print("Snap Layout hover enabled (0.5 seconds)", flush=True)

        while True:
            try:
                if self.popup_running():
                    self.reset()
                    time.sleep(POLL_INTERVAL)
                    continue

                pointer = self.root.query_pointer()
                px, py = pointer.root_x, pointer.root_y
                pressed = bool(pointer.mask & X.Button1Mask)

                if self.process_drag(px, py, pressed):
                    self.reset()
                    time.sleep(POLL_INTERVAL)
                    continue

                info = self.find_hovered_window(px, py)

                if info is None:
                    self.reset()
                    time.sleep(POLL_INTERVAL)
                    continue

                rect = self.maximize_area(info)


                if self.inside(px, py, rect):
                    if self.hover_window != info["id"]:
                        self.hover_window = info["id"]
                        self.hover_start = time.monotonic()
                        self.triggered = False

                    if self.hover_start is None:
                        self.hover_start = time.monotonic()

                    if (
                        time.monotonic() - self.hover_start >= self.hover_delay()
                        and not self.triggered
                    ):
                        self.triggered = True
                        self.open_popup(info["id"], rect)
                else:
                    self.reset()

            except (error.XError, subprocess.CalledProcessError, ValueError, KeyError) as e:
                print("Error:", e, flush=True)
                self.reset()

            time.sleep(POLL_INTERVAL)

class SnapTray:
    def __init__(self):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, GLib

        self.Gtk = Gtk
        self.GLib = GLib
        self.detector = HoverDetector()
        self.enabled = True

        self.icon = Gtk.StatusIcon.new_from_icon_name(
            "preferences-desktop-display"
        )
        self.icon.set_tooltip_text("XFCE Kali Linux Snap")
        self.icon.set_visible(True)
        self.icon.connect("popup-menu", self.show_menu)
        self.icon.connect("activate", self.show_menu_left)

        GLib.timeout_add(40, self.poll)

        print("XFCE Kali Linux Snap System Tray enabled.", flush=True)

    def poll(self):
        if self.enabled:
            return self.detector.tick()

        self.detector.reset()
        return True

    def toggle(self, *args):
        self.enabled = not self.enabled

        if not self.enabled:
            self.detector.reset()

        self.icon.set_tooltip_text(
            "XFCE Kali Linux Snap - " +
            ("Enabled" if self.enabled else "Disabled")
        )

        print(
            "Snap Layout:",
            "Enabled" if self.enabled else "Disabled",
            flush=True
        )

    def show_menu_left(self, icon):
        from gi.repository import Gtk
        self.show_menu(
            icon,
            1,
            Gtk.get_current_event_time()
        )

    def show_menu(self, icon, button, activate_time):
        Gtk = self.Gtk

        menu = Gtk.Menu()

        status = Gtk.CheckMenuItem(label="Enable Snap Layout")
        status.set_active(self.enabled)
        status.connect("toggled", self.on_status_changed)
        menu.append(status)

        menu.append(Gtk.SeparatorMenuItem())

        settings = Gtk.MenuItem(label="Settings")
        settings.connect("activate", self.open_settings)
        menu.append(settings)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self.quit)
        menu.append(quit_item)

        menu.show_all()
        menu.popup(
            None, None,
            Gtk.StatusIcon.position_menu,
            icon, button, activate_time
        )

    def on_status_changed(self, item):
        desired = item.get_active()
        if desired != self.enabled:
            self.toggle()

    def open_settings(self, *args):
        import json

        Gtk = self.Gtk
        config = Path(str(Path.home() / ".config/snaplayout/settings.json"))
        data = json.loads(config.read_text())

        dialog = Gtk.Dialog(
            title="XFCE Kali Linux Snap — Settings",
            flags=Gtk.DialogFlags.MODAL
        )
        dialog.set_default_size(440, 350)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save Settings", Gtk.ResponseType.OK)

        grid = Gtk.Grid()
        grid.set_row_spacing(18)
        grid.set_column_spacing(20)
        grid.set_border_width(24)

        dialog.get_content_area().add(grid)

        def add_label(text, row):
            label = Gtk.Label(label=text)
            label.set_xalign(0)
            grid.attach(label, 0, row, 1, 1)

        add_label("Hover Delay (seconds)", 0)
        hover = Gtk.SpinButton.new_with_range(0.2, 2.0, 0.1)
        hover.set_value(data["hover_delay"])
        grid.attach(hover, 1, 0, 1, 1)

        add_label("Animation Speed (ms)", 1)
        animation = Gtk.SpinButton.new_with_range(100, 500, 10)
        animation.set_value(data["animation_speed"])
        grid.attach(animation, 1, 1, 1, 1)

        add_label("Preview Color", 2)
        color = Gtk.ColorButton()
        from gi.repository import Gdk
        rgba = Gdk.RGBA()
        rgba.parse(data["preview_color"])
        color.set_rgba(rgba)
        grid.attach(color, 1, 2, 1, 1)

        add_label("Corner Radius (px)", 3)
        radius = Gtk.SpinButton.new_with_range(0, 30, 1)
        radius.set_value(data["corner_radius"])
        grid.attach(radius, 1, 3, 1, 1)

        enabled = Gtk.CheckButton(label="Enable Snap Layout")
        enabled.set_active(self.enabled)
        grid.attach(enabled, 0, 4, 2, 1)

        dialog.show_all()

        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            rgba = color.get_rgba()

            data.update({
                "enabled": enabled.get_active(),
                "hover_delay": round(hover.get_value(), 2),
                "animation_speed": animation.get_value_as_int(),
                "preview_color": "#{:02X}{:02X}{:02X}".format(
                    round(rgba.red * 255),
                    round(rgba.green * 255),
                    round(rgba.blue * 255)
                ),
                "corner_radius": radius.get_value_as_int()
            })

            config.write_text(json.dumps(data, indent=4) + "\n")

            if self.enabled != data["enabled"]:
                self.toggle()

            print("Settings saved:", data, flush=True)

        dialog.destroy()

    def quit(self, *args):
        if self.detector.popup_running():
            self.detector.popup.terminate()

        self.icon.set_visible(False)
        self.Gtk.main_quit()

    def run(self):
        self.Gtk.main()


if __name__ == "__main__":
    try:
        SnapTray().run()
    except KeyboardInterrupt:
        print("\\nSnap Layout stopped.")
