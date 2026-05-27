"""Chat App URL routing - serves the frontend."""
from django.urls import path
from apps.chat import frontend_views

urlpatterns = [
    path("", frontend_views.index, name="index"),
    path("login/", frontend_views.login_view, name="login"),
    path("logout/", frontend_views.logout_view, name="logout"),
]
