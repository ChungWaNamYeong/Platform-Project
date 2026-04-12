from django.contrib.auth.models import AbstractUser
from django.db import models


class Student(AbstractUser):
    """Extended user model for students (Student)."""

    student_id = models.CharField("\u5b66\u53f7", max_length=32, unique=True, blank=True, null=True)
    major = models.CharField("\u4e13\u4e1a", max_length=100, blank=True)
    grade = models.CharField("\u5e74\u7ea7", max_length=32, blank=True)

    class Meta:
        verbose_name = "\u5b66\u751f"
        verbose_name_plural = "\u5b66\u751f"

    def __str__(self):
        return self.username


class ChatSession(models.Model):
    """Per-user AI chat session with FastGPT chatId binding."""

    user = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="chat_sessions",
        verbose_name="\u7528\u6237",
    )
    title = models.CharField("\u4f1a\u8bdd\u6807\u9898", max_length=200, blank=True)
    fastgpt_chat_id = models.CharField(
        "FastGPT chatId",
        max_length=64,
        blank=True,
        default="",
    )
    created_at = models.DateTimeField("\u521b\u5efa\u65f6\u95f4", auto_now_add=True)
    updated_at = models.DateTimeField("\u66f4\u65b0\u65f6\u95f4", auto_now=True)

    class Meta:
        verbose_name = "\u5bf9\u8bdd\u4f1a\u8bdd"
        verbose_name_plural = "\u5bf9\u8bdd\u4f1a\u8bdd"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user.username} - {self.title or self.id}"


class ChatMessage(models.Model):
    """Chat messages under a session."""

    ROLE_CHOICES = (
        ("user", "user"),
        ("assistant", "assistant"),
        ("system", "system"),
    )

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="\u6240\u5c5e\u4f1a\u8bdd",
    )
    role = models.CharField("\u89d2\u8272", max_length=16, choices=ROLE_CHOICES)
    content = models.TextField("\u5185\u5bb9")
    citations_json = models.JSONField("\u5f15\u7528\u6570\u636e", default=list, blank=True)
    raw_response_json = models.JSONField("\u539f\u59cb\u54cd\u5e94", default=dict, blank=True)
    created_at = models.DateTimeField("\u521b\u5efa\u65f6\u95f4", auto_now_add=True)

    class Meta:
        verbose_name = "\u5bf9\u8bdd\u6d88\u606f"
        verbose_name_plural = "\u5bf9\u8bdd\u6d88\u606f"
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.session_id}:{self.role}"
