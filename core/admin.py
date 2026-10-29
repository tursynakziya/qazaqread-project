from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .analysis import analyze_session
from .models import (
    Assignment,
    AttemptAnswer,
    Choice,
    ClassReading,
    Question,
    QuizAttempt,
    ReadingSession,
    SchoolClass,
    Text,
    User,
    WordResult,
)


@admin.register(User)
class QazaqUserAdmin(UserAdmin):
    list_display = ("username", "display_name", "role", "school_class", "login_code", "is_active")
    list_filter = ("role", "school_class", "is_active", "is_staff")
    search_fields = ("username", "first_name", "last_name", "email", "login_code")
    filter_horizontal = ("children", "groups", "user_permissions")
    fieldsets = UserAdmin.fieldsets + (
        ("QazaqRead", {"fields": ("role", "school_name", "school_class", "children", "login_code")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("QazaqRead", {"fields": ("role", "first_name", "last_name", "school_class")}),
    )
    actions = ["new_login_codes"]

    @admin.action(description="Жаңа кіру коды (QR) жасау")
    def new_login_codes(self, request, queryset):
        for user in queryset:
            user.regenerate_login_code()
        self.message_user(request, f"{queryset.count()} пайдаланушыға жаңа код жасалды.")


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("__str__", "school", "teacher", "academic_year")
    list_filter = ("grade", "academic_year")


@admin.register(Text)
class TextAdmin(admin.ModelAdmin):
    list_display = ("title", "grade", "difficulty", "topic", "genre", "word_count", "is_featured")
    list_filter = ("grade", "difficulty", "topic", "genre", "is_featured")
    search_fields = ("title", "body")
    readonly_fields = ("word_count",)


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("text", "school_class", "due_date", "assigned_by", "created_at")
    list_filter = ("school_class",)


class WordResultInline(admin.TabularInline):
    model = WordResult
    extra = 0
    fields = ("position", "expected", "heard", "status")


@admin.register(ReadingSession)
class ReadingSessionAdmin(admin.ModelAdmin):
    list_display = ("student", "text", "created_at", "wpm", "accuracy", "mark", "status")
    list_filter = ("status", "student__school_class", "text__grade")
    search_fields = ("student__first_name", "student__last_name", "text__title")
    readonly_fields = ("words_total", "words_correct", "words_review", "words_skipped", "wpm", "accuracy")
    inlines = [WordResultInline]
    actions = ["reanalyze"]

    @admin.action(description="Транскрипт бойынша қайта талдау")
    def reanalyze(self, request, queryset):
        for session in queryset:
            analyze_session(session)
        self.message_user(request, f"{queryset.count()} сессия қайта талданды.")


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 4
    max_num = 4


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("prompt", "text", "order")
    list_filter = ("text__grade", "text")
    search_fields = ("prompt", "text__title")
    inlines = [ChoiceInline]


class AttemptAnswerInline(admin.TabularInline):
    model = AttemptAnswer
    extra = 0
    readonly_fields = ("question", "choice", "is_correct")
    can_delete = False


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ("student", "text", "correct", "total", "created_at")
    list_filter = ("text", "student__school_class")
    inlines = [AttemptAnswerInline]


@admin.register(ClassReading)
class ClassReadingAdmin(admin.ModelAdmin):
    list_display = ("school_class", "text", "teacher", "created_at")
    list_filter = ("school_class",)
    filter_horizontal = ("absent",)
