# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for ImageSorter.exe; build_windows.bat runs it. It's a spec file instead of
# command-line flags so it can leave out the parts of OpenCV and onnxruntime the app never loads.
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], collect_submodules("winrt")
d, b, h = collect_all("rapidocr")  # its models and settings files
datas += d
binaries += b
hiddenimports += h

# RapidOCR can also run on these engines, but it uses onnxruntime here. Leave them out even if
# they happen to be installed (PyTorch alone is gigabytes).
excludes = ["torch", "paddle", "openvino", "tensorrt", "MNN"]
excludes += [f"rapidocr.inference_engine.{e}" for e in ("pytorch", "paddle", "openvino", "tensorrt", "mnn")]


def needed(dest):
    name = os.path.basename(dest).lower()
    # OpenCV's video-file plugin (31 MB), only loaded to open videos.
    if name.startswith("opencv_videoio_ffmpeg"):
        return False
    # A second copy of the onnxruntime engine (19 MB) for C programs. Python uses
    # onnxruntime_pybind11_state.pyd, which has the engine built in and doesn't load this.
    if name == "onnxruntime.dll":
        return False
    return True


a = Analysis(
    ["image_sorter_app.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=excludes,
)
a.binaries = [x for x in a.binaries if needed(x[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ImageSorter",
    console=False,
    icon=["icon.ico"],
)
