import csv
import re
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import stats
from .analysis import analyze_session
from .forms import (
    AddChildForm,
    AssignmentForm,
    CommentForm,
    LoginForm,
    ProfileForm,
    RegisterForm,
    SchoolClassForm,
    StudentCreateForm,
    StyledPasswordChangeForm,
    TextForm,
)
from .models import (
    AttemptAnswer,
    Assignment,
    QuizAttempt,
    ReadingSession,
    Text,
    User,
    WordResult,
    READING_SECONDS,
    grade_norm,
    int_or_none,
)
from .speech import is_available as speech_available, live_feed, text_grammar, transcribe

HOME_BY_ROLE = {
    User.Role.STUDENT: "student_dashboard",
    User.Role.PARENT: "parent_dashboard",
    User.Role.TEACHER: "teacher_dashboard",
}


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def can_view_student(user, student):
    if user == student or user.is_superuser:
        return True
    if user.is_parent:
        return user.children.filter(pk=student.pk).exists()
    if user.is_teacher:
        return student.school_class_id is not None and student.school_class.teacher_id == user.pk
    return False


def teacher_class(request):
    """The class the teacher is working with (?class=<id> or their first)."""
    classes = request.user.taught_classes.all()
    class_id = int_or_none(request.GET.get("class")) or request.session.get("class_id")
    current = classes.filter(pk=class_id).first() if class_id else None
    current = current or classes.annotate(n=Count("students")).order_by("-n").first()
    if current:
        request.session["class_id"] = current.pk
    return classes, current


# ---------------------------------------------------------------- auth


def home(request):
    if not request.user.is_authenticated:
        return redirect("login")
    if request.user.is_admin and request.user.role not in HOME_BY_ROLE:
        return redirect("panel_dashboard")
    return redirect(HOME_BY_ROLE.get(request.user.role, "settings"))


class QazaqLoginView(LoginView):
    template_name = "core/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        if not form.cleaned_data.get("remember"):
            self.request.session.set_expiry(0)
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("register_form", RegisterForm())
        ctx["active_tab"] = "login"
        return ctx


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="core.backends.EmailOrUsernameBackend")
        messages.success(request, f"Қош келдіңіз, {user.short_name}! Аккаунт жасалды.")
        if user.is_teacher:
            return redirect("class_create")
        if user.is_parent:
            return redirect("add_child")
        return redirect("home")
    return render(
        request,
        "core/login.html",
        {"form": LoginForm(request), "register_form": form, "active_tab": "register"},
    )


def qr_login(request, code):
    student = get_object_or_404(User, login_code=code.lower(), role=User.Role.STUDENT, is_active=True)
    login(request, student, backend="core.backends.EmailOrUsernameBackend")
    messages.success(request, f"Сәлем, {student.short_name}!")
    return redirect("student_dashboard")


def qr_code_login(request):
    """The QR-code form on the login page: type the card code by hand."""
    code = request.POST.get("code", "").strip()
    if request.method == "POST" and code:
        return redirect("qr_login", code=code)
    return redirect("login")


# ---------------------------------------------------------------- student


@role_required(User.Role.STUDENT)
def student_dashboard(request):
    student = request.user
    summary = stats.student_summary(student)
    read_ids = student.sessions.values_list("text_id", flat=True)
    assigned = (
        Assignment.objects.filter(school_class=student.school_class)
        .exclude(text_id__in=read_ids)
        .select_related("text")[:3]
        if student.school_class
        else []
    )
    assigned = list(assigned)
    recommended = list(Text.objects.filter(grade=student.grade or 1).exclude(pk__in=read_ids)[:3])
    # The "read a new text" button: the first task, else the first recommendation (may be none at all).
    next_text = assigned[0].text if assigned else (recommended[0] if recommended else None)
    return render(
        request,
        "core/student.html",
        {
            "s": summary,
            "assigned": assigned,
            "recommended": recommended,
            "next_text": next_text,
            "recent": summary["sessions"][:3],
        },
    )


@login_required
def library(request):
    texts = Text.objects.all()
    q = request.GET.get("q", "").strip()
    grade = str(int_or_none(request.GET.get("grade")) or "")
    if not grade and request.user.is_student and request.user.grade and "grade" not in request.GET:
        grade = str(request.user.grade)
    difficulty = request.GET.get("difficulty", "")
    sort = request.GET.get("sort", "popular")

    if q:
        texts = texts.filter(Q(title__icontains=q) | Q(body__icontains=q))
    if grade:
        texts = texts.filter(grade=grade)
    if difficulty:
        texts = texts.filter(difficulty=difficulty)

    texts = texts.annotate(reads=Count("sessions"))
    texts = texts.order_by({"words": "word_count", "new": "-created_at"}.get(sort, "-reads"))

    my_results = {}
    if request.user.is_student:
        for s in request.user.sessions.order_by("created_at"):
            my_results[s.text_id] = s
    cards = [{"text": t, "mine": my_results.get(t.pk)} for t in texts]

    featured = Text.objects.filter(is_featured=True, **({"grade": grade} if grade else {})).first()
    return render(
        request,
        "core/library.html",
        {
            "cards": cards,
            "featured": featured,
            "total": Text.objects.count(),
            "q": q,
            "grade": grade,
            "difficulty": difficulty,
            "sort": sort,
            "grades": [1, 2, 3, 4],
            "difficulties": Text.Difficulty.choices,
        },
    )


@role_required(User.Role.STUDENT)
def reading(request, pk):
    text = get_object_or_404(Text, pk=pk)
    low, high = grade_norm(text.grade)
    assignment = (
        Assignment.objects.filter(text=text, school_class=request.user.school_class).first()
        if request.user.school_class
        else None
    )
    return render(
        request,
        "core/reading.html",
        {
            "text": text,
            "norm_low": low,
            "norm_high": high,
            "assignment": assignment,
            "server_speech": speech_available(),
            "reading_seconds": READING_SECONDS,
            "submit_url": reverse("submit_reading", args=[text.pk]),
        },
    )


LIVE_SID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
LIVE_MAX_CHUNK = 512 * 1024  # bytes of 16 kHz PCM, ~16 s


@role_required(User.Role.STUDENT, User.Role.TEACHER)
@require_POST
def live_recognize(request, pk):
    """Live recognition while reading: body is raw 16 kHz mono PCM16, returns the text heard so far."""
    sid = request.GET.get("sid", "")
    if not LIVE_SID_RE.match(sid) or not speech_available():
        return JsonResponse({"error": "unavailable"}, status=400)
    pcm = request.body
    if len(pcm) > LIVE_MAX_CHUNK:
        return JsonResponse({"error": "too large"}, status=413)
    text = get_object_or_404(Text, pk=pk)
    heard = live_feed(
        (request.user.pk, pk, sid),
        pcm[: len(pcm) // 2 * 2],
        final=request.GET.get("final") == "1",
        grammar=text_grammar(text.body),
    )
    if heard is None:
        return JsonResponse({"error": "busy"}, status=503)
    return JsonResponse({"text": heard})


@role_required(User.Role.STUDENT)
@require_POST
def submit_reading(request, pk):
    text = get_object_or_404(Text, pk=pk)
    assignment_id = int_or_none(request.POST.get("assignment"))
    if assignment_id and not Assignment.objects.filter(pk=assignment_id, school_class=request.user.school_class).exists():
        assignment_id = None
    session = save_reading(request, text, request.user, assignment_id=assignment_id)
    url = reverse("result", args=[session.pk])
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"redirect": url})
    return redirect(url)


def save_reading(request, text, student, **extra):
    """Store an uploaded reading for `student`, recognise the recording and score it."""
    try:
        duration = max(0.0, min(float(request.POST.get("duration", 0)), READING_SECONDS))
    except ValueError:
        duration = 0.0
    session = ReadingSession(
        student=student,
        text=text,
        transcript=request.POST.get("transcript", "")[:20000],
        duration_seconds=duration,
        **extra,
    )
    audio = request.FILES.get("audio")
    if audio:
        session.audio.save(audio.name or "reading.webm", audio, save=False)
    session.save()

    # The server model scores every student the same way; the browser's
    # transcript is only a fallback when server recognition is unavailable.
    if session.audio:
        server_transcript = transcribe(session.audio.path, grammar=text_grammar(text.body))
        if server_transcript.strip():
            session.transcript = server_transcript
            session.save(update_fields=["transcript"])

    analyze_session(session)
    return session


@login_required
def results_list(request, student_id=None):
    student = get_object_or_404(User, pk=student_id, role=User.Role.STUDENT) if student_id else request.user
    if not student.is_student or not can_view_student(request.user, student):
        raise PermissionDenied
    summary = stats.student_summary(student)
    return render(request, "core/results.html", {"student": student, "s": summary})


@login_required
def result_detail(request, pk):
    session = get_object_or_404(ReadingSession.objects.select_related("text", "student"), pk=pk)
    if not can_view_student(request.user, session.student):
        raise PermissionDenied
    words = {w.position: w for w in session.word_results.all()}
    tokens = [(tok, words.get(idx) if idx is not None else None, idx) for tok, idx in session.text.tokens]
    previous = (
        session.student.sessions.filter(created_at__lt=session.created_at).order_by("-created_at").first()
    )
    is_teacher = request.user.is_teacher and can_view_student(request.user, session.student)
    return render(
        request,
        "core/result.html",
        {
            "session": session,
            "tokens": tokens,
            "previous": previous,
            "is_teacher": is_teacher,
            "comment_form": CommentForm(instance=session) if is_teacher else None,
            "not_reached": session.text.word_count - session.words_total,
            "has_quiz": session.text.questions.exists(),
            "attempt": session.quiz_attempts.first(),
        },
    )


@login_required
def session_audio(request, pk):
    session = get_object_or_404(ReadingSession, pk=pk)
    if not can_view_student(request.user, session.student) or not session.audio:
        raise Http404
    return FileResponse(session.audio.open("rb"), content_type="audio/webm")


@role_required(User.Role.TEACHER)
@require_POST
def review_word(request, pk, position):
    session = get_object_or_404(ReadingSession, pk=pk)
    if not can_view_student(request.user, session.student):
        raise PermissionDenied
    status = request.POST.get("status")
    if status not in WordResult.Status.values:
        return JsonResponse({"error": "bad status"}, status=400)
    text_words = session.text.words
    if not 0 <= position < len(text_words):
        raise Http404
    WordResult.objects.update_or_create(
        session=session, position=position, defaults={"status": status, "expected": text_words[position][:100]}
    )
    if session.status == ReadingSession.Status.NEEDS_REVIEW and not session.word_results.filter(
        status=WordResult.Status.MISREAD
    ).exists():
        session.status = ReadingSession.Status.COMPLETED
    session.recalculate()
    return JsonResponse(
        {
            "wpm": round(session.wpm),
            "accuracy": round(session.accuracy),
            "correct": session.words_correct,
            "review": session.words_review,
            "skipped": session.words_skipped,
            "total": session.words_total,
        }
    )


@role_required(User.Role.TEACHER)
@require_POST
def session_comment(request, pk):
    session = get_object_or_404(ReadingSession, pk=pk)
    if not can_view_student(request.user, session.student):
        raise PermissionDenied
    form = CommentForm(request.POST, instance=session)
    if form.is_valid():
        form.save()
        messages.success(request, "Пікір сақталды.")
    return redirect("result", pk=pk)


# ---------------------------------------------------------------- comprehension test


@role_required(User.Role.STUDENT)
def quiz(request, pk):
    text = get_object_or_404(Text, pk=pk)
    questions = list(text.questions.prefetch_related("choices"))
    if not questions:
        raise Http404
    errors = False
    if request.method == "POST":
        picked = {}
        for question in questions:
            choice_id = request.POST.get(f"q{question.pk}")
            picked[question.pk] = next((c for c in question.choices.all() if str(c.pk) == choice_id), None)
        if None in picked.values():
            errors = True
        else:
            session = request.user.sessions.filter(text=text).first()
            attempt = QuizAttempt.objects.create(student=request.user, text=text, session=session, total=len(questions))
            AttemptAnswer.objects.bulk_create(
                AttemptAnswer(attempt=attempt, question=q, choice=picked[q.pk], is_correct=picked[q.pk].is_correct)
                for q in questions
            )
            attempt.correct = sum(picked[q.pk].is_correct for q in questions)
            attempt.save(update_fields=["correct"])
            return redirect("quiz_result", pk=attempt.pk)
    return render(
        request,
        "core/quiz.html",
        {"text": text, "questions": questions, "errors": errors, "posted": request.POST},
    )


@login_required
def quiz_result(request, pk):
    attempt = get_object_or_404(QuizAttempt.objects.select_related("text", "student"), pk=pk)
    if not can_view_student(request.user, attempt.student) and not request.user.is_admin:
        raise PermissionDenied
    answers = {a.question_id: a for a in attempt.answers.all()}
    rows = [
        {"question": q, "answer": answers.get(q.pk), "correct": q.correct_choice}
        for q in attempt.text.questions.prefetch_related("choices")
        if q.pk in answers
    ]
    return render(request, "core/quiz_result.html", {"attempt": attempt, "rows": rows})


# ---------------------------------------------------------------- parent


@role_required(User.Role.PARENT)
def parent_dashboard(request):
    children = list(request.user.children.select_related("school_class"))
    if not children:
        return render(request, "core/parents.html", {"children": [], "add_form": AddChildForm()})
    child_id = request.GET.get("child")
    child = next((c for c in children if str(c.pk) == child_id), children[0])
    summary = stats.student_summary(child)
    return render(
        request,
        "core/parents.html",
        {
            "children": children,
            "child": child,
            "s": summary,
            "week": stats.weekly_minutes(child),
            "teacher": child.school_class.teacher if child.school_class else None,
            "add_form": AddChildForm(),
        },
    )


@role_required(User.Role.PARENT)
def add_child(request):
    form = AddChildForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.user.children.add(form.child)
        messages.success(request, f"{form.child.display_name} сіздің кабинетіңізге қосылды.")
        return redirect(f"{reverse('parent_dashboard')}?child={form.child.pk}")
    return render(
        request,
        "core/form_page.html",
        {
            "form": form,
            "title": "Баланы қосу",
            "subtitle": "Баланың QR-картасындағы кіру кодын енгізіңіз.",
            "icon": "add_circle",
            "submit": "Қосу",
        },
    )


@login_required
def student_report(request, student_id):
    student = get_object_or_404(User, pk=student_id, role=User.Role.STUDENT)
    if not can_view_student(request.user, student):
        raise PermissionDenied
    return render(
        request,
        "core/report.html",
        {"student": student, "s": stats.student_summary(student), "now": timezone.localtime()},
    )


# ---------------------------------------------------------------- teacher


@role_required(User.Role.TEACHER)
def teacher_dashboard(request):
    classes, current = teacher_class(request)
    if current is None:
        return redirect("class_create")
    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "speed")
    rows = stats.class_rows(current, q, sort)
    recent = (
        ReadingSession.objects.filter(student__school_class=current)
        .select_related("student", "text")[:6]
    )
    review = ReadingSession.objects.filter(
        student__school_class=current, status=ReadingSession.Status.NEEDS_REVIEW
    ).select_related("student", "text")
    return render(
        request,
        "core/teacher.html",
        {
            "classes": classes,
            "current": current,
            "summary": stats.class_summary(current),
            "rows": rows,
            "q": q,
            "sort": sort,
            "recent": recent,
            "review": review,
            "assignments": current.assignments.select_related("text")[:5],
            "lessons": current.class_readings.select_related("text").annotate(n_read=Count("sessions__student", distinct=True))[:5],
        },
    )


@role_required(User.Role.TEACHER)
def class_create(request):
    form = SchoolClassForm(request.POST or None, initial={"school": request.user.school_name})
    if request.method == "POST" and form.is_valid():
        school_class = form.save(commit=False)
        school_class.teacher = request.user
        school_class.save()
        request.session["class_id"] = school_class.pk
        messages.success(request, f"{school_class} сыныбы құрылды. Енді оқушыларды қосыңыз.")
        return redirect("teacher_dashboard")
    return render(
        request,
        "core/form_page.html",
        {"form": form, "title": "Сынып құру", "subtitle": "Сіз жүргізетін сыныптың мәліметтері.", "icon": "groups", "submit": "Құру"},
    )


@role_required(User.Role.TEACHER)
def student_add(request):
    _, current = teacher_class(request)
    if current is None:
        return redirect("class_create")
    form = StudentCreateForm(request.POST or None, school_class=current)
    if request.method == "POST" and form.is_valid():
        student = form.save()
        messages.success(request, f"{student.display_name} қосылды. Кіру коды: {student.login_code}")
        if "another" in request.POST:
            return redirect("student_add")
        return redirect("teacher_dashboard")
    return render(
        request,
        "core/form_page.html",
        {
            "form": form,
            "title": f"Оқушыны қосу — {current}",
            "subtitle": "Оқушы жүйеге QR-карта арқылы кіреді, құпиясөз қажет емес.",
            "icon": "person_add",
            "submit": "Қосу",
            "submit_another": "Сақтап, тағы қосу",
        },
    )


@role_required(User.Role.TEACHER)
def assign_text(request):
    _, current = teacher_class(request)
    if current is None:
        return redirect("class_create")
    initial = {"text": request.GET.get("text")} if request.GET.get("text") else None
    form = AssignmentForm(request.POST or None, grade=current.grade, initial=initial)
    if request.method == "POST" and form.is_valid():
        assignment = form.save(commit=False)
        assignment.school_class = current
        assignment.assigned_by = request.user
        assignment.save()
        messages.success(request, f"«{assignment.text}» мәтіні {current} сыныбына тағайындалды.")
        return redirect("teacher_dashboard")
    return render(
        request,
        "core/form_page.html",
        {"form": form, "title": f"Мәтін тағайындау — {current}", "subtitle": "Оқушылар мәтінді басты бетінен көреді.", "icon": "assignment_add", "submit": "Тағайындау"},
    )


@role_required(User.Role.TEACHER)
def text_create(request):
    form = TextForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        text = form.save(commit=False)
        text.created_by = request.user
        text.save()
        messages.success(request, f"«{text}» мәтіні кітапханаға қосылды ({text.word_count} сөз).")
        return redirect("library")
    return render(
        request,
        "core/form_page.html",
        {"form": form, "title": "Жаңа мәтін қосу", "subtitle": "Мәтін барлық сыныптардың кітапханасында пайда болады.", "icon": "post_add", "submit": "Сақтау"},
    )


@role_required(User.Role.TEACHER)
def export_csv(request):
    _, current = teacher_class(request)
    if current is None:
        raise Http404
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="qazaqread_{current.grade}{current.letter}.csv"'
    response.write("﻿")  # BOM so Excel opens Cyrillic correctly
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["Оқушы", "Мәтін", "Күні", "Жылдамдық (сөз/мин)", "Дәлдік (%)", "Дұрыс", "Қате", "Өткізілген", "Ұзақтығы (сек)", "Мәртебе"])
    sessions = ReadingSession.objects.filter(student__school_class=current).select_related("student", "text")
    for s in sessions.order_by("student__last_name", "created_at"):
        writer.writerow([
            s.student.display_name,
            s.text.title,
            timezone.localtime(s.created_at).strftime("%d.%m.%Y %H:%M"),
            round(s.wpm, 1),
            round(s.accuracy, 1),
            s.words_correct,
            s.words_review,
            s.words_skipped,
            round(s.duration_seconds),
            s.level[0],
        ])
    return response


@role_required(User.Role.TEACHER)
def qr_cards(request):
    classes, current = teacher_class(request)
    if current is None:
        return redirect("class_create")
    students = current.students.order_by("last_name", "first_name")
    base = request.build_absolute_uri("/")[:-1]
    cards = [{"student": s, "url": base + reverse("qr_login", args=[s.login_code])} for s in students]
    return render(request, "core/qr_cards.html", {"current": current, "classes": classes, "cards": cards})


# ---------------------------------------------------------------- settings


@login_required
def settings_view(request):
    profile_form = ProfileForm(instance=request.user)
    password_form = StyledPasswordChangeForm(request.user)
    if request.method == "POST":
        if "profile" in request.POST:
            profile_form = ProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Мәліметтер сақталды.")
                return redirect("settings")
        elif "password" in request.POST:
            password_form = StyledPasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Құпиясөз өзгертілді.")
                return redirect("settings")
    return render(request, "core/settings.html", {"profile_form": profile_form, "password_form": password_form})


def error_403(request, exception=None):
    return render(request, "core/error.html", {"code": 403, "message": "Бұл бетке кіруге рұқсат жоқ."}, status=403)


def error_404(request, exception=None):
    return render(request, "core/error.html", {"code": 404, "message": "Бет табылмады."}, status=404)
