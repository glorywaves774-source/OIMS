"""Staff profile pictures: any phone or camera photo becomes a small, square JPEG made by the app.

The picture is decoded and drawn again, so nothing hidden in the original file is kept (location, camera
details or anything else), and it is turned the right way up first."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD = 8 * 1024 * 1024     # photos straight from a phone camera can be several MB
SIZE = 512
Image.MAX_IMAGE_PIXELS = 60_000_000   # refuse "decompression bomb" files


class PhotoError(ValueError):
    pass


def make_profile_photo(data):
    if not data:
        raise PhotoError("Choose a photo first.")
    if len(data) > MAX_UPLOAD:
        raise PhotoError("The photo must be 8 MB or smaller.")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ("JPEG", "PNG", "WEBP", "MPO", "HEIF", "HEIC", "GIF"):
            raise PhotoError("Use a JPEG, PNG or WebP photo.")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise PhotoError("This file is not a photo the system can read. Use a JPEG, PNG or WebP photo.") from exc
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img = ImageOps.fit(img, (SIZE, SIZE), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=86, optimize=True, progressive=True)
    return out.getvalue()
