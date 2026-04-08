from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Student


@admin.register(Student)
class StudentAdmin(UserAdmin):
    """Admin for Student with extra profile fields."""

    fieldsets = UserAdmin.fieldsets + (
        ("\u5b66\u751f\u4fe1\u606f", {"fields": ("student_id", "major", "grade")}),
    )
    list_display = ("username", "email", "student_id", "major", "grade", "is_staff")
