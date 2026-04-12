from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ChatSession
from .permissions import IsSuperUser
from .serializers import (
    AdminUserSerializer,
    ChatMessageSerializer,
    ChatSessionSerializer,
    RegisterSerializer,
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
