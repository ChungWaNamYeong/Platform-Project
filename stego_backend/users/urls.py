from django.urls import path

from .views import (
    ExperimentRecordDetailView,
    ExperimentRecordBulkDeleteView,
    ExperimentRecordExportView,
    ExperimentRecordListCreateView,
    SandboxAdminRunsView,
    SandboxAdminMetricsView,
    SandboxStartView,
    SandboxStatusView,
    SandboxStopView,
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
    path("labs/sandbox/start", SandboxStartView.as_view(), name="sandbox-start"),
    path("labs/sandbox/stop", SandboxStopView.as_view(), name="sandbox-stop"),
    path("labs/sandbox/status", SandboxStatusView.as_view(), name="sandbox-status"),
    path("labs/records", ExperimentRecordListCreateView.as_view(), name="experiment-records"),
    path(
        "labs/records/bulk-delete",
        ExperimentRecordBulkDeleteView.as_view(),
        name="experiment-record-bulk-delete",
    ),
    path(
        "labs/records/<int:pk>",
        ExperimentRecordDetailView.as_view(),
        name="experiment-record-detail",
    ),
    path(
        "labs/records/export",
        ExperimentRecordExportView.as_view(),
        name="experiment-record-export",
    ),
    path(
        "labs/sandbox/admin/runs",
        SandboxAdminRunsView.as_view(),
        name="sandbox-admin-runs",
    ),
    path(
        "labs/sandbox/admin/metrics",
        SandboxAdminMetricsView.as_view(),
        name="sandbox-admin-metrics",
    ),
]
