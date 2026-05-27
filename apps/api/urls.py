"""API URL Configuration"""

from django.urls import path
from apps.api import views

urlpatterns = [
    # Chat
    path("chat/",                views.ChatView.as_view(),             name="chat"),
    path("sessions/",            views.SessionListView.as_view(),       name="sessions"),
    path("sessions/delete-all/", views.DeleteAllSessionsView.as_view(), name="sessions-delete-all"),
    path("sessions/<uuid:session_id>/delete/", views.DeleteSessionView.as_view(), name="session-delete"),
    path("history/<uuid:session_id>/", views.HistoryView.as_view(),    name="history"),

    # Documents / Knowledge Base
    path("documents/",           views.DocumentListView.as_view(),      name="document-list"),
    path("documents/upload/",    views.DocumentUploadView.as_view(),    name="document-upload"),
    path("sources/",             views.SourcesView.as_view(),           name="sources"),

    # Feedback
    path("feedback/",            views.FeedbackView.as_view(),          name="feedback"),

    # System
    path("health/",              views.HealthView.as_view(),            name="health"),
]