"""Numbers and chart geometry for the dashboards."""

from datetime import timedelta

from django.db.models import Avg, Count, Sum
from django.utils import timezone

from .models import ReadingSession, grade_norm

MONTHLY_GOAL = 15
DAILY_MINUTES_GOAL = 15
WEEKDAYS = ["Дс", "Сс", "Ср", "Бс", "Жм", "Сн", "Жс"]


def local_today():
    return timezone.localdate()


def week_start(day=None):
    day = day or local_today()
    return day - timedelta(days=day.weekday())


def streak_days(sessions):
    days = {timezone.localtime(s.created_at).date() for s in sessions}
    day, streak = local_today(), 0
    if day not in days:
        day -= timedelta(days=1)
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def line_chart(values, labels, target=None, width=500, height=200, pad=30):
    """Return SVG coordinates for a simple line chart."""
    if not values:
        return None
    top = max(values + ([target] if target else [])) * 1.15 or 1
    step = (width - 2 * pad) / max(len(values) - 1, 1)

    def y(v):
        return round(height - 20 - (v / top) * (height - 40), 1)

    points = [
        {"x": round(pad + i * step, 1), "y": y(v), "value": round(v), "label": labels[i]}
        for i, v in enumerate(values)
    ]
    line = " ".join(f"{'M' if i == 0 else 'L'} {p['x']},{p['y']}" for i, p in enumerate(points))
    area = f"{line} L {points[-1]['x']},{height - 20} L {points[0]['x']},{height - 20} Z"
    return {
        "points": points,
        "last": points[-1],
        "line": line,
        "area": area,
        "target_y": y(target) if target else None,
        "target": target,
        "width": width,
        "height": height,
    }


def student_summary(student):
    sessions = list(student.sessions.select_related("text").order_by("-created_at"))
    low, high = grade_norm(student.grade)
    today = local_today()
    this_week = [s for s in sessions if timezone.localtime(s.created_at).date() >= week_start(today)]
    last_week = [
        s
        for s in sessions
        if week_start(today) - timedelta(days=7) <= timezone.localtime(s.created_at).date() < week_start(today)
    ]

    def avg(items, attr):
        vals = [getattr(s, attr) for s in items if s.words_total]
        return round(sum(vals) / len(vals), 1) if vals else 0

    month_count = sum(
        1 for s in sessions if timezone.localtime(s.created_at).date().replace(day=1) == today.replace(day=1)
    )
    total_seconds = sum(s.duration_seconds for s in sessions)
    active_days = len({timezone.localtime(s.created_at).date() for s in sessions}) or 1

    recent = list(reversed(sessions[:7]))
    chart = line_chart(
        [s.wpm for s in recent],
        [timezone.localtime(s.created_at).strftime("%d.%m") for s in recent],
        target=high or None,
    )

    return {
        "sessions": sessions,
        "count": len(sessions),
        "last": sessions[0] if sessions else None,
        "speed_delta": round(avg(this_week, "wpm") - avg(last_week, "wpm"), 1) if this_week and last_week else None,
        "accuracy": avg(sessions[:10], "accuracy"),
        "month_count": month_count,
        "month_goal": MONTHLY_GOAL,
        "month_percent": min(100, round(100 * month_count / MONTHLY_GOAL)),
        "total_minutes": round(total_seconds / 60),
        "minutes_per_day": round(total_seconds / 60 / active_days, 1),
        "streak": streak_days(sessions),
        "norm_low": low,
        "norm_high": high,
        "chart": chart,
        "week_count": len(this_week),
    }


def weekly_minutes(student):
    start = week_start()
    rows = (
        student.sessions.filter(created_at__date__gte=start)
        .values_list("created_at", "duration_seconds")
    )
    minutes = [0.0] * 7
    for created, seconds in rows:
        day = timezone.localtime(created).date()
        idx = (day - start).days
        if 0 <= idx < 7:
            minutes[idx] += seconds / 60
    peak = max(minutes + [DAILY_MINUTES_GOAL]) or 1
    today_idx = local_today().weekday()
    return {
        "days": [
            {
                "label": WEEKDAYS[i],
                "minutes": round(m),
                "height": round(100 * m / peak),
                "today": i == today_idx,
            }
            for i, m in enumerate(minutes)
        ],
        "goal_height": round(100 * DAILY_MINUTES_GOAL / peak),
        "goal": DAILY_MINUTES_GOAL,
        "total": round(sum(minutes)),
    }


def class_rows(school_class, query="", sort="speed"):
    """One row per student with their latest session and averages."""
    students = school_class.students.filter(role="student").annotate(
        avg_wpm=Avg("sessions__wpm"),
        avg_accuracy=Avg("sessions__accuracy"),
        session_count=Count("sessions"),
    )
    if query:
        students = [s for s in students if query.lower() in s.display_name.lower()]
    low, high = school_class.norm
    rows = []
    for st in students:
        last = st.sessions.select_related("text").first()
        rows.append({"student": st, "last": last, "level": last.level if last else ("Әлі оқымаған", "none")})
    keys = {
        "speed": lambda r: -(r["last"].wpm if r["last"] else -1),
        "accuracy": lambda r: -(r["last"].accuracy if r["last"] else -1),
        "name": lambda r: r["student"].display_name,
    }
    rows.sort(key=keys.get(sort, keys["speed"]))
    return rows


def class_summary(school_class):
    sessions = ReadingSession.objects.filter(student__school_class=school_class)
    agg = sessions.aggregate(wpm=Avg("wpm"), accuracy=Avg("accuracy"), seconds=Sum("duration_seconds"))
    week = sessions.filter(created_at__date__gte=week_start()).count()
    prev = sessions.filter(
        created_at__date__gte=week_start() - timedelta(days=7), created_at__date__lt=week_start()
    ).count()
    low, high = school_class.norm
    return {
        "students": school_class.students.count(),
        "sessions": sessions.count(),
        "week_sessions": week,
        "week_growth": round(100 * (week - prev) / prev) if prev else None,
        "avg_wpm": round(agg["wpm"] or 0, 1),
        "avg_accuracy": round(agg["accuracy"] or 0, 1),
        "norm_low": low,
        "norm_high": high,
        "above_norm": round((agg["wpm"] or 0) - low, 1),
    }
