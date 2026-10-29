from django.contrib.auth import views as auth_views
from django.urls import path

from . import lesson, panel, views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.QazaqLoginView.as_view(), name="login"),
    path("register/", views.register, name="register"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="core/auth_form.html",
            email_template_name="core/email/password_reset.txt",
            subject_template_name="core/email/password_reset_subject.txt",
            extra_context={"title": "Құпиясөзді қалпына келтіру", "submit": "Сілтеме жіберу"},
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="core/auth_message.html",
            extra_context={"title": "Хат жіберілді", "text": "Поштаңызды тексеріңіз: құпиясөзді өзгерту сілтемесі жіберілді."},
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="core/auth_form.html",
            extra_context={"title": "Жаңа құпиясөз", "submit": "Сақтау"},
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="core/auth_message.html",
            extra_context={"title": "Дайын!", "text": "Құпиясөз өзгертілді. Енді жүйеге кіре аласыз."},
        ),
        name="password_reset_complete",
    ),
    path("qr/", views.qr_code_login, name="qr_code_login"),
    path("qr/<str:code>/", views.qr_login, name="qr_login"),
    # student
    path("student/", views.student_dashboard, name="student_dashboard"),
    path("library/", views.library, name="library"),
    path("read/<int:pk>/", views.reading, name="reading"),
    path("read/<int:pk>/submit/", views.submit_reading, name="submit_reading"),
    path("read/<int:pk>/live/", views.live_recognize, name="live_recognize"),
    path("results/", views.results_list, name="results"),
    path("results/<int:pk>/", views.result_detail, name="result"),
    path("results/<int:pk>/audio/", views.session_audio, name="session_audio"),
    path("results/<int:pk>/word/<int:position>/", views.review_word, name="review_word"),
    path("results/<int:pk>/comment/", views.session_comment, name="session_comment"),
    path("students/<int:student_id>/results/", views.results_list, name="student_results"),
    path("students/<int:student_id>/report/", views.student_report, name="student_report"),
    path("read/<int:pk>/quiz/", views.quiz, name="quiz"),
    path("quiz/<int:pk>/", views.quiz_result, name="quiz_result"),
    # parent
    path("parent/", views.parent_dashboard, name="parent_dashboard"),
    path("parent/add-child/", views.add_child, name="add_child"),
    # teacher
    path("teacher/", views.teacher_dashboard, name="teacher_dashboard"),
    path("teacher/class/new/", views.class_create, name="class_create"),
    path("teacher/students/new/", views.student_add, name="student_add"),
    path("teacher/assign/", views.assign_text, name="assign_text"),
    path("teacher/texts/new/", views.text_create, name="text_create"),
    path("teacher/export.csv", views.export_csv, name="export_csv"),
    path("teacher/qr-cards/", views.qr_cards, name="qr_cards"),
    path("teacher/lessons/new/", lesson.lesson_create, name="lesson_create"),
    path("teacher/lessons/<int:pk>/", lesson.lesson, name="lesson"),
    path("teacher/lessons/<int:pk>/read/<int:student_id>/", lesson.lesson_read, name="lesson_read"),
    path("teacher/lessons/<int:pk>/read/<int:student_id>/submit/", lesson.lesson_submit, name="lesson_submit"),
    path("teacher/lessons/<int:pk>/absent/<int:student_id>/", lesson.lesson_absent, name="lesson_absent"),
    # admin panel
    path("panel/", panel.dashboard, name="panel_dashboard"),
    path("panel/texts/new/", panel.text_edit, name="panel_text_create"),
    path("panel/texts/<int:pk>/edit/", panel.text_edit, name="panel_text_edit"),
    path("panel/texts/<int:pk>/delete/", panel.text_delete, name="panel_text_delete"),
    path("panel/texts/<int:pk>/questions/", panel.questions, name="panel_questions"),
    path("panel/questions/<int:pk>/edit/", panel.question_edit, name="panel_question_edit"),
    path("panel/questions/<int:pk>/delete/", panel.question_delete, name="panel_question_delete"),
    path("panel/users/", panel.users, name="panel_users"),
    path("panel/users/<int:pk>/role/", panel.user_role, name="panel_user_role"),
    path("panel/users/<int:pk>/password/", panel.user_password, name="panel_user_password"),
    path("panel/quiz-results/", panel.quiz_results, name="panel_quiz_results"),
    # common
    path("settings/", views.settings_view, name="settings"),
]
