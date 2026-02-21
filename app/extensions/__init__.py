from flask_babel import Babel
from flask_mailman import Mail
from flask_wtf import CSRFProtect

from flask_merchants import FlaskMerchants

babel = Babel()
mail = Mail()
flask_merchants = FlaskMerchants()
csrf = CSRFProtect()
