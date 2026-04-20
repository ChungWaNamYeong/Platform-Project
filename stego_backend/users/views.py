from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from docker.errors import DockerException
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from sandbox_manager import StegoSandbox

from .models import ChatSession, SandboxRun
from .permissions import IsSuperUser
from .serializers import (
    AdminUserSerializer,
    ChatMessageSerializer,
    ChatSessionSerializer,
    RegisterSerializer,
    SandboxRunSerializer,
    StudentSerializer,
)

Student = get_user_model()


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {"token": token.key, "user": StudentSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", "")).strip()
        if not username or not password:
            return Response(
                {"detail": "username 和 password 不能为空"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"detail": "用户名或密码错误"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not user.is_active:
            return Response(
                {"detail": "账户已禁用"},
                status=status.HTTP_403_FORBIDDEN,
            )

        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": StudentSerializer(user).data})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response({"detail": "已退出登录"})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(StudentSerializer(request.user).data)


class UserListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsSuperUser]
    serializer_class = AdminUserSerializer
    queryset = Student.objects.all().order_by("-date_joined")


class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, IsSuperUser]
    serializer_class = AdminUserSerializer
    queryset = Student.objects.all()


class ChatSessionListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatSessionSerializer

    def get_queryset(self):
        return ChatSession.objects.filter(user=self.request.user).order_by("-updated_at")

    def perform_create(self, serializer):
        # 会话强制绑定当前登录用户，防止跨用户写入
        serializer.save(user=self.request.user)


class ChatSessionDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatSessionSerializer

    def get_queryset(self):
        return ChatSession.objects.filter(user=self.request.user)


class ChatSessionMessagesView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatMessageSerializer

    def _get_session(self):
        session_id = self.kwargs["session_id"]
        return get_object_or_404(ChatSession, id=session_id, user=self.request.user)

    def get_queryset(self):
        session = self._get_session()
        return session.messages.all().order_by("created_at", "id")

    def perform_create(self, serializer):
        session = self._get_session()
        serializer.save(session=session)
        session.save(update_fields=["updated_at"])


class SandboxStartView(APIView):
    """启动当前登录用户的实验沙箱。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        experiment_topic = str(request.data.get("experiment_topic", "")).strip()
        if not experiment_topic:
            return Response(
                {"detail": "experiment_topic 不能为空"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        running_run = (
            SandboxRun.objects.filter(user=request.user, status=SandboxRun.STATUS_RUNNING)
            .order_by("-created_at")
            .first()
        )
        if running_run:
            return Response(
                {
                    "detail": "当前用户已有运行中的沙箱",
                    "run": SandboxRunSerializer(running_run).data,
                    "reused": True,
                }
            )

        run = SandboxRun.objects.create(
            user=request.user,
            experiment_topic=experiment_topic,
            status=SandboxRun.STATUS_STARTING,
        )

        try:
            sandbox = StegoSandbox()
            result = sandbox.start_container(
                image=StegoSandbox.DEFAULT_IMAGE,
                environment={
                    "LAB_USER_ID": str(request.user.id),
                    "LAB_USERNAME": request.user.username,
                    "LAB_EXPERIMENT_TOPIC": experiment_topic,
                },
                name=f"stego-lab-u{request.user.id}-r{run.id}",
            )
        except Exception as exc:
            run.status = SandboxRun.STATUS_FAILED
            run.launch_error = str(exc)
            run.save(update_fields=["status", "launch_error", "updated_at"])
            error_code = "sandbox_start_failed"
            hint = "请联系管理员查看后端日志。"
            exc_text = str(exc)
            if isinstance(exc, DockerException) and (
                "fetching server API version" in exc_text
                or "No such file or directory" in exc_text
                or "Connection aborted" in exc_text
            ):
                error_code = "docker_unavailable"
                hint = "后端未连接 Docker daemon，请确认 django 服务已挂载 /var/run/docker.sock 并重启。"
            elif "未成功映射端口" in exc_text:
                error_code = "sandbox_port_mapping_failed"
                hint = "沙箱容器未正确暴露 Web 端口，请检查镜像启动命令和端口占用情况。"
            return Response(
                {
                    "detail": f"启动沙箱失败：{exc}",
                    "error_code": error_code,
                    "hint": hint,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        run.status = SandboxRun.STATUS_RUNNING
        run.container_id = result["container_id"]
        run.web_port = result["web_port"]
        run.image_name = result.get("image") or StegoSandbox.DEFAULT_IMAGE
        run.launch_error = ""
        run.started_at = timezone.now()
        run.stopped_at = None
        run.save(
            update_fields=[
                "status",
                "container_id",
                "web_port",
                "image_name",
                "launch_error",
                "started_at",
                "stopped_at",
                "updated_at",
            ]
        )

        payload = SandboxRunSerializer(run).data
        payload["web_url"] = self._build_web_url(request, run.web_port)
        return Response({"detail": "沙箱启动成功", "run": payload, "reused": False})

    @staticmethod
    def _build_web_url(request, web_port: int | None) -> str:
        if not web_port:
            return ""
        host = request.get_host().split(":")[0]
        if host in {"0.0.0.0", ""}:
            host = "127.0.0.1"
        return f"http://{host}:{web_port}"


class SandboxStopView(APIView):
    """停止沙箱，普通用户仅可停止自己的沙箱。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        run_id = request.data.get("run_id")
        if request.user.is_superuser and run_id:
            run = get_object_or_404(SandboxRun, id=run_id)
            if run.status not in (
                SandboxRun.STATUS_RUNNING,
                SandboxRun.STATUS_STARTING,
            ):
                return Response(
                    {
                        "detail": "该记录已不在运行中，无需停止。",
                        "run": SandboxRunSerializer(run).data,
                    },
                    status=status.HTTP_200_OK,
                )
        else:
            run = (
                SandboxRun.objects.filter(
                    user=request.user,
                    status=SandboxRun.STATUS_RUNNING,
                )
                .order_by("-created_at")
                .first()
            )
            if run is None:
                return Response({"detail": "当前没有运行中的沙箱", "run": None}, status=status.HTTP_200_OK)

        if run.container_id:
            try:
                StegoSandbox().stop_container(run.container_id, remove=True)
            except Exception as exc:
                return Response(
                    {"detail": f"停止沙箱失败：{exc}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        run.status = SandboxRun.STATUS_STOPPED
        run.stopped_at = timezone.now()
        run.save(update_fields=["status", "stopped_at", "updated_at"])
        return Response({"detail": "沙箱已停止", "run": SandboxRunSerializer(run).data})


class SandboxStatusView(APIView):
    """查询当前用户沙箱状态。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        running_run = (
            SandboxRun.objects.filter(user=request.user, status=SandboxRun.STATUS_RUNNING)
            .order_by("-created_at")
            .first()
        )
        latest_runs = SandboxRun.objects.filter(user=request.user).order_by("-created_at")[:10]
        return Response(
            {
                "running": SandboxRunSerializer(running_run).data if running_run else None,
                "history": SandboxRunSerializer(latest_runs, many=True).data,
            }
        )


class SandboxAdminRunsView(generics.ListAPIView):
    """超级管理员查看全部用户沙箱运行记录。"""

    permission_classes = [IsAuthenticated, IsSuperUser]
    serializer_class = SandboxRunSerializer
    queryset = SandboxRun.objects.select_related("user").all().order_by("-created_at")
