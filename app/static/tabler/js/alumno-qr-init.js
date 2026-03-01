document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.qr-code-container').forEach(function (el) {
        var tag = el.getAttribute('data-tag');
        if (tag && typeof QRCode !== 'undefined') {
            new QRCode(el, {
                text: tag,
                width: 80,
                height: 80,
                colorDark: '#000000',
                colorLight: '#ffffff',
                correctLevel: QRCode.CorrectLevel.M
            });
        }
    });
});
