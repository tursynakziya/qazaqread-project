from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .analysis import align
from .models import ClassReading, ReadingSession, SchoolClass, Text, User, WordResult, split_words

S = WordResult.Status


class AnalysisTests(TestCase):
    def test_split_words_keeps_kazakh_letters_and_hyphens(self):
        self.assertEqual(split_words("Күш-қуат, бұлақ — әсем!"), ["Күш-қуат", "бұлақ", "әсем"])

    def test_perfect_reading(self):
        words = ["Менің", "отбасым", "үлкен"]
        self.assertEqual([r[2] for r in align(words, ["менің", "отбасым", "үлкен"])], [S.CORRECT] * 3)

    def test_misread_and_skipped(self):
        expected = ["Әкем", "жаңа", "ғимараттар", "салады"]
        heard = ["әкем", "үйлер", "салады"]
        self.assertEqual([r[2] for r in align(expected, heard)], [S.CORRECT, S.MISREAD, S.SKIPPED, S.CORRECT])

    def test_close_recognition_counts_as_correct(self):
        self.assertEqual(align(["қарындасым"], ["қарындасын"])[0][2], S.CORRECT)

    def test_unreached_tail_is_not_an_error(self):
        result = align(["бір", "екі", "үш", "төрт"], ["бір", "екі"])
        self.assertEqual(len(result), 2)


class Fixture(TestCase):
    password = "Qazaq-pass-2026"

    def setUp(self):
        self.teacher = self.make("teacher1", User.Role.TEACHER)
        self.klass = SchoolClass.objects.create(grade=3, letter="А", teacher=self.teacher)
        self.student = self.make("student1", User.Role.STUDENT, school_class=self.klass)
        self.other = self.make("student2", User.Role.STUDENT)
        self.parent = self.make("parent1", User.Role.PARENT)
        self.parent.children.add(self.student)
        self.text = Text.objects.create(title="Сынақ", grade=3, body="Менің отбасым үлкен әрі тату. Біз Алматыда тұрамыз.")

    def make(self, username, role, **extra):
        user = User.objects.create_user(username, f"{username}@x.kz", self.password, role=role, first_name=username, **extra)
        return user

    def login(self, user):
        self.client.force_login(user)


@override_settings(MEDIA_ROOT="test_media_tmp")
class ReadingFlowTests(Fixture):
    def tearDown(self):
        import shutil

        shutil.rmtree("test_media_tmp", ignore_errors=True)

    def submit(self, transcript, duration="30"):
        audio = SimpleUploadedFile("reading.webm", b"fake-audio", content_type="audio/webm")
        return self.client.post(
            reverse("submit_reading", args=[self.text.pk]),
            {"transcript": transcript, "duration": duration, "audio": audio},
        )

    def test_submit_scores_reading(self):
        self.login(self.student)
        resp = self.submit("менің отбасым үлкен әрі тату біз алматыда тұрамыз")
        session = ReadingSession.objects.get()
        self.assertRedirects(resp, reverse("result", args=[session.pk]))
        self.assertEqual(session.words_correct, 8)
        self.assertEqual(session.accuracy, 100)
        self.assertEqual(session.wpm, 16)  # 8 words in 30 seconds
        self.assertTrue(session.audio.name.endswith(".webm"))

    def test_reading_is_limited_to_one_minute(self):
        self.login(self.student)
        self.submit("менің отбасым үлкен әрі тату біз алматыда тұрамыз", duration="95")
        session = ReadingSession.objects.get()
        self.assertEqual(session.duration_seconds, 60)
        self.assertEqual(session.wpm, 8)  # 8 correct words in the one-minute window

    def test_empty_transcript_goes_to_teacher_review(self):
        self.login(self.student)
        self.submit("")
        session = ReadingSession.objects.get()
        self.assertEqual(session.status, ReadingSession.Status.NEEDS_REVIEW)

        self.login(self.teacher)
        url = reverse("review_word", args=[session.pk, 0])
        data = self.client.post(url, {"status": "correct"}).json()
        self.assertEqual(data["correct"], 1)

    def test_result_page_access(self):
        self.login(self.student)
        self.submit("менің отбасым")
        session = ReadingSession.objects.get()
        url = reverse("result", args=[session.pk])
        for user, code in [(self.student, 200), (self.parent, 200), (self.teacher, 200), (self.other, 403)]:
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, code, user.username)
        self.login(self.other)
        self.assertEqual(self.client.get(reverse("session_audio", args=[session.pk])).status_code, 404)

    def test_student_cannot_review_words(self):
        self.login(self.student)
        self.submit("менің")
        session = ReadingSession.objects.get()
        resp = self.client.post(reverse("review_word", args=[session.pk, 0]), {"status": "correct"})
        self.assertEqual(resp.status_code, 403)


class AuthTests(Fixture):
    def test_login_by_email_redirects_by_role(self):
        resp = self.client.post(reverse("login"), {"username": "teacher1@x.kz", "password": self.password})
        self.assertRedirects(resp, reverse("home"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("home")), reverse("teacher_dashboard"))

    def test_qr_login(self):
        resp = self.client.get(reverse("qr_login", args=[self.student.login_code]))
        self.assertRedirects(resp, reverse("student_dashboard"))

    def test_register_parent(self):
        resp = self.client.post(reverse("register"), {
            "role": "parent", "first_name": "Серік", "last_name": "Оспанов", "email": "new@x.kz",
            "password": "Strong-pass-2026", "agree": "on",
        })
        self.assertRedirects(resp, reverse("add_child"))
        self.assertTrue(User.objects.filter(email="new@x.kz", role="parent").exists())

    def test_parent_adds_child_by_code(self):
        self.login(self.parent)
        self.client.post(reverse("add_child"), {"login_code": self.other.login_code})
        self.assertIn(self.other, self.parent.children.all())

    def test_role_pages_are_protected(self):
        self.login(self.student)
        self.assertEqual(self.client.get(reverse("teacher_dashboard")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("student_dashboard")).status_code, 302)


class TeacherTests(Fixture):
    def test_add_student_and_export(self):
        self.login(self.teacher)
        self.client.post(reverse("student_add"), {"first_name": "Аружан", "last_name": "Қасым"})
        self.assertTrue(self.klass.students.filter(first_name="Аружан").exists())
        resp = self.client.get(reverse("export_csv"))
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")

    def test_assign_text(self):
        self.login(self.teacher)
        self.client.post(reverse("assign_text"), {"text": self.text.pk})
        self.assertEqual(self.klass.assignments.count(), 1)


class PagesRenderTests(TestCase):
    """Every page renders for its role with the demo data."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def test_all_pages(self):
        teacher = User.objects.get(username="mugalim")
        student = User.objects.get(username="aiaru")
        parent = User.objects.get(username="serik")
        admin = User.objects.get(username="admin")
        quiz_text = Text.objects.get(title="Менің отбасым")
        session = student.sessions.first()
        text = Text.objects.first()
        pages = {
            student: [("quiz", quiz_text.pk), "student_dashboard", "library", "results", "settings", ("reading", text.pk), ("result", session.pk)],
            parent: ["parent_dashboard", "add_child", ("student_report", student.pk), ("student_results", student.pk)],
            admin: [
                "panel_dashboard", "panel_text_create", "panel_users", "panel_quiz_results", "library",
                ("panel_text_edit", quiz_text.pk), ("panel_questions", quiz_text.pk),
                ("panel_question_edit", quiz_text.questions.first().pk), ("panel_text_delete", quiz_text.pk),
            ],
            teacher: ["teacher_dashboard", "student_add", "assign_text", "text_create", "qr_cards", "class_create", "library"],
        }
        for user, names in pages.items():
            self.client.force_login(user)
            for name in names:
                url = reverse(name[0], args=[name[1]]) if isinstance(name, tuple) else reverse(name)
                self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.logout()
        for name in ["login", "password_reset"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)


class PanelTests(Fixture):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("boss", "boss@x.kz", self.password)

    def test_superuser_gets_admin_role_and_lands_on_panel(self):
        self.assertEqual(self.admin.role, User.Role.ADMIN)
        self.login(self.admin)
        self.assertRedirects(self.client.get(reverse("home")), reverse("panel_dashboard"))

    def test_only_admin_can_open_panel(self):
        for user in (self.student, self.teacher, self.parent):
            self.login(user)
            self.assertEqual(self.client.get(reverse("panel_dashboard")).status_code, 403)

    def test_create_text_then_add_question(self):
        self.login(self.admin)
        resp = self.client.post(reverse("panel_text_create"), {
            "title": "Жаңа мәтін", "grade": 2, "difficulty": "easy", "topic": "nature", "genre": "fiction",
            "summary": "", "body": "Көктем келді. Құстар ұшып келді.",
        })
        text = Text.objects.get(title="Жаңа мәтін")
        self.assertRedirects(resp, reverse("panel_questions", args=[text.pk]))
        self.assertEqual(text.word_count, 5)

        self.client.post(reverse("panel_questions", args=[text.pk]), {
            "prompt": "Не келді?", "choice_1": "Қыс", "choice_2": "Көктем", "choice_3": "", "choice_4": "",
            "correct": "2", "explanation": "", "order": 1,
        })
        question = text.questions.get()
        self.assertEqual([c.label for c in question.choices.all()], ["Қыс", "Көктем"])
        self.assertEqual(question.correct_choice.label, "Көктем")

    def test_correct_answer_must_be_filled(self):
        self.login(self.admin)
        self.client.post(reverse("panel_questions", args=[self.text.pk]), {
            "prompt": "?", "choice_1": "a", "choice_2": "b", "correct": "4",
        })
        self.assertFalse(self.text.questions.exists())

    def test_edit_and_delete(self):
        self.login(self.admin)
        self.client.post(reverse("panel_text_edit", args=[self.text.pk]), {
            "title": "Өзгерген", "grade": 3, "difficulty": "hard", "topic": "family", "genre": "moral",
            "summary": "", "body": self.text.body,
        })
        self.text.refresh_from_db()
        self.assertEqual(self.text.title, "Өзгерген")
        self.client.post(reverse("panel_text_delete", args=[self.text.pk]))
        self.assertFalse(Text.objects.filter(pk=self.text.pk).exists())

    def test_change_role(self):
        self.login(self.admin)
        self.client.post(reverse("panel_user_role", args=[self.parent.pk]), {"role": "teacher"})
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.role, User.Role.TEACHER)


class QuizTests(Fixture):
    def setUp(self):
        super().setUp()
        from .models import Choice, Question

        self.q1 = Question.objects.create(text=self.text, prompt="Қай қалада?", order=1)
        self.right = Choice.objects.create(question=self.q1, label="Алматы", is_correct=True)
        self.wrong = Choice.objects.create(question=self.q1, label="Астана")
        self.q2 = Question.objects.create(text=self.text, prompt="Отбасы қандай?", order=2)
        self.right2 = Choice.objects.create(question=self.q2, label="Тату", is_correct=True)
        Choice.objects.create(question=self.q2, label="Ұрысқақ")

    def test_student_takes_quiz(self):
        self.login(self.student)
        self.assertEqual(self.client.get(reverse("quiz", args=[self.text.pk])).status_code, 200)
        resp = self.client.post(reverse("quiz", args=[self.text.pk]), {
            f"q{self.q1.pk}": self.wrong.pk, f"q{self.q2.pk}": self.right2.pk,
        })
        attempt = self.student.quiz_attempts.get()
        self.assertRedirects(resp, reverse("quiz_result", args=[attempt.pk]))
        self.assertEqual((attempt.correct, attempt.total, attempt.percent), (1, 2, 50))

    def test_unanswered_question_is_rejected(self):
        self.login(self.student)
        self.client.post(reverse("quiz", args=[self.text.pk]), {f"q{self.q1.pk}": self.right.pk})
        self.assertFalse(self.student.quiz_attempts.exists())

    def test_quiz_result_visible_to_parent_not_stranger(self):
        self.login(self.student)
        self.client.post(reverse("quiz", args=[self.text.pk]), {
            f"q{self.q1.pk}": self.right.pk, f"q{self.q2.pk}": self.right2.pk,
        })
        url = reverse("quiz_result", args=[self.student.quiz_attempts.get().pk])
        self.login(self.parent)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)


@override_settings(MEDIA_ROOT="test_media_tmp")
class ServerSpeechTests(Fixture):
    """Real recognition of a short Kazakh recording (skipped if Vosk is not set up)."""

    def tearDown(self):
        import shutil

        shutil.rmtree("test_media_tmp", ignore_errors=True)

    def test_server_recognises_kazakh_recording(self):
        from pathlib import Path

        from .speech import is_available

        if not is_available():
            self.skipTest("Vosk model or ffmpeg not installed")
        text = Text.objects.create(
            title="Айару",
            grade=3,
            body="Менің атым Айару. Мен үшінші сыныпта оқимын. Біздің отбасымыз үлкен. Әкем дәрігер, анам мұғалім.",
        )
        sample = Path(__file__).parent / "test_data" / "kk_sample.webm"
        audio = SimpleUploadedFile("reading.webm", sample.read_bytes(), content_type="audio/webm")
        self.login(self.student)
        # The browser sent nothing (e.g. Yandex browser, no internet): the server must recognise the voice itself.
        self.client.post(reverse("submit_reading", args=[text.pk]), {"transcript": "", "duration": "10", "audio": audio})
        session = ReadingSession.objects.get()
        self.assertIn("отбасымыз", session.transcript)
        self.assertGreaterEqual(session.words_correct, 13)
        self.assertEqual(session.status, ReadingSession.Status.COMPLETED)

    def test_live_recognition_streams_chunks(self):
        import subprocess
        from pathlib import Path

        from .speech import ffmpeg_path, is_available

        if not is_available():
            self.skipTest("Vosk model or ffmpeg not installed")
        text = Text.objects.create(
            title="Айару",
            grade=3,
            body="Менің атым Айару. Мен үшінші сыныпта оқимын. Біздің отбасымыз үлкен. Әкем дәрігер, анам мұғалім.",
        )
        sample = Path(__file__).parent / "test_data" / "kk_sample.webm"
        pcm = subprocess.run(
            [ffmpeg_path(), "-loglevel", "error", "-i", str(sample), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
            check=True, capture_output=True,
        ).stdout
        self.login(self.student)
        url = reverse("live_recognize", args=[text.pk]) + "?sid=test-session-1"
        step = 16000 * 2 * 7 // 10  # 0.7 s, as the reading page sends
        texts = []
        for i in range(0, len(pcm), step):
            resp = self.client.post(url, pcm[i : i + step], content_type="application/octet-stream")
            self.assertEqual(resp.status_code, 200)
            texts.append(resp.json()["text"])
        final = self.client.post(url + "&final=1", b"", content_type="application/octet-stream").json()["text"]
        self.assertTrue(any("менің" in t for t in texts[:-1]), "words should appear while still reading")
        self.assertIn("мұғалім", final)

    def test_live_recognition_rejects_bad_session_id(self):
        self.login(self.student)
        resp = self.client.post(reverse("live_recognize", args=[self.text.pk]) + "?sid=../x", b"", content_type="application/octet-stream")
        self.assertEqual(resp.status_code, 400)


class PanelPasswordTests(Fixture):
    def test_admin_issues_new_password(self):
        admin = User.objects.create_user("boss", password="pw-12345", role=User.Role.ADMIN)
        self.client.force_login(admin)
        resp = self.client.post(reverse("panel_user_password", args=[self.student.pk]))
        password = resp.context["password"]
        self.assertContains(resp, password)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(password))

    def test_teacher_cannot_reset_passwords(self):
        self.login(self.teacher)
        resp = self.client.post(reverse("panel_user_password", args=[self.student.pk]))
        self.assertEqual(resp.status_code, 403)


class RobustnessTests(Fixture):
    def test_junk_query_parameters_do_not_crash(self):
        self.login(self.teacher)
        self.assertEqual(self.client.get(reverse("teacher_dashboard") + "?class=abc").status_code, 200)
        self.login(self.student)
        self.assertEqual(self.client.get(reverse("library") + "?grade=abc").status_code, 200)
        resp = self.client.post(reverse("submit_reading", args=[self.text.pk]), {"transcript": "менің", "duration": "x", "assignment": "x"})
        self.assertEqual(resp.status_code, 302)

    def test_hyphenated_word_heard_as_two_words_is_correct(self):
        rows = align(["Күш-қуат", "береді"], ["күш", "қуат", "береді"])
        self.assertEqual([r[2] for r in rows], [WordResult.Status.CORRECT] * 2)

    def test_grammar_contains_text_words_and_unknown(self):
        from .speech import text_grammar

        self.assertEqual(text_grammar("Күш-қуат береді. Күш!"), ["береді", "күш", "қуат", "[unk]"])


class EmptyAccountTests(TestCase):
    """Brand-new accounts with no class, children, texts or readings must see every page without errors."""

    PAGES = {
        User.Role.STUDENT: ["home", "student_dashboard", "library", "results", "settings"],
        User.Role.PARENT: ["home", "parent_dashboard", "add_child", "settings"],
        User.Role.TEACHER: ["home", "teacher_dashboard", "class_create", "student_add", "assign_text", "text_create", "qr_cards", "export_csv", "library", "settings"],
        User.Role.ADMIN: ["home", "panel_dashboard", "panel_text_create", "panel_users", "panel_quiz_results", "library", "settings"],
    }

    def check_pages(self):
        for role, names in self.PAGES.items():
            user = User.objects.create_user(f"new_{role}", password="x", role=role)
            self.client.force_login(user)
            for name in names:
                with self.subTest(role=role, page=name):
                    expected = (404,) if name == "export_csv" else (200, 302)  # no class yet: nothing to export
                    self.assertIn(self.client.get(reverse(name)).status_code, expected)

    def test_no_texts_at_all(self):
        self.check_pages()

    def test_student_has_read_every_text(self):
        Text.objects.create(title="Жалғыз", grade=1, body="Бір сөз екі сөз.")
        student = User.objects.create_user("reader", password="x", role=User.Role.STUDENT)
        ReadingSession.objects.create(student=student, text=Text.objects.get(), duration_seconds=10)
        self.client.force_login(student)
        self.assertEqual(self.client.get(reverse("student_dashboard")).status_code, 200)
        self.check_pages()


@override_settings(MEDIA_ROOT="test_media_tmp")
class ClassLessonTests(Fixture):
    def tearDown(self):
        import shutil

        shutil.rmtree("test_media_tmp", ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.student.last_name = "Сейітов"
        self.student.save()
        # Kazakh letters must sort in alphabet order, not Unicode order (Ә after А, before Б).
        self.b = self.make("bekova", User.Role.STUDENT, school_class=self.klass, last_name="Бекова")
        self.ae = self.make("aliev", User.Role.STUDENT, school_class=self.klass, last_name="Әлиев")
        self.a = self.make("akhmet", User.Role.STUDENT, school_class=self.klass, last_name="Ахметов")
        self.login(self.teacher)
        self.client.post(reverse("lesson_create"), {"school_class": self.klass.pk, "text": self.text.pk})
        self.lesson = ClassReading.objects.get()

    def read(self, student, transcript="менің отбасым үлкен әрі тату біз алматыда тұрамыз"):
        return self.client.post(
            reverse("lesson_submit", args=[self.lesson.pk, student.pk]),
            {"transcript": transcript, "duration": "60"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

    def test_students_are_listed_in_kazakh_alphabet_order(self):
        resp = self.client.get(reverse("lesson", args=[self.lesson.pk]))
        names = [r["student"].last_name for r in resp.context["rows"]]
        self.assertEqual(names, ["Ахметов", "Әлиев", "Бекова", "Сейітов"])
        self.assertEqual(resp.context["next_row"]["student"], self.a)

    def test_reading_is_saved_to_student_and_next_student_comes_up(self):
        self.assertEqual(self.client.get(reverse("lesson_read", args=[self.lesson.pk, self.a.pk])).status_code, 200)
        resp = self.read(self.a)
        self.assertIn(f"done={self.a.pk}", resp.json()["redirect"])
        session = ReadingSession.objects.get()
        self.assertEqual((session.student, session.class_reading), (self.a, self.lesson))
        page = self.client.get(reverse("lesson", args=[self.lesson.pk]))
        self.assertEqual(page.context["next_row"]["student"], self.ae)

    def test_absent_student_is_skipped(self):
        self.client.post(reverse("lesson_absent", args=[self.lesson.pk, self.a.pk]))
        page = self.client.get(reverse("lesson", args=[self.lesson.pk]))
        self.assertEqual(page.context["next_row"]["student"], self.ae)

    def test_marks_are_visible_to_student_parent_and_teacher(self):
        self.read(self.student)
        self.read(self.a)
        resp = self.client.post(
            reverse("lesson", args=[self.lesson.pk]),
            {f"mark_{self.student.pk}": "5", f"comment_{self.student.pk}": "Жарайсың!", f"mark_{self.a.pk}": "9"},
        )
        self.assertRedirects(resp, reverse("lesson", args=[self.lesson.pk]))
        session = ReadingSession.objects.get(student=self.student)
        self.assertEqual((session.mark, session.teacher_comment), (5, "Жарайсың!"))
        self.assertIsNone(ReadingSession.objects.get(student=self.a).mark)  # 9 is not a valid mark

        self.assertContains(self.client.get(reverse("teacher_dashboard")), "Баға: 5")
        self.login(self.student)
        self.assertContains(self.client.get(reverse("result", args=[session.pk])), "Мұғалім бағасы")
        self.assertContains(self.client.get(reverse("student_dashboard")), "Баға: 5")
        self.login(self.parent)
        self.assertContains(self.client.get(reverse("parent_dashboard")), "Баға: 5")

    def test_suggested_mark(self):
        self.read(self.student)
        self.assertEqual(ReadingSession.objects.get().suggested_mark, 2)  # 8 words in a minute, norm is 50+

    def test_only_the_class_teacher_runs_the_lesson(self):
        other_teacher = self.make("teacher2", User.Role.TEACHER)
        self.login(other_teacher)
        self.assertEqual(self.client.get(reverse("lesson", args=[self.lesson.pk])).status_code, 404)
        self.assertEqual(self.read(self.a).status_code, 404)
        self.login(self.student)
        self.assertEqual(self.client.get(reverse("lesson", args=[self.lesson.pk])).status_code, 403)
        self.login(self.teacher)
        self.assertEqual(self.read(self.other).status_code, 404)  # not in this class
