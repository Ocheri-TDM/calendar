from django.db import models


class Teacher(models.Model):
    first_name = models.CharField(max_length=50, verbose_name="Имя")
    last_name = models.CharField(max_length=50, verbose_name="Фамилия")
    patronymic = models.CharField(max_length=50, verbose_name="Отчество", blank=True, null=True)
    phone_number = models.CharField(max_length=20, verbose_name="Телефон", blank=True, null=True)
    gmail = models.EmailField(max_length=100, verbose_name="Gmail", blank=True, null=True)
    position = models.CharField(max_length=100, verbose_name="Должность", blank=True, null=True)
    photo = models.ImageField(upload_to="teachers/", blank=True, null=True, verbose_name="Фотография")

    def __str__(self):
        return f"{self.last_name} {self.first_name} {self.patronymic or ''}".strip()

    class Meta:
        db_table = "main_teacher"
        verbose_name = "Преподаватель"
        verbose_name_plural = "Преподаватели"


class Direction(models.Model):
    name = models.CharField(max_length=100, verbose_name="Название")
    code = models.CharField(max_length=20, unique=True, verbose_name="Код")

    def __str__(self):
        return self.code

    class Meta:
        db_table = "main_direction"
        verbose_name = "Направление"
        verbose_name_plural = "Направления"



class Group(models.Model):
    SHIFT_CHOICES = (
        (1, "Первая смена"),
        (2, "Вторая смена"),
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
        db_column="supervisor_id",
    )
    students_count = models.PositiveIntegerField(default=0, verbose_name="Количество студентов")
    shift = models.PositiveSmallIntegerField(choices=SHIFT_CHOICES, default=1, verbose_name="Смена")
    course = models.PositiveSmallIntegerField(choices=COURSE_CHOICES, default=1, verbose_name="Курс")
    direction = models.ForeignKey(
        Direction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Направление",
        db_column="direction_id",
    )

    def __str__(self):
        return f"{self.name_group} (Смена {self.shift}, Курс {self.course})"

    class Meta:
        db_table = "main_group"
        verbose_name = "Группа"
        verbose_name_plural = "Группы"


class Classroom(models.Model):
    STATUS_CHOICES = (
        ("free", "Доступна"),
        ("busy", "Занята"),
        ("repair", "На ремонте"),
    )

    number_room = models.CharField(max_length=20, verbose_name="Номер аудитории")
    floor = models.PositiveIntegerField(verbose_name="Этаж", null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="free", verbose_name="Статус")

    def __str__(self):
        return f"Аудитория {self.number_room}"

    class Meta:
        db_table = "main_classroom"
        verbose_name = "Аудитория"
        verbose_name_plural = "Аудитории"


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

    name_dis = models.CharField(max_length=255, verbose_name="Название дисциплины")
    name_short = models.CharField(max_length=50, verbose_name="Сокращение", blank=True, null=True)
    duration_hours = models.PositiveIntegerField(
        verbose_name="Количество часов обучения", null=True, blank=True, default=50
    )
    control_type = models.CharField(
        max_length=20, choices=CONTROL_CHOICES, default="exam", verbose_name="Форма контроля"
    )
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default="active", verbose_name="Статус"
    )

    teachers = models.ManyToManyField(
        Teacher,
        related_name="disciplines",
        verbose_name="Преподаватели",
        through="DisciplineTeacherLink",
        blank=True,
    )

    classroom = models.ManyToManyField(
        Classroom,
        related_name="disciplines",
        verbose_name="Аудитории",
        through="DisciplineClassroomLink",
        blank=True,
    )

    def __str__(self):
        return self.name_dis

    class Meta:
        db_table = "main_discipline"
        verbose_name = "Дисциплина"
        verbose_name_plural = "Дисциплины"


class DisciplineTeacherLink(models.Model):
    discipline = models.ForeignKey(Discipline, on_delete=models.CASCADE, db_column="discipline_id")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, db_column="teacher_id")

    class Meta:
        db_table = "main_discipline_teachers"
        managed = False


class DisciplineClassroomLink(models.Model):
    discipline = models.ForeignKey(Discipline, on_delete=models.CASCADE, db_column="discipline_id")
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, db_column="classroom_id")

    class Meta:
        db_table = "main_discipline_classroom"
        managed = False


class GroupWeekState(models.Model):
    STATE_CHOICES = (
        ("theory", "Теория"),
        ("practice", "Практика"),
        ("vacation", "Каникулы"),
        ("holiday", "Праздничная неделя"),
        ("no_schedule", "Без расписания"),
    )

    group = models.ForeignKey(Group, on_delete=models.CASCADE, verbose_name="Группа", db_column="group_id")
    week_number = models.PositiveIntegerField(verbose_name="Номер недели")
    state = models.CharField(max_length=30, choices=STATE_CHOICES, verbose_name="Состояние")
    practice_code = models.CharField(max_length=100, blank=True, null=True, verbose_name="Код практики")
    practice_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Название практики")
    cell_value = models.CharField(max_length=100, blank=True, null=True, verbose_name="Значение ячейки")
    start_date = models.DateField(blank=True, null=True, verbose_name="Начало недели")
    end_date = models.DateField(blank=True, null=True, verbose_name="Конец недели")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.group.name_group} | {self.week_number} | {self.state}"

    class Meta:
        db_table = "main_group_week_state"
        verbose_name = "Состояние группы на неделю"
        verbose_name_plural = "Состояния групп на неделю"
        unique_together = ("group", "week_number")


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

    group = models.ForeignKey(Group, on_delete=models.CASCADE, verbose_name="Группа", db_column="group_id")
    discipline = models.ForeignKey(Discipline, on_delete=models.CASCADE, verbose_name="Дисциплина", db_column="discipline_id")
    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Преподаватель",
        db_column="teacher_id",
    )
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Аудитория",
        db_column="classroom_id",
    )
    classroom2 = models.ForeignKey(
    Classroom,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    verbose_name="Вторая аудитория",
    db_column="second_classroom_id",
    related_name="second_classroom_id",
)

    weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES, verbose_name="День недели")
    week_type = models.CharField(max_length=20, choices=WEEK_TYPE_CHOICES, default="numerator", verbose_name="Тип недели")
    lesson_number = models.PositiveSmallIntegerField(choices=LESSON_CHOICES, verbose_name="Номер пары")
    start_time = models.TimeField(verbose_name="Начало", blank=True, null=True)
    end_time = models.TimeField(verbose_name="Конец", blank=True, null=True)

    def __str__(self):
        return (
            f"{self.group.name_group} | {self.get_weekday_display()} | "
            f"{self.lesson_number} пара | {self.get_week_type_display()}"
        )

    class Meta:
        db_table = "main_classschedule"
        verbose_name = "Расписание"
        verbose_name_plural = "Расписание"

class DirectionDiscipline(models.Model):
    COURSE_CHOICES = (
        (1, "1 курс"),
        (2, "2 курс"),
        (3, "3 курс"),
        (4, "4 курс"),
    )

    direction = models.ForeignKey(
        Direction,
        on_delete=models.CASCADE,
        db_column="direction_id",
        related_name="direction_disciplines",
        verbose_name="Направление"
    )
    discipline = models.ForeignKey(
        "Discipline",
        on_delete=models.CASCADE,
        db_column="discipline_id",
        related_name="direction_discipline_links",
        verbose_name="Дисциплина"
    )
    is_required = models.BooleanField(default=True, verbose_name="Обязательная")
    course = models.PositiveSmallIntegerField(
        choices=COURSE_CHOICES,
        verbose_name="Курс",
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"{self.direction.code} -> {self.discipline.name_dis} ({self.course or 'без курса'})"

    class Meta:
        db_table = "main_direction_discipline"
        verbose_name = "Связь направления и дисциплины"
        verbose_name_plural = "Связи направлений и дисциплин"
        unique_together = ("direction", "discipline", "course")
    



class GroupPracticeClassroom(models.Model):
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="practice_classrooms"
    )
    week_number = models.IntegerField()
    practice_code = models.CharField(max_length=50)
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "main_group_practice_classroom"
        unique_together = ("group", "week_number", "practice_code")

    def __str__(self):
        return f"{self.group} - {self.practice_code} - {self.week_number}"