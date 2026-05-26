# display-overlay
A program for displaying overlays on screen in Wayland compositors.
It can be used to display panels, notifications and other things.

## Features
- Display text from a file or output of a script (supports [Pango Markup](https://docs.gtk.org/Pango/pango_markup))
- Apply styles to the displayed panel using [GTK CSS](https://docs.gtk.org/gtk3/css-overview)
- Display the overlay on a specific screen or on the currenly focused screen
- Set position and margins of the overlay
- Display the overlay on a specific layer (e.g. above all windows or in the background)
- Change the layer the overlay is displayed on while it is running
- Show / hide the overlay when it is already running

## Dependencies
- [GTK Layer Shell (GTK3)](https://github.com/wmww/gtk-layer-shell)
- [uv](https://docs.astral.sh/uv) or [Python PyGObject package](https://pypi.org/project/PyGObject)

## Installation
### Debian
1. Install GTK Layer Shell (GTK3 version):
```bash
sudo apt install libgtk-layer-shell-dev
```
2. Install either uv (see [uv documentation](https://docs.astral.sh/uv/#installation)) (recommended) or PyGObject:
```bash
pip install pygobject --break-system-packages
```
3. Clone this repository:
```bash
git clone https://github.com/lesolas20/display-overlay
```

## Usage
If PyGObject is installed as a system-wide Python package, use your system's Python to run this program:
```bash
python3 display-overlay.py --help
```
If you are getting `RuntimeError: PyGObject is not installed`, either install PyGObject as a system-wide Python package (not recommended, as this has the risk of breaking your Python installation or OS) or install uv (recommended).
If uv is installed, use uv to run this program:
```bash
uv run display-overlay.py --help
```

## Examples
### Spawn a clock overlay that can be shown at any time:
```bash
#!/usr/bin/env bash

echo $$ >/tmp/clock-overlay.pid

exec \
    uv run ~/Development/display-overlay/display-overlay.py \
    --script ~/.config/clock-overlay/clock \
    --css ~/.config/clock-overlay/clock.css \
    --alignment bottom --margin_bottom 32 \
    --layer 3 --refresh 200 \
    --animation_length 150 --framerate 30 \
    --invisible
```

~/.config/clock-overlay/clock
```bash
#!/usr/bin/env bash

echo -n '<span>'
date '+ %H:%M:%S ' | tr -d '\n'
echo -en '\n'
date '+%Y-%m-%d' | tr -d '\n'
echo '</span>'
```

~/.config/clock-overlay/clock.css
```css
* {
  border-radius: 16px;
  background-color: transparent;
}

#box-inner {
  padding: 8px;
  background-color: #444444;
  color: #4090fe;
  font: 48pt "SauceCodePro Nerd Font Mono";
  border: 4px solid #333333;
}
```

Show/hide the overlay:
```bash
kill -s SIGUSR2 $(cat /tmp/clock-overlay.pid)
```

If you bind the command for toggling visibility to a keybind, you can get a clock like this:

https://github.com/user-attachments/assets/fae494f6-19f1-42ce-83df-178f798ceea0
