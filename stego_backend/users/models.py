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
