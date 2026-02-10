from flask_babel import Babel
from flask_mailman import Mail
from flask_wtf import CSRFProtect

from flask_merchants.core import FlaskMerchantsExtension

babel = Babel()
mail = Mail()
flask_merchants = FlaskMerchantsExtension()
csrf = CSRFProtect()
