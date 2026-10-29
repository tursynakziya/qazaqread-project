import secrets

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.utils.text import slugify

from .models import Assignment, ClassReading, ReadingSession, SchoolClass, Text, User

INPUT = (
    "w-full px-space-md py-space-sm rounded-xl bg-surface-container-low border border-outline-variant "
    "focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none font-body-md text-body-md text-on-surface"
)


class StyledMixin:
    """Give every widget the platform's input style."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "w-4 h-4 rounded accent-primary")
            else:
                field.widget.attrs.setdefault("class", INPUT)


class LoginForm(StyledMixin, AuthenticationForm):
    username = forms.CharField(label="Электрондық пошта немесе логин", max_length=254)
    password = forms.CharField(label="Құпиясөз", strip=False, widget=forms.PasswordInput)
    remember = forms.BooleanField(label="Мені есте сақтау", required=False, initial=True)

    error_messages = {
        "invalid_login": "Логин немесе құпиясөз қате. Қайта тексеріңіз.",
        "inactive": "Бұл аккаунт белсенді емес.",
    }


class RegisterForm(StyledMixin, forms.Form):
    role = forms.ChoiceField(
        label="Сіздің рөліңіз",
        choices=[c for c in User.Role.choices if c[0] != User.Role.ADMIN],
        initial=User.Role.STUDENT,
    )
    first_name = forms.CharField(label="Аты", max_length=150)
    last_name = forms.CharField(label="Тегі", max_length=150)
    school_name = forms.CharField(label="Мектеп", max_length=200, required=False)
    school_class = forms.ModelChoiceField(
        label="Сынып (оқушылар үшін)", queryset=SchoolClass.objects.all(), required=False, empty_label="— Таңдаңыз —"
    )
    email = forms.EmailField(label="Электрондық пошта")
    password = forms.CharField(label="Құпиясөз жасаңыз", widget=forms.PasswordInput, strip=False)
    agree = forms.BooleanField(label="Пайдалану ережелерімен және құпиялылық саясатымен келісемін")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Бұл пошта бойынша аккаунт бар.")
        return email

    def clean(self):
        data = super().clean()
        if data.get("password"):
            validate_password(data["password"], User(email=data.get("email", ""), first_name=data.get("first_name", "")))
        return data

    def save(self):
        d = self.cleaned_data
        user = User(
            username=unique_username(d["email"].split("@")[0]),
            email=d["email"],
            first_name=d["first_name"],
            last_name=d["last_name"],
            role=d["role"],
            school_name=d.get("school_name", ""),
            school_class=d.get("school_class") if d["role"] == User.Role.STUDENT else None,
        )
        user.set_password(d["password"])
        user.save()
        return user


def unique_username(base):
    base = slugify(base, allow_unicode=False) or "user"
    candidate, n = base, 1
    while User.objects.filter(username=candidate).exists():
        n += 1
        candidate = f"{base}{n}"
    return candidate


class StudentCreateForm(StyledMixin, forms.ModelForm):
    """A teacher adds a student; the student signs in with the QR card code."""

    class Meta:
        model = User
        fields = ["last_name", "first_name"]
        labels = {"last_name": "Тегі", "first_name": "Аты"}

    def __init__(self, *args, school_class=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school_class = school_class
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.STUDENT
        user.school_class = self.school_class
        user.school_name = self.school_class.school if self.school_class else ""
        user.username = unique_username(f"{user.last_name}-{user.first_name}")
        user.set_password(secrets.token_urlsafe(12))
        if commit:
            user.save()
        return user


class SchoolClassForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = ["grade", "letter", "school", "academic_year"]


class AssignmentForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ["text", "due_date"]
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, grade=None, **kwargs):
        super().__init__(*args, **kwargs)
        if grade:
            self.fields["text"].queryset = Text.objects.filter(grade=grade)


class TextChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, text):
        return f"{text.grade}-сынып • «{text.title}» • {text.word_count} сөз"


class LessonForm(StyledMixin, forms.ModelForm):
    text = TextChoiceField(label="Мәтін (барлық оқушы осы мәтінді оқиды)", queryset=Text.objects.order_by("grade", "title"))

    class Meta:
        model = ClassReading
        fields = ["school_class", "text"]

    def __init__(self, *args, teacher, school_class, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["school_class"].queryset = teacher.taught_classes.all()
        self.fields["school_class"].empty_label = None
        self.fields["school_class"].initial = school_class.pk
        self.fields["text"].empty_label = None
        first = Text.objects.filter(grade=school_class.grade).order_by("title").first()
        if first:
            self.fields["text"].initial = first.pk


class TextForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Text
        fields = ["grade", "title", "body", "difficulty"]
        widgets = {"body": forms.Textarea(attrs={"rows": 10})}


class AddChildForm(StyledMixin, forms.Form):
    login_code = forms.CharField(
        label="Баланың кіру коды (QR-картадағы код)",
        max_length=16,
        help_text="Кодты сынып мұғалімінен алуға болады.",
    )

    def clean_login_code(self):
        code = self.cleaned_data["login_code"].strip().lower()
        child = User.objects.filter(login_code=code, role=User.Role.STUDENT).first()
        if child is None:
            raise forms.ValidationError("Мұндай кодпен оқушы табылмады.")
        self.child = child
        return code


class ProfileForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["last_name", "first_name", "email", "school_name"]
        labels = {"last_name": "Тегі", "first_name": "Аты", "email": "Электрондық пошта"}


class StyledPasswordChangeForm(StyledMixin, PasswordChangeForm):
    pass


class CommentForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = ReadingSession
        fields = ["teacher_comment"]
        widgets = {"teacher_comment": forms.Textarea(attrs={"rows": 3, "placeholder": "Оқушыға кеңес жазыңыз…"})}


class QuestionForm(StyledMixin, forms.Form):
    """A question with up to MAX_CHOICES options, exactly one of them correct."""

    MAX_CHOICES = 4

    prompt = forms.CharField(label="Сұрақ", max_length=500, widget=forms.TextInput(attrs={"placeholder": "Мысалы: Отбасында неше адам бар?"}))
    choice_1 = forms.CharField(label="A нұсқасы", max_length=300)
    choice_2 = forms.CharField(label="B нұсқасы", max_length=300)
    choice_3 = forms.CharField(label="C нұсқасы", max_length=300, required=False)
    choice_4 = forms.CharField(label="D нұсқасы", max_length=300, required=False)
    correct = forms.ChoiceField(
        label="Дұрыс жауап",
        choices=[("1", "A"), ("2", "B"), ("3", "C"), ("4", "D")],
        widget=forms.RadioSelect,
        initial="1",
    )
    explanation = forms.CharField(label="Түсіндірме (міндетті емес)", max_length=500, required=False)
    order = forms.IntegerField(label="Реті", min_value=0, initial=0, required=False)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None and "initial" not in kwargs:
            choices = list(instance.choices.all())
            initial = {"prompt": instance.prompt, "explanation": instance.explanation, "order": instance.order}
            for i, c in enumerate(choices[: self.MAX_CHOICES], start=1):
                initial[f"choice_{i}"] = c.label
                if c.is_correct:
                    initial["correct"] = str(i)
            kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.fields["correct"].widget.attrs = {"class": "accent-primary"}

    @property
    def choice_rows(self):
        """(value of the 'correct' radio, letter, bound field) for each option."""
        return [(str(i), "ABCD"[i - 1], self[f"choice_{i}"]) for i in range(1, self.MAX_CHOICES + 1)]

    @property
    def correct_value(self):
        return str(self["correct"].value() or "")

    def clean(self):
        data = super().clean()
        correct = data.get("correct")
        if correct and not data.get(f"choice_{correct}"):
            self.add_error("correct", "Дұрыс жауап ретінде бос емес нұсқаны таңдаңыз.")
        return data

    def save(self, text):
        from .models import Choice, Question

        d = self.cleaned_data
        question = self.instance or Question(text=text)
        question.prompt = d["prompt"]
        question.explanation = d.get("explanation", "")
        question.order = d.get("order") or 0
        question.save()
        question.choices.all().delete()
        Choice.objects.bulk_create(
            Choice(question=question, label=d[f"choice_{i}"], is_correct=str(i) == d["correct"])
            for i in range(1, self.MAX_CHOICES + 1)
            if d.get(f"choice_{i}")
        )
        return question
