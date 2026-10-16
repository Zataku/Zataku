"""Read the store number from a photo of a store label like "MCD7958DT" or "MCD7958DEL".

Uses the text recognition built into the OS, so there's nothing extra to install
beyond the Python packages in requirements.txt:
    macOS:   Apple Vision      (pyobjc-framework-Vision, pyobjc-framework-Quartz)
    Windows: Windows.Media.Ocr (winrt-* packages)

    store_number(path) -> "7958", or None if no label could be read.
"""
import re
import sys

# MCD <digits> DT|DEL. OCR sometimes reads digits as look-alike letters and adds spaces,
# so the number part allows O/I/L/S/B/Z and spaces, then gets cleaned up.
LABEL_PATTERN = re.compile(r"M\s*C\s*D\s*([0-9OQILSBZ ]{2,8}?)\s*(D\s*E\s*L|D\s*T)", re.IGNORECASE)
LOOKALIKES = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", " ": None})
# Fallbacks for when the label itself can't be read (Windows OCR misses its heavy bold font):
#   the ATP admin screen's device name, "DBLC29084DT" or "DBLC29084DEL"
#   the scale screen's "OuiCheck Cloud (n°29084)", where OCR usually reads "°" as "0"
SCREEN_PATTERNS = [
    re.compile(r"D\s*B\s*L\s*C\s*([0-9OQISBZ]{3,6}?)\s*(D\s*E\s*L|D\s*T)", re.IGNORECASE),
    re.compile(r"Cloud\s*\(\s*n\s*[°º0oO]?\s*([0-9]{3,6})\s*\)", re.IGNORECASE),
]


def find_store(lines):
    """Return the store number from OCR'd lines, or None."""
    # The label wins, then the screens. Check each line alone, then all text
    # joined, in case the text was split.
    for pattern in [LABEL_PATTERN] + SCREEN_PATTERNS:
        for text in lines + [" ".join(lines)]:
            for match in pattern.finditer(text):
                digits = match.group(1).upper().translate(LOOKALIKES)
                if len(digits) >= 3 and digits.isdigit():
                    return digits
    return None


if sys.platform == "darwin":
    import Quartz
    import Vision
    from Foundation import NSURL

    # EXIF orientation values: up, down (180°), left, right
    ROTATIONS = [1, 3, 8, 6]

    def _recognize_lines(image, orientation):
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(False)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_orientation_options_(
            image, orientation, None
        )
        handler.performRequests_error_([request], None)
        lines = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates:
                lines.append(str(candidates[0].string()))
        return lines

    def store_number(path):
        source = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(path)), None)
        if source is None:
            return None
        image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
        if image is None:
            return None
        props = Quartz.CGImageSourceCopyPropertiesAtIndex(source, 0, None) or {}
        exif = int(props.get(Quartz.kCGImagePropertyOrientation, 1))

        # Labels can be photographed sideways or upside down, so try every rotation.
        for orientation in dict.fromkeys([exif] + ROTATIONS):
            store = find_store(_recognize_lines(image, orientation))
            if store:
                return store
        return None

elif sys.platform == "win32":
    import asyncio
    import threading

    _thread = threading.local()

    def _winrt():
        """Load the Windows OCR modules on the reading thread, not the app's main thread.

        Windows text recognition needs its thread in COM's multi-threaded mode, which
        would break Tk's Browse… folder picker if it were done on the main thread.
        """
        if not getattr(_thread, "ready", False):
            from winrt.runtime import ApartmentType, init_apartment
            try:
                init_apartment(ApartmentType.MULTI_THREADED)
            except OSError:
                pass  # this thread was already set up
            _thread.ready = True
        import winrt.windows.globalization as globalization
        import winrt.windows.graphics.imaging as imaging
        import winrt.windows.media.ocr as ocr
        import winrt.windows.storage as storage
        return globalization, imaging, ocr, storage

    async def _store_number(path):
        globalization, imaging, ocr, storage = _winrt()
        engine = (ocr.OcrEngine.try_create_from_user_profile_languages()
                  or ocr.OcrEngine.try_create_from_language(globalization.Language("en-US")))
        if engine is None:
            raise RuntimeError("Windows text recognition isn't available (no OCR language installed).")
        file = await storage.StorageFile.get_file_from_path_async(str(path))
        stream = await file.open_async(storage.FileAccessMode.READ)
        decoder = await imaging.BitmapDecoder.create_async(stream)

        # Windows OCR rejects images bigger than max_image_dimension, so shrink phone photos.
        w, h = decoder.pixel_width, decoder.pixel_height
        scale = min(1.0, ocr.OcrEngine.max_image_dimension / max(w, h))
        # EXIF is ignored and every rotation tried instead, since labels can be
        # photographed sideways or upside down anyway.
        rotations = [imaging.BitmapRotation.NONE, imaging.BitmapRotation.CLOCKWISE180_DEGREES,
                     imaging.BitmapRotation.CLOCKWISE90_DEGREES, imaging.BitmapRotation.CLOCKWISE270_DEGREES]
        for rotation in rotations:
            transform = imaging.BitmapTransform()
            transform.scaled_width = int(w * scale)
            transform.scaled_height = int(h * scale)
            transform.interpolation_mode = imaging.BitmapInterpolationMode.FANT
            transform.rotation = rotation
            bitmap = await decoder.get_software_bitmap_transformed_async(
                imaging.BitmapPixelFormat.BGRA8, imaging.BitmapAlphaMode.PREMULTIPLIED, transform,
                imaging.ExifOrientationMode.IGNORE_EXIF_ORIENTATION,
                imaging.ColorManagementMode.DO_NOT_COLOR_MANAGE)
            result = await engine.recognize_async(bitmap)
            store = find_store([line.text for line in result.lines])
            if store:
                return store
        return None

    def store_number(path):
        try:
            return asyncio.run(_store_number(path))
        except ImportError as e:
            raise RuntimeError(f"Windows OCR packages are missing ({e}). Run: pip install -r requirements.txt")
        except OSError:
            return None  # a format Windows can't decode, e.g. HEIC without the HEIF extension

else:
    def store_number(path):
        raise RuntimeError("Reading store labels needs macOS or Windows.")
