from django.db import models


class Teacher(models.Model):
    first_name = models.CharField(max_length=50, verbose_name="Имя")
    last_name = models.CharField(max_length=50, verbose_name="Фамилия")
    patronymic = models.CharField(max_length=50, verbose_name="Отчество", blank=True, null=True)
    phone_number = models.CharField(max_length=20, verbose_name="Телефон")
    gmail = models.EmailField(max_length=100, verbose_name="Gmail", blank=True, null=True)
    position = models.CharField(max_length=100, verbose_name="Должность", blank=True, null=True)
    photo = models.ImageField(upload_to="teachers/", blank=True, null=True, verbose_name="Фотография")

    def __str__(self):
        return f"{self.last_name} {self.first_name} {self.patronymic or ''}".strip()


class Group(models.Model):
    SHIFT_CHOICES = (
        (1, "Первая смена (дневная)"),
        (2, "Вторая смена (послеобеденная)"),
    )

    COURSE_CHOICES = (
        (1, "1 курс"),
        (2, "2 курс"),
        (3, "3 курс"),
        (4, "4 курс"),
    )

    name_group = models.CharField(max_length=100, verbose_name="Название группы")
    supervisor = models.ForeignKey(
        Teacher,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Куратор",
    )
    students_count = models.PositiveIntegerField(default=0, verbose_name="Количество студентов")
    shift = models.PositiveSmallIntegerField(
        choices=SHIFT_CHOICES, default=1, verbose_name="Смена"
    )
    course = models.PositiveSmallIntegerField(
        choices=COURSE_CHOICES, default=1, verbose_name="Курс"
    )  # ✅ Новое поле

    def __str__(self):
        return f"{self.name_group} (Смена {self.shift}, Курс {self.course})"



class Classroom(models.Model):
    number_room = models.CharField(max_length=10, verbose_name="Номер аудитории")
    floor = models.PositiveIntegerField(verbose_name="Этаж")
    STATUS_CHOICES = (
        ('free', 'Доступна'),
        ('busy', 'Занята'),
        ('repair', 'На ремонте'),
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='free', verbose_name="Статус")

    def __str__(self):
        return f"Аудитория {self.number_room} (Этаж {self.floor})"


class Discipline(models.Model):
    CONTROL_CHOICES = (
        ("exam", "Экзамен"),
        ("test", "Зачет"),
        ("coursework", "Курсовая работа"),
    )

    STATUS_CHOICES = (
        ("active", "Активный"),
        ("inactive", "Неактивный"),
    )

    name_dis = models.CharField(max_length=100, verbose_name="Название дисциплины")
    name_short = models.CharField(max_length=10, verbose_name="Сокращение", blank=True, null=True)
    classroom = models.ForeignKey(
        Classroom, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Аудитория"
    )
    duration_hours = models.PositiveIntegerField(
        verbose_name="Количество часов обучения", null=True, blank=True, default=50
    )
    control_type = models.CharField(
        max_length=20, choices=CONTROL_CHOICES, default="exam", verbose_name="Форма контроля"
    )
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default="active", verbose_name="Статус"
    )
    teachers = models.ManyToManyField(Teacher, related_name="disciplines", verbose_name="Преподаватели")

    def __str__(self):
        return self.name_dis


class ClassSchedule(models.Model):
    LESSON_CHOICES = (
        (1, "1 пара"),
        (2, "2 пара"),
        (3, "3 пара"),
        (4, "4 пара"),
    )

    WEEK_TYPE_CHOICES = (
        ("numerator", "Числитель"),
        ("denominator", "Знаменатель"),
    )

    WEEKDAY_CHOICES = (
        (1, "Понедельник"),
        (2, "Вторник"),
        (3, "Среда"),
        (4, "Четверг"),
        (5, "Пятница"),
    )

    SHIFT_CHOICES = (
        (1, "Первая смена"),
        (2, "Вторая смена"),
    )

    # 🔗 Связи
    group = models.ForeignKey(Group, on_delete=models.CASCADE, verbose_name="Группа")
    discipline = models.ForeignKey(Discipline, on_delete=models.CASCADE, verbose_name="Дисциплина")
    teacher = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True, verbose_name="Преподаватель")
    classroom = models.ForeignKey(Classroom, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Аудитория")

    # 📅 Основные параметры
    shift = models.PositiveSmallIntegerField(choices=SHIFT_CHOICES, default=1, verbose_name="Смена")
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES, verbose_name="День недели")
    week_type = models.CharField(max_length=20, choices=WEEK_TYPE_CHOICES, default="numerator", verbose_name="Тип недели")
    lesson_number = models.PositiveSmallIntegerField(choices=LESSON_CHOICES, verbose_name="Номер пары")

    # ⏰ Автоматически выставляемые поля
    start_time = models.TimeField(verbose_name="Начало", blank=True, null=True)
    end_time = models.TimeField(verbose_name="Конец", blank=True, null=True)

    def save(self, *args, **kwargs):
        """
        При сохранении:
        1. Автоматически подставляем время по смене и номеру пары.
        2. Если аудитория не указана — берём из дисциплины.
        """

        # Время для первой смены
        times_shift_1 = {
            1: ("08:00", "09:20"),
            2: ("09:30", "10:50"),
            3: ("11:00", "12:20"),
            4: ("12:30", "13:50"),
        }

        # Время для второй смены
        times_shift_2 = {
            1: ("13:00", "14:20"),
            2: ("14:30", "15:50"),
            3: ("16:00", "17:20"),
            4: ("17:30", "18:50"),
        }

        lesson_times = times_shift_1 if self.shift == 1 else times_shift_2
        if not self.start_time or not self.end_time:
            from datetime import time
            start_str, end_str = lesson_times.get(self.lesson_number, (None, None))
            if start_str and end_str:
                self.start_time = time.fromisoformat(start_str)
                self.end_time = time.fromisoformat(end_str)

        # Автоматическая подстановка аудитории
        if not self.classroom and self.discipline and self.discipline.classroom:
            self.classroom = self.discipline.classroom

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.group.name_group} | {self.get_weekday_display()} "
            f"({self.get_shift_display()}, {self.lesson_number} пара)"
        )
