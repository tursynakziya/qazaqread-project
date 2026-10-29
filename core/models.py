import re
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.urls import reverse
from django.utils import timezone

# Reading-speed norms (words per minute) for primary grades.
# One source of truth for every page that shows a norm.
# Reading speed is measured over one minute: recording stops automatically after this.
READING_SECONDS = 60

def int_or_none(value):
    """Parse an id or number from a query string; junk gives None instead of a server error."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


GRADE_NORMS = {
    1: (25, 30),
    2: (40, 50),
    3: (50, 60),
    4: (60, 75),
}

WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)


def grade_norm(grade):
    return GRADE_NORMS.get(grade, (0, 0))


def split_words(text):
    """Split text into words, keeping hyphenated words together."""
    return [w for w in WORD_RE.findall(text) if w.strip("-")]


class SchoolClass(models.Model):
    grade = models.PositiveSmallIntegerField("Сынып", choices=[(g, f"{g}-сынып") for g in GRADE_NORMS])
    letter = models.CharField("Литер", max_length=2)
    school = models.CharField("Мектеп", max_length=200, blank=True)
    academic_year = models.CharField("Оқу жылы", max_length=9, default="2026-2027")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Мұғалім",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="taught_classes",
        limit_choices_to={"role": "teacher"},
    )

    class Meta:
        verbose_name = "Сынып"
        verbose_name_plural = "Сыныптар"
        ordering = ["grade", "letter"]

    def __str__(self):
        return f"{self.grade} «{self.letter}»"

    @property
    def norm(self):
        return grade_norm(self.grade)


def new_login_code():
    return uuid.uuid4().hex[:10]


class QazaqUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", "admin")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "student", "Оқушы"
        PARENT = "parent", "Ата-ана"
        TEACHER = "teacher", "Мұғалім"
        ADMIN = "admin", "Әкімші"

    role = models.CharField("Рөл", max_length=10, choices=Role.choices, default=Role.STUDENT)
    school_name = models.CharField("Мектеп", max_length=200, blank=True)
    school_class = models.ForeignKey(
        SchoolClass,
        verbose_name="Сынып",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="students",
    )
    children = models.ManyToManyField(
        "self",
        verbose_name="Балалары",
        symmetrical=False,
        related_name="parents",
        blank=True,
        limit_choices_to={"role": "student"},
    )
    # Code printed on the student's QR card; /qr/<code>/ signs the student in.
    login_code = models.CharField("Кіру коды", max_length=16, unique=True, default=new_login_code)

    objects = QazaqUserManager()

    class Meta:
        verbose_name = "Пайдаланушы"
        verbose_name_plural = "Пайдаланушылар"

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        full = f"{self.first_name} {self.last_name}".strip()
        return full or self.username

    @property
    def short_name(self):
        return self.first_name or self.username

    @property
    def initials(self):
        parts = [p[0] for p in (self.first_name, self.last_name) if p]
        return "".join(parts).upper() or self.username[:2].upper()

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_parent(self):
        return self.role == self.Role.PARENT

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def grade(self):
        return self.school_class.grade if self.school_class else None

    def regenerate_login_code(self):
        self.login_code = new_login_code()
        self.save(update_fields=["login_code"])


class Text(models.Model):
    class Difficulty(models.TextChoices):
        EASY = "easy", "Жеңіл"
        MEDIUM = "medium", "Орташа"
        HARD = "hard", "Күрделі"

    class Topic(models.TextChoices):
        NATURE = "nature", "Табиғат пен экология"
        HOMELAND = "homeland", "Отан және туған жер"
        FAMILY = "family", "Отбасы және достық"
        TALES = "tales", "Ертегілер мен аңыздар"
        SCIENCE = "science", "Ғылым және өнертабыс"
        TRADITION = "tradition", "Қазақ салт-дәстүрі"

    class Genre(models.TextChoices):
        FICTION = "fiction", "Көркем әдебиет"
        SCIENCE = "science", "Ғылыми-танымдық"
        MORAL = "moral", "Тәрбиелік"

    title = models.CharField("Атауы", max_length=200)
    body = models.TextField("Мәтін")
    summary = models.CharField("Қысқаша сипаттама", max_length=300, blank=True)
    grade = models.PositiveSmallIntegerField("Сынып", choices=[(g, f"{g}-сынып") for g in GRADE_NORMS])
    difficulty = models.CharField("Күрделілігі", max_length=10, choices=Difficulty.choices, default=Difficulty.MEDIUM)
    topic = models.CharField("Тақырып", max_length=20, choices=Topic.choices, default=Topic.NATURE)
    genre = models.CharField("Жанр", max_length=20, choices=Genre.choices, default=Genre.FICTION)
    word_count = models.PositiveIntegerField("Сөз саны", default=0, editable=False)
    is_featured = models.BooleanField("Күннің мәтіні", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Мәтін"
        verbose_name_plural = "Мәтіндер"
        ordering = ["grade", "title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.word_count = len(split_words(self.body))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("reading", args=[self.pk])

    @property
    def words(self):
        return split_words(self.body)

    @property
    def tokens(self):
        """Body as a list of (token, word_index or None) so templates can mark words."""
        result, index = [], 0
        for part in re.split(r"([\w\-]+)", self.body):
            if not part:
                continue
            if WORD_RE.fullmatch(part) and part.strip("-"):
                result.append((part, index))
                index += 1
            else:
                result.append((part, None))
        return result

    @property
    def minutes_estimate(self):
        low, high = grade_norm(self.grade)
        speed = (low + high) / 2 or 50
        return round(self.word_count / speed, 1)

    @property
    def question_count(self):
        return self.questions.count()

    @property
    def excerpt(self):
        return self.summary or (self.body[:160] + "…" if len(self.body) > 160 else self.body)


class Assignment(models.Model):
    text = models.ForeignKey(Text, verbose_name="Мәтін", on_delete=models.CASCADE, related_name="assignments")
    school_class = models.ForeignKey(SchoolClass, verbose_name="Сынып", on_delete=models.CASCADE, related_name="assignments")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    due_date = models.DateField("Мерзімі", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Тапсырма"
        verbose_name_plural = "Тапсырмалар"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.school_class}: {self.text}"


def audio_upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "webm"
    return f"recordings/{timezone.now():%Y/%m}/{instance.student_id}_{uuid.uuid4().hex[:8]}.{ext}"


MARKS = [(5, "5 — өте жақсы"), (4, "4 — жақсы"), (3, "3 — қанағаттанарлық"), (2, "2 — қанағаттанарлықсыз")]


KAZAKH_ALPHABET = "аәбвгғдеёжзийкқлмнңоөпрстуұүфхһцчшщъыіьэюя"
_KAZAKH_ORDER = {ch: i for i, ch in enumerate(KAZAKH_ALPHABET)}


def kazakh_sort_key(value):
    """Sort Kazakh words in alphabet order (plain Unicode order puts ә, ғ, қ, ң, ө, ұ, ү, і at the end)."""
    return [_KAZAKH_ORDER.get(ch, 100 + ord(ch)) for ch in value.lower()]


def alphabetical(students):
    """Students in class-register order: surname, then first name."""
    return sorted(students, key=lambda s: (kazakh_sort_key(s.last_name), kazakh_sort_key(s.first_name), s.username))


class ClassReading(models.Model):
    """A lesson where the whole class reads the same text one by one on the teacher's computer."""

    school_class = models.ForeignKey(SchoolClass, verbose_name="Сынып", on_delete=models.CASCADE, related_name="class_readings")
    text = models.ForeignKey(Text, verbose_name="Мәтін", on_delete=models.CASCADE, related_name="class_readings")
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    absent = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+", verbose_name="Келмегендер")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Сыныпта оқу"
        verbose_name_plural = "Сыныпта оқу сабақтары"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.school_class} — {self.text} ({self.created_at:%d.%m.%Y})"

    def get_absolute_url(self):
        return reverse("lesson", args=[self.pk])

    def students(self):
        return alphabetical(self.school_class.students.filter(role="student"))

    def latest_sessions(self):
        """Student id -> their last reading in this lesson."""
        result = {}
        for session in self.sessions.order_by("created_at"):
            result[session.student_id] = session
        return result


class ReadingSession(models.Model):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Аяқталды"
        NEEDS_REVIEW = "review", "Мұғалім тексеруі қажет"

    student = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Оқушы", on_delete=models.CASCADE, related_name="sessions")
    text = models.ForeignKey(Text, verbose_name="Мәтін", on_delete=models.CASCADE, related_name="sessions")
    assignment = models.ForeignKey(Assignment, on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions")
    audio = models.FileField("Аудиожазба", upload_to=audio_upload_path, blank=True)
    transcript = models.TextField("Танылған мәтін", blank=True)
    duration_seconds = models.FloatField("Ұзақтығы (сек)", default=0)
    words_total = models.PositiveIntegerField(default=0)
    words_correct = models.PositiveIntegerField(default=0)
    words_review = models.PositiveIntegerField(default=0)
    words_skipped = models.PositiveIntegerField(default=0)
    wpm = models.FloatField("Жылдамдық (сөз/мин)", default=0)
    accuracy = models.FloatField("Дәлдік (%)", default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COMPLETED)
    teacher_comment = models.TextField("Мұғалім пікірі", blank=True)
    class_reading = models.ForeignKey(
        ClassReading, verbose_name="Сыныпта оқу", on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions"
    )
    mark = models.PositiveSmallIntegerField("Баға", choices=MARKS, null=True, blank=True)
    marked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Оқу сессиясы"
        verbose_name_plural = "Оқу сессиялары"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.student} — {self.text} ({self.created_at:%d.%m.%Y})"

    def get_absolute_url(self):
        return reverse("result", args=[self.pk])

    @property
    def norm(self):
        return grade_norm(self.text.grade)

    @property
    def level(self):
        """Return (label, css-tone) for speed against the grade norm."""
        low, high = self.norm
        if self.wpm >= high:
            return "Үздік", "good"
        if self.wpm >= low:
            return "Нормада", "good"
        if self.wpm >= low * 0.8:
            return "Нормаға жақын", "mid"
        return "Көмек қажет", "low"

    @property
    def suggested_mark(self):
        """A starting point for the teacher: speed against the grade norm, and accuracy."""
        low, _ = self.norm
        if self.wpm >= low and self.accuracy >= 90:
            return 5
        if self.wpm >= low * 0.8 and self.accuracy >= 75:
            return 4
        if self.wpm >= low * 0.5:
            return 3
        return 2

    @property
    def duration_display(self):
        total = int(round(self.duration_seconds))
        return f"{total // 60:02d}:{total % 60:02d}"

    def recalculate(self):
        """Refresh counters from word results (after analysis or teacher review)."""
        words = list(self.word_results.all())
        self.words_total = len(words)
        self.words_correct = sum(w.status == WordResult.Status.CORRECT for w in words)
        self.words_review = sum(w.status == WordResult.Status.MISREAD for w in words)
        self.words_skipped = sum(w.status == WordResult.Status.SKIPPED for w in words)
        minutes = self.duration_seconds / 60 if self.duration_seconds else 0
        self.wpm = round(self.words_correct / minutes, 1) if minutes else 0
        self.accuracy = round(100 * self.words_correct / self.words_total, 1) if self.words_total else 0
        self.save()


class WordResult(models.Model):
    class Status(models.TextChoices):
        CORRECT = "correct", "Дұрыс"
        MISREAD = "misread", "Тексеру қажет"
        SKIPPED = "skipped", "Өткізіп алынған"

    session = models.ForeignKey(ReadingSession, on_delete=models.CASCADE, related_name="word_results")
    position = models.PositiveIntegerField()
    expected = models.CharField(max_length=100)
    heard = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)

    class Meta:
        ordering = ["position"]
        unique_together = [("session", "position")]

    def __str__(self):
        return f"{self.expected} → {self.heard or '—'} ({self.get_status_display()})"


class Question(models.Model):
    """A comprehension question asked after the text is read."""

    text = models.ForeignKey(Text, verbose_name="Мәтін", on_delete=models.CASCADE, related_name="questions")
    prompt = models.CharField("Сұрақ", max_length=500)
    explanation = models.CharField("Түсіндірме (жауаптан кейін көрсетіледі)", max_length=500, blank=True)
    order = models.PositiveSmallIntegerField("Реті", default=0)

    class Meta:
        verbose_name = "Тест сұрағы"
        verbose_name_plural = "Тест сұрақтары"
        ordering = ["order", "pk"]

    def __str__(self):
        return self.prompt

    @property
    def correct_choice(self):
        return next((c for c in self.choices.all() if c.is_correct), None)


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    label = models.CharField("Жауап нұсқасы", max_length=300)
    is_correct = models.BooleanField("Дұрыс жауап", default=False)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.label


class QuizAttempt(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Оқушы", on_delete=models.CASCADE, related_name="quiz_attempts")
    text = models.ForeignKey(Text, verbose_name="Мәтін", on_delete=models.CASCADE, related_name="quiz_attempts")
    session = models.ForeignKey(
        ReadingSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="quiz_attempts"
    )
    correct = models.PositiveSmallIntegerField("Дұрыс жауаптар", default=0)
    total = models.PositiveSmallIntegerField("Сұрақ саны", default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Тест нәтижесі"
        verbose_name_plural = "Тест нәтижелері"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.student} — {self.text}: {self.correct}/{self.total}"

    @property
    def percent(self):
        return round(100 * self.correct / self.total) if self.total else 0


class AttemptAnswer(models.Model):
    attempt = models.ForeignKey(QuizAttempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="+")
    choice = models.ForeignKey(Choice, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    is_correct = models.BooleanField(default=False)
