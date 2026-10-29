from datetime import timedelta

from django import template
from django.utils import timezone

register = template.Library()

MONTHS = ["қаң", "ақп", "нау", "сәу", "мам", "мау", "шіл", "там", "қыр", "қаз", "қар", "жел"]


@register.filter
def when(value):
    """'Бүгін, 10:30' / 'Кеше, 16:45' / '3 күн бұрын' / '12 қаз'."""
    if not value:
        return ""
    local = timezone.localtime(value)
    today = timezone.localdate()
    days = (today - local.date()).days
    if days == 0:
        return f"Бүгін, {local:%H:%M}"
    if days == 1:
        return f"Кеше, {local:%H:%M}"
    if days < 7:
        return f"{days} күн бұрын"
    return f"{local.day} {MONTHS[local.month - 1]} {local.year}" if local.year != today.year else f"{local.day} {MONTHS[local.month - 1]}"


@register.filter
def num(value, digits=0):
    """Round a number for display; drop the trailing .0."""
    try:
        value = round(float(value), int(digits))
    except (TypeError, ValueError):
        return value
    return int(value) if float(value).is_integer() else value


@register.filter
def signed(value):
    try:
        value = num(value, 1)
        return f"+{value}" if value > 0 else str(value)
    except TypeError:
        return value


@register.filter
def tone_classes(tone):
    return {
        "good": "bg-secondary-container text-on-secondary-container",
        "mid": "bg-tertiary-fixed text-on-tertiary-fixed",
        "low": "bg-error-container text-on-error-container",
    }.get(tone, "bg-surface-container-high text-on-surface-variant")


@register.filter
def heard(value):
    """Speech recognition marks words it could not make out as "[unk]"."""
    return str(value).replace("[unk]", "(түсініксіз)") if value else value


@register.filter
def heard_word(value):
    return "түсініксіз" if value == "unk" else value
