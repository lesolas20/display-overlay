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
