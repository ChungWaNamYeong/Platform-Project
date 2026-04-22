from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import ChatMessage, ChatSession, ExperimentRecord, SandboxRun

Student = get_user_model()


class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = [
            "id",
            "username",
            "email",
            "student_id",
            "major",
            "grade",
            "is_staff",
            "is_superuser",
            "is_active",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = Student
        fields = ["username", "password", "email", "student_id", "major", "grade"]

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = Student(**validated_data)
        user.set_password(password)
        user.is_staff = False
        user.is_superuser = False
        user.save()
        return user


class AdminUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = Student
        fields = [
            "id",
            "username",
            "password",
            "email",
            "student_id",
            "major",
            "grade",
            "is_staff",
            "is_superuser",
            "is_active",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined"]

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = Student(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_password("ChangeMe123!")
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class ChatSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = [
            "id",
            "title",
            "fastgpt_chat_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "session",
            "role",
            "content",
            "citations_json",
            "raw_response_json",
            "created_at",
        ]
        read_only_fields = ["id", "session", "created_at"]


class SandboxRunSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = SandboxRun
        fields = [
            "id",
            "user",
            "username",
            "experiment_topic",
            "image_name",
            "status",
            "container_id",
            "web_port",
            "launch_error",
            "started_at",
            "stopped_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "username",
            "container_id",
            "web_port",
            "started_at",
            "stopped_at",
            "created_at",
            "updated_at",
        ]


class ExperimentRecordSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = ExperimentRecord
        fields = [
            "id",
            "user",
            "username",
            "experiment_name",
            "started_at",
            "completed_at",
            "cover_image_b64",
            "stego_image_b64",
            "psnr",
            "histogram_data",
            "bit_planes_data",
            "source_text",
            "extracted_text",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "username",
            "created_at",
            "updated_at",
        ]
