from django.urls import path

from .views import (
    ChatSessionDetailView,
    ChatSessionListCreateView,
    ChatSessionMessagesView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
    UserDetailView,
    UserListCreateView,
)

urlpatterns = [
    path("auth/register", RegisterView.as_view(), name="auth-register"),
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("auth/me", MeView.as_view(), name="auth-me"),
    path("users", UserListCreateView.as_view(), name="users-list-create"),
    path("users/<int:pk>", UserDetailView.as_view(), name="users-detail"),
    path("chat/sessions", ChatSessionListCreateView.as_view(), name="chat-sessions"),
    path(
        "chat/sessions/<int:pk>",
        ChatSessionDetailView.as_view(),
        name="chat-session-detail",
    ),
    path(
        "chat/sessions/<int:session_id>/messages",
        ChatSessionMessagesView.as_view(),
        name="chat-session-messages",
    ),
]
