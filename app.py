from dotenv import load_dotenv

from app import create_app
import os

load_dotenv()
app = create_app()
celery_app = app.extensions["celery"]
