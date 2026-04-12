from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ChatMessage, ChatSession, Student


@admin.register(Student)
class StudentAdmin(UserAdmin):
    """Admin for Student with extra profile fields."""

    fieldsets = UserAdmin.fieldsets + (
        ("\u5b66\u751f\u4fe1\u606f", {"fields": ("student_id", "major", "grade")}),
    )
    list_display = ("username", "email", "student_id", "major", "grade", "is_staff")


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "fastgpt_chat_id", "updated_at")
    search_fields = ("user__username", "title", "fastgpt_chat_id")
    list_filter = ("updated_at",)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "created_at")
    search_fields = ("session__user__username", "content")
    list_filter = ("role", "created_at")
