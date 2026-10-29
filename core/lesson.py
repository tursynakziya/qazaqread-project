"""
Reading lesson in class: the teacher opens the class list on their computer,
students read the same text for one minute one after another (in register
order), and every result is saved to the student's own account. Afterwards
the teacher gives marks, which students and parents see too.
"""

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import LessonForm
from .models import MARKS, READING_SECONDS, ClassReading, User, grade_norm, int_or_none
from .speech import is_available as speech_available
from .views import role_required, save_reading, teacher_class

MARK_VALUES = {value for value, _ in MARKS}


def get_lesson(request, pk):
    return get_object_or_404(
        ClassReading.objects.select_related("school_class", "text"), pk=pk, school_class__teacher=request.user
    )


def get_lesson_student(lesson, student_id):
    student = lesson.school_class.students.filter(pk=student_id, role=User.Role.STUDENT).first()
    if student is None:
        raise Http404
    return student


@role_required(User.Role.TEACHER)
def lesson_create(request):
    _, current = teacher_class(request)
    if current is None:
        return redirect("class_create")
    form = LessonForm(request.POST or None, teacher=request.user, school_class=current)
    if request.method == "POST" and form.is_valid():
        lesson = form.save(commit=False)
        lesson.teacher = request.user
        lesson.save()
        return redirect(lesson)
    return render(
        request,
        "core/form_page.html",
        {
            "form": form,
            "title": "Сыныпта минуттық оқу",
            "subtitle": "Оқушылар тізім бойынша (әліпби ретімен) кезекпен 1 минут оқиды. Нәтиже әр оқушының кабинетіне сақталады, соңында баға қоясыз.",
            "icon": "groups",
            "submit": "Сабақты бастау",
        },
    )


@role_required(User.Role.TEACHER)
def lesson(request, pk):
    lesson = get_lesson(request, pk)
    students = lesson.students()
    sessions = lesson.latest_sessions()

    if request.method == "POST":
        saved = 0
        for student in students:
            session = sessions.get(student.pk)
            if session is None or f"mark_{student.pk}" not in request.POST:
                continue
            mark = int_or_none(request.POST.get(f"mark_{student.pk}"))
            mark = mark if mark in MARK_VALUES else None
            comment = request.POST.get(f"comment_{student.pk}", "").strip()[:500]
            if mark != session.mark or comment != session.teacher_comment:
                session.mark = mark
                session.marked_at = timezone.now() if mark else None
                session.teacher_comment = comment
                session.save(update_fields=["mark", "marked_at", "teacher_comment"])
            saved += mark is not None
        messages.success(request, f"Бағалар сақталды ({saved} оқушы). Оқушылар мен ата-аналар оларды өз кабинеттерінен көреді.")
        return redirect(lesson)

    absent = set(lesson.absent.values_list("pk", flat=True))
    rows = [
        {"n": i, "student": st, "session": sessions.get(st.pk), "absent": st.pk in absent}
        for i, st in enumerate(students, 1)
    ]
    waiting = [r for r in rows if not r["session"] and not r["absent"]]
    return render(
        request,
        "core/lesson.html",
        {
            "lesson": lesson,
            "rows": rows,
            "next_row": waiting[0] if waiting else None,
            "read_count": len(sessions),
            "total": len(rows),
            "all_done": not waiting,
            "just_read": sessions.get(int_or_none(request.GET.get("done"))),
            "marks": MARKS,
            "norm": grade_norm(lesson.text.grade),
        },
    )


@role_required(User.Role.TEACHER)
@require_POST
def lesson_absent(request, pk, student_id):
    lesson = get_lesson(request, pk)
    student = get_lesson_student(lesson, student_id)
    if lesson.absent.filter(pk=student.pk).exists():
        lesson.absent.remove(student)
    else:
        lesson.absent.add(student)
    return redirect(lesson)


@role_required(User.Role.TEACHER)
def lesson_read(request, pk, student_id):
    lesson = get_lesson(request, pk)
    student = get_lesson_student(lesson, student_id)
    students = lesson.students()
    low, high = grade_norm(lesson.text.grade)
    return render(
        request,
        "core/reading.html",
        {
            "text": lesson.text,
            "norm_low": low,
            "norm_high": high,
            "server_speech": speech_available(),
            "reading_seconds": READING_SECONDS,
            "submit_url": reverse("lesson_submit", args=[lesson.pk, student.pk]),
            "lesson": lesson,
            "reader": student,
            "position": students.index(student) + 1,
            "total": len(students),
        },
    )


@role_required(User.Role.TEACHER)
@require_POST
def lesson_submit(request, pk, student_id):
    lesson = get_lesson(request, pk)
    student = get_lesson_student(lesson, student_id)
    save_reading(request, lesson.text, student, class_reading=lesson)
    lesson.absent.remove(student)
    url = f"{reverse('lesson', args=[lesson.pk])}?done={student.pk}"
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"redirect": url})
    return redirect(url)
