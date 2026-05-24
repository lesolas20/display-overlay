import os
import sys
import json
import shlex
import signal
import subprocess
from enum import Enum
from time import sleep
from typing import Any
from pathlib import Path
from argparse import Namespace, ArgumentParser

import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("GtkLayerShell", "0.1")
except ValueError:
    raise RuntimeError("GTK Layer Shell is not installed") from None

from gi.repository import (  # noqa: E402, I001
    Gtk,
    Gdk,
    GLib,
    GdkPixbuf,
    GtkLayerShell,  # type: ignore
)


class AnimationState(Enum):
    NONE = 1
    FADE_IN = 2
    FADE_OUT = 3


class EpsilonComparable:
    def __init__(self, value: float, epsilon: float) -> None:
        if epsilon <= 0:
            raise ValueError("epsilon must be greater than zero")

        self.value = value
        self.epsilon = epsilon

    def __str__(self) -> str:
        return f"EpsilonComparable({self.value}, {self.epsilon})"

    def __hash__(self) -> int:
        return hash((self.value, self.epsilon))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, (int, float)):
            return False

        return abs(self.value - other) < self.epsilon

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, (int, float)):
            raise TypeError

        return (other - self.value) > self.epsilon

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, (int, float)):
            raise TypeError

        return (self.value - other) > self.epsilon

    def __le__(self, other: Any) -> bool:
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        return NotImplemented


class GdkDisplayError(Exception):
    pass


class GdkScreenError(Exception):
    pass


class AlignedImage(Gtk.Image):
    def __init__(self, path: str, align: str, width: int, height: int):
        super().__init__()

        self.align = align

        try:
            self.set_from_pixbuf(
                GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    path,
                    width,
                    height,
                    False,
                ),
            )

        except Exception as e:
            sys.stderr.write(f"{e}\n")
            self.set_from_icon_name("image-missing", Gtk.IconSize.INVALID)


def get_outputs():
    outputs = json.loads(subprocess.check_output(("wlr-randr", "--json")))  # noqa: S607
    display = Gdk.Display.get_default()

    if display is None:
        raise GdkDisplayError("Failed to get the default display")

    return {
        outputs[i]["name"]: display.get_monitor(i)
        for i in range(display.get_n_monitors())
    }


def parse_output(text: str, justify: str) -> list[Gtk.Label | AlignedImage]:
    lines = text.splitlines()

    block: list[str] = []
    blocks: list[str] = []

    # Parse text lines into text blocks and image blocks
    for line in lines:
        if not line.startswith("#img"):
            block.append(line)
            continue

        if block:
            # End and flush the current block
            blocks.append("\n".join(block))
            block.clear()

        blocks.append(line)

    if block:
        # End and flush the last block
        blocks.append("\n".join(block))
        block.clear()

    # Parse text blocks and image blocks into GTK labels and GTL images
    widgets: list[Gtk.Label | AlignedImage] = []

    del block

    block: str
    for block in blocks:
        if block.startswith("#img"):
            widgets.append(parse_image(block))

        else:
            label = Gtk.Label()
            label.set_markup(block)
            set_justify(label, justify)
            widgets.append(label)

    return widgets


def set_justify(label: Gtk.Label, justify: str) -> None:
    match justify:
        case "left":
            label.set_justify(Gtk.Justification.LEFT)
        case "center":
            label.set_justify(Gtk.Justification.CENTER)
        case "right":
            label.set_justify(Gtk.Justification.RIGHT)


def parse_image(string) -> AlignedImage:
    """Parse an image string into a GTK Image with an `align` field."""

    path: str = ""
    align: str = ""
    width: int = 0
    height: int = 0

    for token in shlex.split(string):
        match token.split("="):
            case ["path", value]:
                path = value
            case ["align", value]:
                align = value
            case ["width", value]:
                width = int(value)
            case ["height", value]:
                height = int(value)

    return AlignedImage(path, align, width, height)


def glib_timeout_add_forever(interval: int, function, *user_data: Any) -> int:
    def wrapper(user_data):
        function(*user_data)
        return True

    return GLib.timeout_add(interval, wrapper, user_data)


def animation_linear(time: float) -> float:
    """Return `opacity` corresponding to given `time` using a linear
    function.
    """
    return time


def animation_ease_in_out_cubic(time: float) -> float:
    """Return `opacity` corresponding to given `time` using a cubic
    function.
    """
    if time < 0.5:  # noqa: PLR2004
        return 4 * time**3
    return 1 - (4 * (1 - time) ** 3)


class App:
    def __init__(self) -> None:
        self.script_path: Path | None = None
        self.text_path: Path | None = None

        self.pid_file: Path = Path("/tmp/display-overlay.pid")  # noqa: S108

        self.parser = self.create_argument_parser()
        self.args: Namespace = self.parser.parse_args()

        self.layer: int = 1
        self.inner_box_width: int = 0

        if self.args.single_instance:
            self.enforce_single_instance()

        self.build_gui()

        self.set_monitor()

        if self.args.css:
            self.load_css()

        self.init_source()

        self.apply_margins()
        self.apply_vertical_position()
        self.apply_horizontal_position()

        self.init_animation()

        self.window.connect("destroy", Gtk.main_quit)

        if (self.args.refresh > 0) and self.script_path:
            glib_timeout_add_forever(
                self.args.refresh,
                self.build_overlay_from_script,
            )

        self.mount_signals()

        Gtk.main()

    def init_source(self) -> None:
        if self.args.script:
            self.script_path = Path(os.path.realpath(self.args.script))

            if self.args.refresh:
                print(
                    f"Using a script: {self.script_path}"
                    f", refresh rate {self.args.refresh} ms",
                )
            else:
                print(f"Using a script: {self.script_path}, no refresh")

            self.build_overlay_from_script()
            return

        if self.args.text:
            self.text_path = Path(os.path.realpath(self.args.text))

            print(f"Using a text file: {self.text_path}")

            self.build_overlay_from_text()
            return

        sys.stderr.write("ERROR: Neither script nor text file specified\n")
        self.parser.print_help(sys.stderr)
        sys.exit(1)

    def init_animation(self) -> None:
        # Prepare animation and window state
        self.animation_state: AnimationState = AnimationState.NONE

        is_animated: bool = self.args.animation_length > 0
        is_visible: bool = not self.args.invisible

        match [is_animated, is_visible]:
            case [False, False]:
                self.window.hide()
            case [False, True]:
                self.window.show_all()
            case [True, False]:
                self.animation_time = 0
                Gtk.Widget.set_opacity(self.window, 0)
                self.window.hide()
            case [True, True]:
                self.animation_time = 1
                Gtk.Widget.set_opacity(self.window, 1)
                self.window.show_all()

        # Set the animation function
        match self.args.animation_function:
            case "linear":
                self.animation_function = animation_linear
            case "cubic":
                self.animation_function = animation_ease_in_out_cubic
            case _:
                self.animation_function = animation_linear

        if self.args.animation_length > 0:
            # Calculate animation frame time in milliseconds
            self.frame_time: int = int(1000 / self.args.framerate)
            # Create the animation loop
            glib_timeout_add_forever(
                self.frame_time,
                self.animation_update,
                self.animation_function,
            )

    def create_argument_parser(self) -> ArgumentParser:
        """Create an argument parser with arguments available in the
        program and return the argument parser.
        """

        parser = ArgumentParser()

        source_group = parser.add_mutually_exclusive_group(required=True)

        source_group.add_argument(
            "-s",
            "--script",
            type=str,
            default="",
            help="path to the script the output of which to display",
        )
        source_group.add_argument(
            "-t",
            "--text",
            type=str,
            default="",
            help="path to the text file to display",
        )

        parser.add_argument(
            "-c",
            "--css",
            type=str,
            default="",
            help="path to the CSS file to apply the styling",
        )
        parser.add_argument(
            "-o",
            "--output",
            type=str,
            default="",
            help="output to place the window on, e.g. 'eDP-1'",
        )
        parser.add_argument(
            "-p",
            "--position",
            type=str,
            default="center",
            help=(
                "horizontal position on the display"
                " ('left' / 'center' / 'right'); default 'center'"
            ),
        )
        parser.add_argument(
            "-a",
            "--alignment",
            type=str,
            default="center",
            help=(
                "vertical position on the display"
                " ('top' / 'center' / 'bottom'); default 'center'"
            ),
        )
        parser.add_argument(
            "-j",
            "--justify",
            type=str,
            default="left",
            help=(
                "text justification in the overlay"
                " ('right' / 'center' / 'left'); default 'left'"
            ),
        )
        parser.add_argument(
            "-mt",
            "--margin_top",
            type=int,
            default=0,
            help="top margin",
        )
        parser.add_argument(
            "-mb",
            "--margin_bottom",
            type=int,
            default=0,
            help="bottom margin",
        )
        parser.add_argument(
            "-ml",
            "--margin_left",
            type=int,
            default=0,
            help="left margin",
        )
        parser.add_argument(
            "-mr",
            "--margin_right",
            type=int,
            default=0,
            help="right margin",
        )
        parser.add_argument(
            "-l",
            "--layer",
            type=int,
            default=1,
            help=(
                "layer for the overlay to be on"
                " (1 for bottom / 2 for top / 3 for overlay); default 1"
            ),
        )
        parser.add_argument(
            "-i",
            "--invisible",
            default=False,
            action="store_true",
            help="make the overlay invisible on launch",
        )
        parser.add_argument(
            "-si",
            "--single_instance",
            action="store_true",
            help="allow only a single instance of the program to be running",
        )
        parser.add_argument(
            "-sl",
            "--sig_layer",
            type=int,
            default=10,
            help="signal number for switching layer; default: 10",
        )
        parser.add_argument(
            "-sv",
            "--sig_visibility",
            type=int,
            default=12,
            help="signal number for toggling visibility; default: 12",
        )
        parser.add_argument(
            "-sq",
            "--sig_quit",
            type=int,
            default=2,
            help="signal number to quit the program; default: 2",
        )
        parser.add_argument(
            "-sr",
            "--sig_refresh",
            type=int,
            default=8,
            help="signal number to refresh the script; default: 8",
        )
        parser.add_argument(
            "-srd",
            "--sig_refresh_delay",
            type=int,
            default=0,
            help="delay before acting on refresh signal in seconds; default: 0",  # noqa: E501
        )
        parser.add_argument(
            "-r",
            "--refresh",
            type=int,
            default=0,
            help="refresh time in milliseconds; default: 0 (do not refresh)",
        )
        parser.add_argument(
            "-f",
            "--framerate",
            type=int,
            default=60,
            help=(
                "toggle visibility animation framerate in frames per second;"
                " default: 60"
            ),
        )
        parser.add_argument(
            "-al",
            "--animation_length",
            type=int,
            default=0,
            help=(
                "toggle visibility animation length in millisecondsl"
                " default: 0 (do not animate)"
            ),
        )
        parser.add_argument(
            "-af",
            "--animation_function",
            type=str,
            default="linear",
            help=(
                "toggle visibility animation easing function"
                " ('linear' / 'cubic'); default: linear"
            ),
        )

        return parser

    def signal_handler(self, sig):
        """Handle signals the program recieves."""

        match sig:
            case 2:
                print("Terminated with SIGINT")
                Gtk.main_quit()

            case 15:
                print("Terminated with SIGTERM")
                Gtk.main_quit()

            case self.args.sig_quit:
                print(f"Terminated with a custom signal {sig}")
                Gtk.main_quit()

            case self.args.sig_layer:
                print(f"Changed layer with a custom signal {sig}")
                GtkLayerShell.set_layer(self.window, self.layer)

            case self.args.sig_refresh:
                sleep(self.args.sig_refresh_delay)
                self.build_overlay_from_script()

            case self.args.sig_visibility:
                self.handle_visibility_signal()

    def handle_visibility_signal(self) -> None:
        is_animated: bool = self.args.animation_length > 0
        is_visible: bool = self.window.is_visible()
        anim_state: AnimationState = self.animation_state

        match [is_animated, is_visible, anim_state]:
            case [False, False, _]:
                self.window.show_all()
            case [False, True, _]:
                self.window.hide()

            case [True, False, AnimationState.NONE]:
                self.fade_in()
            case [True, True, AnimationState.NONE]:
                self.fade_out()

            case [True, _, AnimationState.FADE_OUT]:
                self.fade_in()
            case [True, _, AnimationState.FADE_IN]:
                self.fade_out()

    def fade_in(self) -> None:
        self.animation_state = AnimationState.FADE_IN

    def fade_out(self) -> None:
        self.animation_state = AnimationState.FADE_OUT

    def animation_update(self, animation_function) -> None:  # noqa: C901
        def clamp(value: float, min_value: float, max_value: float) -> float:
            return min(max(value, min_value), max_value)

        match self.animation_state:
            case AnimationState.NONE:
                return
            case AnimationState.FADE_IN:
                delta_t_direction = +1
            case AnimationState.FADE_OUT:
                delta_t_direction = -1

        opacity: float = Gtk.Widget.get_opacity(self.window)
        c_opacity = EpsilonComparable(opacity, 0.000001)

        # Recalculate animation time
        delta_t: float = self.frame_time / self.args.animation_length
        self.animation_time = clamp(
            self.animation_time + (delta_t_direction * delta_t),
            0,
            1,
        )

        # Calculate the next opacity value
        next_opacity: float = animation_function(self.animation_time)
        c_next_opacity = EpsilonComparable(next_opacity, 0.000001)

        # Start fade-in animation
        if (c_opacity == 0) and (c_next_opacity > 0):
            self.window.show_all()
            Gtk.Widget.set_opacity(self.window, next_opacity)

        # End fade-in animation
        elif (c_opacity < 1) and (c_next_opacity == 1):
            Gtk.Widget.set_opacity(self.window, next_opacity)
            self.animation_state = AnimationState.NONE

        # Start fade-out animation
        elif (c_opacity == 1) and (c_next_opacity < 1):
            Gtk.Widget.set_opacity(self.window, next_opacity)

        # End fade-out animation
        elif (c_opacity > 0) and (c_next_opacity == 0):
            Gtk.Widget.set_opacity(self.window, next_opacity)
            self.window.hide()
            self.animation_state = AnimationState.NONE

        # End animation if stuck on the 0% opacity boundary
        elif (c_opacity == 0) and (c_next_opacity == 0):
            self.window.hide()
            self.animation_state = AnimationState.NONE

        # End animation if stuck on the 100% opacity boundary
        elif (c_opacity == 1) and (c_next_opacity == 1):
            self.animation_state = AnimationState.NONE

        # Run a normal animation frame
        else:
            Gtk.Widget.set_opacity(self.window, next_opacity)

    def enforce_single_instance(self) -> None:
        """Try to kill an already running instances of the program."""

        pid: int | None = None

        if self.pid_file.is_file():
            try:
                with self.pid_file.open() as file:
                    file_contents = file.read()

                pid = int(file_contents)
                os.kill(pid, signal.SIGINT)

            except Exception:
                print(f"Failed to kill a possibly running instance, PID {pid}")

            else:
                print(f"A running instance killed, PID {pid}")

        with self.pid_file.open("w") as file:
            file.write(str(os.getpid()))

    def build_gui(self) -> None:
        """Create the base of the program's GUI."""

        # Create a window
        self.window: Gtk.Window = Gtk.Window()
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_layer(self.window, self.args.layer)
        GtkLayerShell.set_exclusive_zone(self.window, 0)

        # Add containers
        self.outer_box: Gtk.Box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=0,
            name="box-outer",
        )
        self.window.add(self.outer_box)

        self.inner_box: Gtk.Box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=0,
            name="box-inner",
        )

        self.v_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.inner_box.pack_start(self.v_box, False, False, 0)

    def apply_margins(self) -> None:
        """Apply margins to the window."""

        GtkLayerShell.set_margin(
            self.window,
            GtkLayerShell.Edge.TOP,
            self.args.margin_top,
        )
        GtkLayerShell.set_margin(
            self.window,
            GtkLayerShell.Edge.BOTTOM,
            self.args.margin_bottom,
        )
        GtkLayerShell.set_margin(
            self.window,
            GtkLayerShell.Edge.LEFT,
            self.args.margin_left,
        )
        GtkLayerShell.set_margin(
            self.window,
            GtkLayerShell.Edge.RIGHT,
            self.args.margin_right,
        )

    def apply_horizontal_position(self) -> None:
        """Apply horizontal positioning to the window."""

        match self.args.position:
            case "left":
                GtkLayerShell.set_anchor(
                    self.window,
                    GtkLayerShell.Edge.LEFT,
                    True,
                )

            case "right":
                GtkLayerShell.set_anchor(
                    self.window,
                    GtkLayerShell.Edge.RIGHT,
                    True,
                )

            case "center":
                pass

    def apply_vertical_position(self) -> None:
        """Apply vertical positioning to the window."""

        match self.args.alignment:
            case "top":
                GtkLayerShell.set_anchor(
                    self.window,
                    GtkLayerShell.Edge.TOP,
                    True,
                )
                self.outer_box.pack_start(self.inner_box, False, True, 0)

            case "bottom":
                GtkLayerShell.set_anchor(
                    self.window,
                    GtkLayerShell.Edge.BOTTOM,
                    True,
                )
                self.outer_box.pack_end(self.inner_box, False, True, 0)

            case "center":
                self.outer_box.pack_start(self.inner_box, True, False, 0)

    def set_monitor(self) -> None:
        """Select the monitor on which the overlay is displayed."""

        if self.args.output:
            outputs = get_outputs()
            try:
                monitor = outputs[self.args.output]
                GtkLayerShell.set_monitor(self.window, monitor)
            except KeyError:
                print(f"No such output: {self.args.output}")
                return

        screen = Gdk.Screen.get_default()

        if screen is None:
            raise GdkScreenError("Failed to get the default screen")

        self.css_provider = Gtk.CssProvider()
        style_context = Gtk.StyleContext()
        style_context.add_provider_for_screen(
            screen,
            self.css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def load_css(self) -> None:
        """Load CSS from the given file. If failed, don't apply custom
        styling."""

        css = Path(os.path.realpath(self.args.css))

        if css.is_file():
            self.css_provider.load_from_path(str(css))
            print(f"Using style: {css}")

        else:
            sys.stderr.write(
                f"ERROR: {css} file not found, using default GTK styling\n",
            )

    def mount_signals(self) -> None:
        """Route all signals to the programs's signal handler."""

        catchable = set(signal.Signals) - {signal.SIGKILL, signal.SIGSTOP}
        for sig in catchable:
            signal.signal(sig, lambda sig, _: self.signal_handler(sig))

    def build_overlay_from_text(self) -> None:
        assert self.text_path is not None  # noqa: S101

        try:
            with self.text_path.open() as file:
                output = file.read()
        except Exception as e:
            sys.stderr.write(f"{e}\n")

        content = parse_output(output, self.args.justify)

        for item in content:
            h_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            self.v_box.pack_start(h_box, False, False, 0)

            if not isinstance(item, AlignedImage):
                h_box.pack_start(item, True, True, 0)
                continue

            match item.align:
                case "end":
                    h_box.pack_end(item, False, False, 0)
                case "start":
                    h_box.pack_start(item, False, False, 0)
                case "center":
                    h_box.pack_start(item, True, True, 0)
                case _:
                    h_box.pack_start(item, True, True, 0)

    def build_overlay_from_script(self) -> None:
        assert self.script_path is not None  # noqa: S101

        for item in self.v_box.get_children():
            item.destroy()
        try:
            print(
                "Running build_overlay_from_script with script"
                f" {self.script_path}",
            )
            output = subprocess.check_output(self.script_path)  # noqa: S603
            output = output.decode("utf-8")[:-1]
        except Exception as e:
            sys.stderr.write(f"{e}\n")

        assert isinstance(output, str)  # noqa: S101
        content = parse_output(output, self.args.justify)

        for item in content:
            h_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            self.v_box.pack_start(h_box, False, False, 0)

            if not isinstance(item, AlignedImage):
                h_box.pack_start(item, True, True, 0)
                continue

            match item.align:
                case "end":
                    h_box.pack_end(item, False, False, 0)
                case "start":
                    h_box.pack_start(item, False, False, 0)
                case "center":
                    h_box.pack_start(item, True, True, 0)
                case _:
                    h_box.pack_start(item, True, True, 0)

        self.v_box.show_all()


if __name__ == "__main__":
    app = App()
