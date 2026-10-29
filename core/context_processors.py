from django.urls import reverse

from .models import grade_norm

NAV = {
    "student": [
        ("student_dashboard", "grid_view", "Басты бет"),
        ("library", "menu_book", "Мәтіндер кітапханасы"),
        ("results", "insights", "Менің нәтижелерім"),
        ("settings", "settings", "Баптаулар"),
    ],
    "parent": [
        ("parent_dashboard", "family_restroom", "Ата-ана кабинеті"),
        ("library", "menu_book", "Мәтіндер кітапханасы"),
        ("settings", "settings", "Баптаулар"),
    ],
    "admin": [
        ("panel_dashboard", "admin_panel_settings", "Әкімші панелі"),
        ("panel_text_create", "post_add", "Мәтін қосу"),
        ("panel_quiz_results", "quiz", "Тест нәтижелері"),
        ("panel_users", "group", "Пайдаланушылар"),
        ("library", "menu_book", "Мәтіндер кітапханасы"),
        ("settings", "settings", "Баптаулар"),
    ],
    "teacher": [
        ("teacher_dashboard", "school", "Мұғалім кабинеті"),
        ("library", "menu_book", "Мәтіндер кітапханасы"),
        ("text_create", "post_add", "Мәтін қосу"),
        ("qr_cards", "qr_code_2", "QR-карталар"),
        ("settings", "settings", "Баптаулар"),
    ],
}


def navigation(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    match = getattr(request, "resolver_match", None)
    current = match.url_name if match else ""
    items = [
        {"url": reverse(name), "icon": icon, "label": label, "active": name == current}
        for name, icon, label in NAV.get(user.role, [])
    ]
    if user.is_student and user.grade:
        subtitle = f"{user.grade}-сынып оқушысы"
        norm_grade = user.grade
    elif user.is_teacher:
        subtitle = "Бастауыш сынып мұғалімі"
        first = user.taught_classes.first()
        norm_grade = first.grade if first else None
    elif user.is_parent:
        subtitle = "Ата-ана"
        child = user.children.select_related("school_class").first()
        norm_grade = child.grade if child else None
    else:
        subtitle, norm_grade = user.get_role_display(), None
    low, high = grade_norm(norm_grade)
    return {
        "nav_items": items,
        "nav_subtitle": subtitle,
        "nav_norm": {"grade": norm_grade, "low": low, "high": high} if norm_grade else None,
    }
