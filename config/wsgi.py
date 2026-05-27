"""
Lab Assistant - WSGI Configuration
Used by: python manage.py runserver
For production with WebSocket: use daphne + config/asgi.py instead.
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
