"""Flyers blueprint – printable registration guides for apoderados.

Provides six letter-size HTML flyers (3 for young parents, 3 for middle-aged
parents) showing the 4-step account-creation process with an embedded QR code
pointing to /register.
"""

import io
import base64

import qrcode
import qrcode.image.svg
from flask import Blueprint, abort, render_template

flyers_bp = Blueprint("flyers", __name__)

REGISTER_URL = "https://sabormirandiano.cl/register"

FLYERS = {
    # key: (template, audience_label)
    "joven-1": ("flyers/joven-1.html", "Jóvenes – Opción 1"),
    "joven-2": ("flyers/joven-2.html", "Jóvenes – Opción 2"),
    "joven-3": ("flyers/joven-3.html", "Jóvenes – Opción 3"),
    "adulto-1": ("flyers/adulto-1.html", "Adultos – Opción 1"),
    "adulto-2": ("flyers/adulto-2.html", "Adultos – Opción 2"),
    "adulto-3": ("flyers/adulto-3.html", "Adultos – Opción 3"),
}


def _qr_svg_data_uri(url: str) -> str:
    """Return an inline data-URI SVG QR code for *url*."""
    factory = qrcode.image.svg.SvgPathImage
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(image_factory=factory)
    buf = io.BytesIO()
    img.save(buf)
    svg_bytes = buf.getvalue()
    encoded = base64.b64encode(svg_bytes).decode()
    return f"data:image/svg+xml;base64,{encoded}"


@flyers_bp.route("/flyers/")
def index():
    """Gallery page listing all available flyers."""
    return render_template("flyers/index.html", flyers=FLYERS)


@flyers_bp.route("/flyers/<string:flyer_id>")
def flyer(flyer_id: str):
    """Render a single print-ready flyer."""
    if flyer_id not in FLYERS:
        abort(404)
    template, _ = FLYERS[flyer_id]
    qr_uri = _qr_svg_data_uri(REGISTER_URL)
    return render_template(template, qr_uri=qr_uri, register_url=REGISTER_URL)
