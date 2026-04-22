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


class SandboxRun(models.Model):
    """记录实验沙箱运行信息，支持用户隔离与管理员追踪。"""

    STATUS_STARTING = "starting"
    STATUS_RUNNING = "running"
    STATUS_STOPPED = "stopped"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_STARTING, "启动中"),
        (STATUS_RUNNING, "运行中"),
        (STATUS_STOPPED, "已停止"),
        (STATUS_FAILED, "启动失败"),
    )

    user = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="sandbox_runs",
        verbose_name="所属用户",
    )
    experiment_topic = models.CharField("实验课题", max_length=120)
    image_name = models.CharField("镜像名称", max_length=200, blank=True, default="")
    status = models.CharField("状态", max_length=20, choices=STATUS_CHOICES, default=STATUS_STARTING)
    container_id = models.CharField("容器 ID", max_length=128, blank=True, default="")
    web_port = models.PositiveIntegerField("Web 端口", blank=True, null=True)
    launch_error = models.TextField("启动错误", blank=True, default="")
    started_at = models.DateTimeField("启动时间", blank=True, null=True)
    stopped_at = models.DateTimeField("停止时间", blank=True, null=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "实验沙箱运行"
        verbose_name_plural = "实验沙箱运行"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.experiment_topic} ({self.status})"


class ExperimentRecord(models.Model):
    """记录实验展示结果，供学生与管理员查看学情。"""

    user = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="experiment_records",
        verbose_name="所属用户",
    )
    experiment_name = models.CharField("实验名称", max_length=120)
    started_at = models.DateTimeField("启动时间", blank=True, null=True)
    completed_at = models.DateTimeField("完成时间", blank=True, null=True)
    cover_image_b64 = models.TextField("载体图(Base64)", blank=True, default="")
    stego_image_b64 = models.TextField("隐写图(Base64)", blank=True, default="")
    psnr = models.FloatField("PSNR", blank=True, null=True)
    histogram_data = models.JSONField("直方图数据", default=dict, blank=True)
    bit_planes_data = models.JSONField("位平面数据", default=dict, blank=True)
    source_text = models.TextField("原始文本", blank=True, default="")
    extracted_text = models.TextField("提取文本", blank=True, default="")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "实验记录"
        verbose_name_plural = "实验记录"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.experiment_name} ({self.created_at:%Y-%m-%d %H:%M:%S})"
