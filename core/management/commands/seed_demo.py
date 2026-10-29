import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.analysis import analyze_session
from core.models import Assignment, Choice, Question, ReadingSession, SchoolClass, Text, User, READING_SECONDS, grade_norm

DEMO_PASSWORD = "qazaqread123"

TEXTS = [
    {
        "title": "Менің отбасым", "grade": 3, "difficulty": "easy", "topic": "family", "genre": "moral",
        "summary": "Үлкен әрі тату отбасы туралы шағын әңгіме.",
        "body": "Менің отбасым үлкен әрі тату. Біз Алматы қаласында тұрамыз. Отбасымызда бес адам бар: әкем, анам, "
                "ағам, мен және кішкентай қарындасым. Әкем құрылысшы инженер, ол жаңа ғимараттар салады. Анам мектепте "
                "қазақ тілі мен әдебиеті пәнінің мұғалімі. Ол өте мейірімді және бізге күн сайын қызықты ертегілер оқып "
                "береді. Біз бос уақытымызда саябақта серуендеп, бірге кітап оқимыз. Табиғат аясында демалғанды бәріміз "
                "жақсы көреміз.",
    },
    {
        "title": "Алатау баурайында", "grade": 3, "difficulty": "medium", "topic": "nature", "genre": "fiction",
        "is_featured": True,
        "summary": "Тау табиғатының сұлулығы мен тыныштығы туралы суреттеме.",
        "body": "Көк аспанмен таласқан асқар таулар баурайында жасыл шыршалар жайқалып тұр. Таудан сылдырап аққан таза "
                "бұлақ суы сыр шерткендей. Табиғаттың тыныштығы адамға ерекше шабыт пен күш-қуат сыйлайды. Жазда "
                "баурайды түрлі-түсті гүлдер көмкереді. Аралары гүлден гүлге қонып, бал жинайды. Ағаш басында құстар "
                "сайрап, әсем ән салады. Кешке қарай күн батып, таудың ақ басы қызғылт түске боялады. Мұндай сұлулықты "
                "көрген адам туған жерін бұрынғыдан да қатты сүйеді.",
    },
    {
        "title": "Туған жерім", "grade": 3, "difficulty": "medium", "topic": "homeland", "genre": "fiction",
        "summary": "Отанды сүю, кең байтақ даламыздың табиғаты жайлы көркем әңгіме.",
        "body": "Туған жер адамға анадай ыстық. Біздің еліміз кең әрі бай. Батысында Каспий теңізі толқындайды, "
                "шығысында Алтай таулары биік көтеріледі. Оңтүстігінде мақта мен жеміс өседі, солтүстігінде бидай "
                "алқаптары жайқалады. Даламызда жылқы, қой, түйе өрістейді. Біз өз Отанымызды мақтан тұтамыз. Жақсы "
                "оқып, еңбек етсек, еліміз одан әрі гүлдене береді.",
    },
    {
        "title": "Табиғатты қорғайық", "grade": 3, "difficulty": "medium", "topic": "nature", "genre": "moral",
        "summary": "Қоршаған ортаны аялау, ағаш егу және тазалық сақтау туралы мәтін.",
        "body": "Көктем келгенде біздің сынып мектеп ауласына ағаш ектік. Әр оқушы бір көшеттен отырғызып, оған су "
                "құйды. Мұғаліміміз ағаштың адамға қандай пайдасы бар екенін айтып берді. Ағаш ауаны тазартады, күннің "
                "ыстығынан қорғайды, құстарға үй болады. Біз қоқысты жерге тастамауға, суды үнемдеуге уәде бердік. "
                "Табиғатты қорғау әр адамның міндеті.",
    },
    {
        "title": "Кітаптың пайдасы", "grade": 3, "difficulty": "easy", "topic": "science", "genre": "moral",
        "summary": "Кітап білім бұлағы екені туралы.",
        "body": "Кітап білім бұлағы. Кітап оқыған бала көп нәрсені біледі. Ол басқа елдер туралы, жануарлар мен өсімдіктер "
                "туралы оқиды. Кітап адамды ойлауға, армандауға үйретеді. Күн сайын аз да болса кітап оқу пайдалы. "
                "Кітапты күтіп ұстау керек: бетін бүктемеу, үстіне сызбау қажет.",
    },
    {
        "title": "Бәйтерек аңызы", "grade": 4, "difficulty": "hard", "topic": "tales", "genre": "fiction",
        "summary": "Өмір ағашы мен Самұрық құсы туралы ежелгі аңыз.",
        "body": "Ерте заманда дүниенің ортасында алып Бәйтерек ағашы өсіпті. Оның тамыры жердің түбіне, ал басы көкке "
                "жетіпті. Жыл сайын ағаштың ұшар басына қасиетті Самұрық құсы ұшып келіп, алтын жұмыртқа салады екен. "
                "Ол жұмыртқа күнді бейнелейді деседі. Ағаш түбінде айдаһар жатып, жыл сайын сол жұмыртқаны жұтып қояды. "
                "Осылайша жаз бен қыс, күн мен түн алмасып отырады. Бұл аңыз адамдардың табиғат заңдарын түсінуге "
                "ұмтылғанын көрсетеді.",
    },
    {
        "title": "Жыл мезгілдері", "grade": 2, "difficulty": "easy", "topic": "nature", "genre": "science",
        "summary": "Төрт мезгілдің ерекшеліктері.",
        "body": "Жылда төрт мезгіл бар. Көктемде қар ериді, ағаштар бүршік жарады. Жазда күн ыстық болады, балалар "
                "өзенге шомылады. Күзде жапырақтар сарғайып түседі, егін жиналады. Қыста қар жауып, айнала аппақ "
                "болады. Әр мезгілдің өз сұлулығы бар.",
    },
    {
        "title": "Дала сыры", "grade": 4, "difficulty": "medium", "topic": "nature", "genre": "fiction",
        "summary": "Кең даланың тыныс-тіршілігі.",
        "body": "Кең далада жусанның иісі аңқиды. Таң атқанда бозторғай шырқап, күн шуағы жер бетін жылытады. Алыстан "
                "жылқы үйірі көрінеді. Құлындар енесінің қасында ойнақтайды. Түсте ыстық аптап басталып, жел де "
                "тынады. Кешке қарай салқын самал соғып, аспанда жұлдыздар жымыңдайды. Дала өз сырын тек оны сүйетін "
                "адамға ғана ашады.",
    },
    {
        "title": "Менің мысығым", "grade": 1, "difficulty": "easy", "topic": "family", "genre": "fiction",
        "summary": "Кішкентай мысық туралы.",
        "body": "Менің мысығым бар. Оның аты Мырзабек. Мырзабек ақ әрі жұмсақ. Ол сүт ішкенді жақсы көреді. Біз бірге "
                "ойнаймыз.",
    },
    {
        "title": "Наурыз мерекесі", "grade": 2, "difficulty": "medium", "topic": "tradition", "genre": "science",
        "summary": "Ұлыстың ұлы күні — Наурыз туралы.",
        "body": "Наурыз көктемнің алғашқы мерекесі. Бұл күні күн мен түн теңеледі. Адамдар бір-біріне жақсы тілек "
                "айтады. Әр үйде наурыз көже пісіріледі. Көже жеті түрлі дәмнен жасалады. Балалар ойын ойнап, ән "
                "айтады. Үлкендер жастарға бата береді.",
    },
    {
        "title": "Ғарышқа саяхат", "grade": 4, "difficulty": "hard", "topic": "science", "genre": "science",
        "summary": "Байқоңыр және алғашқы қазақ ғарышкерлері.",
        "body": "Қазақстан жерінде Байқоңыр ғарыш айлағы орналасқан. Дәл осы жерден адамзат тарихындағы алғашқы ғарыш "
                "кемесі ұшырылды. Қазақтың тұңғыш ғарышкері Тоқтар Әубәкіров мың тоғыз жүз тоқсан бірінші жылы "
                "ғарышқа ұшты. Одан кейін Талғат Мұсабаев ғарышта ұзақ уақыт жұмыс істеді. Ғарышкер болу үшін денсаулық, "
                "білім және төзімділік қажет. Бәлкім, сендердің араларыңнан да болашақ ғарышкер шығар.",
    },
]

# title -> [(question, [options...], index of the correct option)]
QUIZZES = {
    "Менің отбасым": [
        ("Отбасы қай қалада тұрады?", ["Астанада", "Алматыда", "Шымкентте", "Ақтауда"], 1),
        ("Отбасында неше адам бар?", ["Үш", "Төрт", "Бес", "Алты"], 2),
        ("Әкесінің мамандығы кім?", ["Дәрігер", "Мұғалім", "Құрылысшы инженер", "Жүргізуші"], 2),
        ("Анасы балаларға күн сайын не оқып береді?", ["Ертегі", "Газет", "Өлең", "Хат"], 0),
    ],
    "Алатау баурайында": [
        ("Тау баурайында қандай ағаштар жайқалып тұр?", ["Қайыңдар", "Шыршалар", "Теректер", "Алма ағаштары"], 1),
        ("Аралар не жинайды?", ["Су", "Жапырақ", "Бал", "Тұқым"], 2),
        ("Кешке таудың ақ басы қандай түске боялады?", ["Көк", "Жасыл", "Қызғылт", "Сары"], 2),
    ],
    "Табиғатты қорғайық": [
        ("Сынып оқушылары көктемде не істеді?", ["Ағаш екті", "Қар тазалады", "Сурет салды", "Ән айтты"], 0),
        ("Ағаштың пайдасы қандай?", ["Ауаны тазартады", "Шу шығарады", "Суды ластайды", "Пайдасы жоқ"], 0),
    ],
}

CLASSMATES = [
    ("Айару", "Серікқызы", 62), ("Дәулет", "Болатұлы", 56), ("Әлішер", "Нұрланұлы", 38),
    ("Аружан", "Қасым", 66), ("Ернұр", "Марат", 51), ("Інжу", "Ахметова", 59),
]


class Command(BaseCommand):
    help = "Демо деректер: мәтіндер, мұғалім, сынып, оқушылар, ата-ана және оқу тарихы."

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(7)
        texts = {}
        for data in TEXTS:
            text, _ = Text.objects.update_or_create(title=data["title"], defaults=data)
            texts[text.title] = text
        self.stdout.write(f"Мәтіндер: {len(texts)}")

        for title, items in QUIZZES.items():
            text = texts[title]
            if text.questions.exists():
                continue
            for order, (prompt, options, correct) in enumerate(items, start=1):
                question = Question.objects.create(text=text, prompt=prompt, order=order)
                Choice.objects.bulk_create(
                    Choice(question=question, label=label, is_correct=i == correct) for i, label in enumerate(options)
                )

        admin = self.user("admin", "Әкімші", "", User.Role.ADMIN, is_staff=True, is_superuser=True)

        teacher = self.user("mugalim", "Гүлнар", "Сейітқалиқызы", User.Role.TEACHER, email="gulnar@school.kz")
        class_3a, _ = SchoolClass.objects.get_or_create(
            grade=3, letter="А", defaults={"school": "№15 мектеп-гимназия", "teacher": teacher}
        )
        class_1b, _ = SchoolClass.objects.get_or_create(
            grade=1, letter="Б", defaults={"school": "№15 мектеп-гимназия", "teacher": teacher}
        )

        students = []
        for first, last, speed in CLASSMATES:
            login = "aiaru" if first == "Айару" else None
            st = self.user(login or f"student{len(students) + 1}", first, last, User.Role.STUDENT, school_class=class_3a)
            students.append((st, speed))
        erasyl = self.user("erasyl", "Ерасыл", "Серікұлы", User.Role.STUDENT, school_class=class_1b)

        parent = self.user("serik", "Серік", "Оспанов", User.Role.PARENT, email="serik@example.kz")
        parent.children.add(students[0][0], erasyl)

        Assignment.objects.get_or_create(
            text=texts["Табиғатты қорғайық"], school_class=class_3a,
            defaults={"assigned_by": teacher, "due_date": timezone.localdate() + timedelta(days=5)},
        )

        if not ReadingSession.objects.exists():
            grade3 = [t for t in texts.values() if t.grade == 3]
            for st, speed in students:
                for days_ago in (12, 9, 6, 4, 2, 0):
                    if random.random() < 0.25 and days_ago:
                        continue
                    progress = (12 - days_ago) / 12 * 6  # students improve over two weeks
                    self.fake_session(st, random.choice(grade3), speed - 6 + progress, days_ago)
            self.fake_session(erasyl, texts["Менің мысығым"], 24, 1)
            self.fake_session(erasyl, texts["Менің мысығым"], 27, 0)

        self.stdout.write(self.style.SUCCESS(
            "\nДайын! Кіру деректері (құпиясөз барлығына: %s):\n"
            "  Әкімші:  admin (әкімші панелі: /panel/)\n"
            "  Мұғалім: mugalim\n  Ата-ана: serik\n  Оқушы:   aiaru (немесе QR-кодпен: /qr/%s/)\n"
            % (DEMO_PASSWORD, students[0][0].login_code)
        ))

    def user(self, username, first, last, role, **extra):
        user, created = User.objects.get_or_create(
            username=username, defaults={"first_name": first, "last_name": last, "role": role, **extra}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
        return user

    def fake_session(self, student, text, target_wpm, days_ago):
        """Simulate a reading with a few recognition mistakes."""
        words = text.words
        heard = []
        for w in words:
            r = random.random()
            if r < 0.04:
                continue                      # skipped word
            if r < 0.08:
                heard.append(w[: max(1, len(w) // 2)] + "ла")  # misread word
            else:
                heard.append(w)
        low, _ = grade_norm(text.grade)
        duration = len(words) / max(target_wpm, 10) * 60
        if duration > READING_SECONDS:      # the reading stops after one minute
            heard = heard[: int(len(heard) * READING_SECONDS / duration)]
            duration = READING_SECONDS
        created = timezone.now() - timedelta(days=days_ago, hours=random.randint(0, 6), minutes=random.randint(0, 59))
        session = ReadingSession.objects.create(
            student=student, text=text, transcript=" ".join(heard), duration_seconds=round(duration, 1), created_at=created
        )
        analyze_session(session)
        if session.wpm < low:
            session.teacher_comment = "Күн сайын 10 минут дауыстап оқуды ұсынамын."
            session.save(update_fields=["teacher_comment"])
