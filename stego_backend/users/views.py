from __future__ import annotations

import csv
import time

from django.contrib.auth import authenticate, get_user_model
from django.db import OperationalError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from docker.errors import DockerException, NotFound
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from sandbox_manager import StegoSandbox

from .models import ChatSession, ExperimentRecord, SandboxRun
from .permissions import IsSuperUser
from .serializers import (
    AdminUserSerializer,
    ChatMessageSerializer,
    ChatSessionSerializer,
    ExperimentRecordListSerializer,
    ExperimentRecordSerializer,
    RegisterSerializer,
    SandboxRunSerializer,
    StudentSerializer,
)

Student = get_user_model()


def _is_sqlite_locked_error(exc: Exception) -> bool:
    """判断是否为 SQLite 的数据库锁冲突。"""
    return "database is locked" in str(exc).lower()


def _create_sandbox_run_with_retry(*, user, experiment_topic: str, max_attempts: int = 3) -> SandboxRun:
    """创建 SandboxRun，遇到 SQLite 锁冲突时做短暂重试。"""
    for attempt in range(1, max_attempts + 1):
        try:
            return SandboxRun.objects.create(
                user=user,
                experiment_topic=experiment_topic,
                status=SandboxRun.STATUS_STARTING,
            )
        except OperationalError as exc:
            if not _is_sqlite_locked_error(exc) or attempt >= max_attempts:
                raise
            # 退避重试，降低并发写入时瞬时锁冲突概率。
            time.sleep(0.15 * attempt)


def _save_sandbox_run_with_retry(run: SandboxRun, update_fields: list[str], max_attempts: int = 3) -> None:
    """保存 SandboxRun，遇到 SQLite 锁冲突时做短暂重试。"""
    for attempt in range(1, max_attempts + 1):
        try:
            run.save(update_fields=update_fields)
            return
        except OperationalError as exc:
            if not _is_sqlite_locked_error(exc) or attempt >= max_attempts:
                raise
            # 保存阶段同样可能遇到短时锁，重试可避免无意义失败。
            time.sleep(0.15 * attempt)


def _filter_experiment_records_for_request(request, queryset):
    """按请求参数过滤实验记录；用户名过滤仅允许管理员使用。"""
    experiment_name = str(request.query_params.get("experiment_name") or "").strip()
    username = str(request.query_params.get("username") or "").strip()
    if experiment_name:
        queryset = queryset.filter(experiment_name=experiment_name)
    if username and request.user.is_superuser:
        queryset = queryset.filter(user__username=username)
    return queryset


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

        try:
            run = _create_sandbox_run_with_retry(
                user=request.user,
                experiment_topic=experiment_topic,
            )
        except OperationalError as exc:
            return Response(
                {
                    "detail": f"启动沙箱失败：{exc}",
                    "error_code": "database_locked",
                    "hint": "数据库正忙，请 1-2 秒后重试；若频繁出现请联系管理员检查并发写入。",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
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
            try:
                _save_sandbox_run_with_retry(run, ["status", "launch_error", "updated_at"])
            except OperationalError:
                # 启动失败时若记录保存也受锁影响，不再向外抛错，避免覆盖原始启动异常。
                pass
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
        try:
            _save_sandbox_run_with_retry(
                run,
                [
                    "status",
                    "container_id",
                    "web_port",
                    "image_name",
                    "launch_error",
                    "started_at",
                    "stopped_at",
                    "updated_at",
                ],
            )
        except OperationalError as exc:
            return Response(
                {
                    "detail": f"启动沙箱失败：{exc}",
                    "error_code": "database_locked",
                    "hint": "容器已启动但状态写入失败，请稍后刷新状态页确认运行结果。",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
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
        try:
            _save_sandbox_run_with_retry(run, ["status", "stopped_at", "updated_at"])
        except OperationalError as exc:
            return Response(
                {
                    "detail": f"停止沙箱失败：{exc}",
                    "error_code": "database_locked",
                    "hint": "数据库正忙，请稍后重试停止操作。",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
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
        running_metrics = None
        if running_run and running_run.container_id:
            try:
                running_metrics = StegoSandbox(ensure_image=False).get_container_metrics(
                    running_run.container_id
                )
            except NotFound:
                running_metrics = {
                    "container_id": running_run.container_id,
                    "error": "container_not_found",
                }
            except Exception as exc:
                running_metrics = {
                    "container_id": running_run.container_id,
                    "error": str(exc),
                }
        return Response(
            {
                "running": SandboxRunSerializer(running_run).data if running_run else None,
                "history": SandboxRunSerializer(latest_runs, many=True).data,
                "running_metrics": running_metrics,
            }
        )


class SandboxAdminRunsView(generics.ListAPIView):
    """超级管理员查看全部用户沙箱运行记录。"""

    permission_classes = [IsAuthenticated, IsSuperUser]
    serializer_class = SandboxRunSerializer
    queryset = SandboxRun.objects.select_related("user").all().order_by("-created_at")


class SandboxAdminMetricsView(APIView):
    """超级管理员实时查看运行中沙箱资源占用。"""

    permission_classes = [IsAuthenticated, IsSuperUser]

    def get(self, request):
        running_runs = SandboxRun.objects.select_related("user").filter(
            status=SandboxRun.STATUS_RUNNING
        )
        sandbox = StegoSandbox(ensure_image=False)
        payload = []
        for run in running_runs:
            if not run.container_id:
                payload.append(
                    {
                        "run_id": run.id,
                        "username": run.user.username,
                        "experiment_topic": run.experiment_topic,
                        "container_id": "",
                        "status": run.status,
                        "metrics": None,
                        "error": "missing_container_id",
                    }
                )
                continue
            try:
                metrics = sandbox.get_container_metrics(run.container_id)
                payload.append(
                    {
                        "run_id": run.id,
                        "username": run.user.username,
                        "experiment_topic": run.experiment_topic,
                        "container_id": run.container_id,
                        "status": run.status,
                        "metrics": metrics,
                        "error": "",
                    }
                )
            except NotFound:
                payload.append(
                    {
                        "run_id": run.id,
                        "username": run.user.username,
                        "experiment_topic": run.experiment_topic,
                        "container_id": run.container_id,
                        "status": run.status,
                        "metrics": None,
                        "error": "container_not_found",
                    }
                )
            except Exception as exc:
                payload.append(
                    {
                        "run_id": run.id,
                        "username": run.user.username,
                        "experiment_topic": run.experiment_topic,
                        "container_id": run.container_id,
                        "status": run.status,
                        "metrics": None,
                        "error": str(exc),
                    }
                )
        return Response({"items": payload, "count": len(payload)})


class ExperimentRecordListCreateView(generics.ListCreateAPIView):
    """实验记录列表与创建接口。"""

    permission_classes = [IsAuthenticated]
    serializer_class = ExperimentRecordSerializer

    def get_serializer_class(self):
        if self.request.method == "GET":
            return ExperimentRecordListSerializer
        return ExperimentRecordSerializer

    def get_queryset(self):
        queryset = ExperimentRecord.objects.select_related("user").order_by("-created_at")
        if not self.request.user.is_superuser:
            queryset = queryset.filter(user=self.request.user)
        return _filter_experiment_records_for_request(self.request, queryset)

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        experiment_name = str(data.get("experiment_name") or "").strip()
        if not experiment_name:
            data["experiment_name"] = "空域 LSB 隐写"
            experiment_name = "空域 LSB 隐写"

        if not data.get("started_at"):
            latest_run = (
                SandboxRun.objects.filter(user=request.user, experiment_topic=experiment_name)
                .order_by("-started_at", "-created_at")
                .first()
            )
            if latest_run and latest_run.started_at:
                data["started_at"] = latest_run.started_at.isoformat()
            else:
                data["started_at"] = timezone.now().isoformat()
        if not data.get("completed_at"):
            data["completed_at"] = timezone.now().isoformat()
        if data.get("duration_seconds") in (None, "", "null"):
            started_dt = parse_datetime(str(data.get("started_at") or ""))
            completed_dt = parse_datetime(str(data.get("completed_at") or ""))
            if started_dt and completed_dt:
                # 兜底根据起止时间计算耗时，避免前端异常导致缺失。
                duration_seconds = (completed_dt - started_dt).total_seconds()
                data["duration_seconds"] = round(max(duration_seconds, 0.0), 3)

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class ExperimentRecordDetailView(generics.RetrieveDestroyAPIView):
    """单条实验记录详情/删除。"""

    permission_classes = [IsAuthenticated]
    serializer_class = ExperimentRecordSerializer
    queryset = ExperimentRecord.objects.select_related("user").all()

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_superuser:
            return queryset
        return queryset.filter(user=self.request.user)


class ExperimentRecordExportView(APIView):
    """导出实验记录，支持 JSON 与 CSV。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        export_format = str(request.query_params.get("format", "json")).strip().lower()
        queryset = ExperimentRecord.objects.select_related("user").order_by("-created_at")
        if not request.user.is_superuser:
            queryset = queryset.filter(user=request.user)
        queryset = _filter_experiment_records_for_request(request, queryset)

        if export_format == "csv":
            return self._export_csv(queryset)

        payload = ExperimentRecordSerializer(queryset, many=True).data
        return Response(payload)

    @staticmethod
    def _export_csv(queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="experiment_records.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "id",
                "username",
                "experiment_name",
                "started_at",
                "completed_at",
                "psnr",
                "source_text",
                "extracted_text",
                "cpu_peak_percent",
                "cpu_avg_percent",
                "memory_peak_bytes",
                "memory_avg_bytes",
                "duration_seconds",
                "cover_image_b64_length",
                "stego_image_b64_length",
                "created_at",
            ]
        )
        for item in queryset:
            writer.writerow(
                [
                    item.id,
                    item.user.username,
                    item.experiment_name,
                    item.started_at.isoformat() if item.started_at else "",
                    item.completed_at.isoformat() if item.completed_at else "",
                    item.psnr if item.psnr is not None else "",
                    item.source_text,
                    item.extracted_text,
                    item.cpu_peak_percent if item.cpu_peak_percent is not None else "",
                    item.cpu_avg_percent if item.cpu_avg_percent is not None else "",
                    item.memory_peak_bytes if item.memory_peak_bytes is not None else "",
                    item.memory_avg_bytes if item.memory_avg_bytes is not None else "",
                    item.duration_seconds if item.duration_seconds is not None else "",
                    len(item.cover_image_b64 or ""),
                    len(item.stego_image_b64 or ""),
                    item.created_at.isoformat() if item.created_at else "",
                ]
            )
        return response


class ExperimentRecordBulkDeleteView(APIView):
    """批量删除实验记录。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_ids = request.data.get("record_ids") or []
        if not isinstance(raw_ids, list):
            return Response(
                {"detail": "record_ids 必须是数组。"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        normalized_ids = []
        for item in raw_ids:
            try:
                normalized_ids.append(int(item))
            except (TypeError, ValueError):
                continue
        normalized_ids = sorted(set(x for x in normalized_ids if x > 0))
        if not normalized_ids:
            return Response(
                {"detail": "未提供有效记录 ID。", "deleted_count": 0, "ignored_count": 0},
                status=status.HTTP_200_OK,
            )

        base_queryset = ExperimentRecord.objects.filter(id__in=normalized_ids)
        if not request.user.is_superuser:
            base_queryset = base_queryset.filter(user=request.user)

        deletable_ids = list(base_queryset.values_list("id", flat=True))
        if deletable_ids:
            ExperimentRecord.objects.filter(id__in=deletable_ids).delete()
        ignored_count = len(normalized_ids) - len(deletable_ids)
        return Response(
            {
                "detail": "批量删除完成。",
                "deleted_count": len(deletable_ids),
                "ignored_count": max(ignored_count, 0),
                "deleted_ids": deletable_ids,
            },
            status=status.HTTP_200_OK,
        )
