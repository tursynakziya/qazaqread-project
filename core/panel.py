"""In-platform admin panel: texts, comprehension tests, users."""

import secrets
from functools import wraps

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import QuestionForm, TextForm
from .models import GRADE_NORMS, Question, QuizAttempt, ReadingSession, Text, User, int_or_none


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped


@admin_required
def dashboard(request):
    q = request.GET.get("q", "").strip()
    grade = str(int_or_none(request.GET.get("grade")) or "")
    texts = Text.objects.annotate(
        n_questions=Count("questions", distinct=True), n_reads=Count("sessions", distinct=True)
    ).order_by("grade", "title")
    if q:
        texts = texts.filter(Q(title__icontains=q) | Q(body__icontains=q))
    if grade:
        texts = texts.filter(grade=grade)
    stats = {
        "texts": Text.objects.count(),
        "with_quiz": Text.objects.filter(questions__isnull=False).distinct().count(),
        "questions": Question.objects.count(),
        "students": User.objects.filter(role=User.Role.STUDENT).count(),
        "sessions": ReadingSession.objects.count(),
        "attempts": QuizAttempt.objects.count(),
    }
    return render(
        request,
        "core/panel/dashboard.html",
        {"texts": texts, "stats": stats, "q": q, "grade": grade, "grades": list(GRADE_NORMS)},
    )


@admin_required
def text_edit(request, pk=None):
    text = get_object_or_404(Text, pk=pk) if pk else None
    form = TextForm(request.POST or None, instance=text)
    if request.method == "POST" and form.is_valid():
        is_new = text is None
        text = form.save(commit=False)
        if is_new:
            text.created_by = request.user
        text.save()
        if is_new:
            messages.success(request, f"«{text}» қосылды ({text.word_count} сөз). Енді тест сұрақтарын қосыңыз.")
            return redirect("panel_questions", pk=text.pk)
        messages.success(request, f"«{text}» сақталды.")
        return redirect("panel_dashboard")
    return render(request, "core/panel/text_form.html", {"form": form, "text": text})


@admin_required
def text_delete(request, pk):
    text = get_object_or_404(Text, pk=pk)
    if request.method == "POST":
        title = text.title
        text.delete()
        messages.success(request, f"«{title}» жойылды.")
        return redirect("panel_dashboard")
    return render(
        request,
        "core/panel/confirm_delete.html",
        {"text": text, "sessions": text.sessions.count(), "questions": text.questions.count()},
    )


@admin_required
def questions(request, pk):
    text = get_object_or_404(Text, pk=pk)
    form = QuestionForm(request.POST or None, initial={"order": text.questions.count() + 1})
    if request.method == "POST" and form.is_valid():
        form.save(text)
        messages.success(request, "Сұрақ қосылды.")
        return redirect("panel_questions", pk=text.pk)
    items = text.questions.prefetch_related("choices")
    attempts = text.quiz_attempts.select_related("student")[:10]
    return render(
        request,
        "core/panel/questions.html",
        {"text": text, "questions": items, "form": form, "attempts": attempts},
    )


@admin_required
def question_edit(request, pk):
    question = get_object_or_404(Question.objects.select_related("text"), pk=pk)
    form = QuestionForm(request.POST or None, instance=question)
    if request.method == "POST" and form.is_valid():
        form.save(question.text)
        messages.success(request, "Сұрақ сақталды.")
        return redirect("panel_questions", pk=question.text_id)
    return render(request, "core/panel/question_form.html", {"form": form, "question": question, "text": question.text})


@admin_required
@require_POST
def question_delete(request, pk):
    question = get_object_or_404(Question, pk=pk)
    text_id = question.text_id
    question.delete()
    messages.success(request, "Сұрақ жойылды.")
    return redirect("panel_questions", pk=text_id)


@admin_required
def users(request):
    role = request.GET.get("role", "")
    q = request.GET.get("q", "").strip()
    people = User.objects.select_related("school_class").order_by("role", "last_name", "first_name")
    if role:
        people = people.filter(role=role)
    if q:
        people = people.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(username__icontains=q) | Q(email__icontains=q)
        )
    return render(
        request,
        "core/panel/users.html",
        {"people": people[:300], "role": role, "q": q, "roles": User.Role.choices},
    )


@admin_required
@require_POST
def user_role(request, pk):
    person = get_object_or_404(User, pk=pk)
    role = request.POST.get("role")
    if role not in User.Role.values:
        raise PermissionDenied
    if person == request.user and role != User.Role.ADMIN:
        messages.error(request, "Өз әкімші рөліңізді алып тастай алмайсыз.")
    else:
        person.role = role
        person.save(update_fields=["role"])
        messages.success(request, f"{person.display_name}: рөлі «{person.get_role_display()}» болып өзгертілді.")
    next_url = request.POST.get("next", "")
    return redirect(next_url if next_url.startswith("/panel/") else "panel_users")


# No look-alike characters (0/o, 1/l/i), so the password is easy to read out to a child.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


@admin_required
@require_POST
def user_password(request, pk):
    """Passwords are stored only as hashes, so they cannot be shown; the admin issues a new one instead."""
    person = get_object_or_404(User, pk=pk)
    password = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(8))
    person.set_password(password)
    person.save(update_fields=["password"])
    if person == request.user:
        update_session_auth_hash(request, person)
    return render(request, "core/panel/password_done.html", {"person": person, "password": password})


@admin_required
def quiz_results(request):
    attempts = QuizAttempt.objects.select_related("student", "text", "student__school_class")[:200]
    return render(request, "core/panel/quiz_results.html", {"attempts": attempts})
