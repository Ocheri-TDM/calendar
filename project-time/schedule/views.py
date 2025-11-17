from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from .models import Classroom, Teacher, Discipline, Group, ClassSchedule
from collections import defaultdict
from django.urls import reverse
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from django.views.decorators.http import require_POST
from datetime import date, timedelta
from django.utils import timezone
import json
import datetime



# ну что ж, поехали
def get_week_type():
    """Определяет тип недели: числитель / знаменатель"""
    current_week = datetime.date.today().isocalendar()[1]
    return "numerator" if current_week % 2 != 0 else "denominator"


def admin_schedule(request):
    group_id = request.GET.get("group")
    shift = request.GET.get("shift")

    # 🔹 Тип недели теперь определяется автоматически
    week_type = get_week_type()

    groups = Group.objects.all()
    group = groups.filter(id=group_id).first() if group_id else None

    # 🔹 Загружаем расписание по типу недели
    schedule_qs = (
        ClassSchedule.objects.filter(week_type=week_type)
        .select_related("discipline", "teacher", "classroom")
        .order_by("weekday", "lesson_number")
    )

    if group:
        schedule_qs = schedule_qs.filter(group=group)
    if shift:
        schedule_qs = schedule_qs.filter(shift=shift)

    # 🔹 Сортируем по дням
    schedule_by_day = {i: [] for i in range(1, 6)}
    for lesson in schedule_qs:
        schedule_by_day[lesson.weekday].append(lesson)

    context = {
        "groups": groups,
        "selected_group": group,
        "selected_shift": int(shift) if shift and shift.isdigit() else None,
        "selected_week_type": week_type,  # автоматически выбранная неделя
        "today": timezone.now().date(),
        "schedule_by_day": schedule_by_day,
    }
    return render(request, "admin/admin-schedule-main.html", context)


def search_discipline(request):
    q = request.GET.get("q", "")
    disciplines = Discipline.objects.filter(name_dis__icontains=q)[:10]
    data = [{"id": d.id, "name": d.name_dis} for d in disciplines]
    return JsonResponse(data, safe=False)


def get_discipline_details(request, discipline_id):
    """Возвращает преподавателей и кабинет для выбранной дисциплины"""
    discipline = Discipline.objects.filter(id=discipline_id).first()
    if not discipline:
        return JsonResponse({"error": "Дисциплина не найдена"}, status=404)

    teachers = discipline.teachers.all()
    teachers_data = [
        {
            "id": t.id,
            "name": f"{t.last_name} {t.first_name[0]}.{t.patronymic[0] if t.patronymic else ''}."
        }
        for t in teachers
    ]

    room = discipline.classroom.number_room if discipline.classroom else "Не указано"

    return JsonResponse({
        "teachers": teachers_data,
        "room": room
    })


def get_groups_by_shift(request):
    shift = request.GET.get("shift")
    groups = Group.objects.filter(shift=shift) if shift else Group.objects.all()
    data = {
        "groups": [{"id": g.id, "name_group": g.name_group} for g in groups]
    }
    return JsonResponse(data)

def get_group_shift(request):
    """Возвращает смену для выбранной группы"""
    group_id = request.GET.get("group_id")
    group = Group.objects.filter(id=group_id).first()
    if not group:
        return JsonResponse({"error": "Группа не найдена"}, status=404)
    return JsonResponse({"shift": group.shift})

def get_next_lesson(request):
    group_id = request.GET.get("group")
    weekday = request.GET.get("weekday")
    shift = request.GET.get("shift")
    week_type = request.GET.get("week_type")

    try:
        existing = ClassSchedule.objects.filter(
            group_id=group_id,
            weekday=weekday,
            shift=shift,
            week_type=week_type
        ).values_list("lesson_number", flat=True)

        all_lessons = [1, 2, 3, 4]
        free_lessons = [n for n in all_lessons if n not in existing]

        if free_lessons:
            next_lesson = min(free_lessons)
        else:
            next_lesson = 1  # если все заняты — начнём заново

        return JsonResponse({"next_lesson": next_lesson})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

def load_schedule_table(request):
    """Возвращает только HTML-таблицу расписания (частичный шаблон)."""
    group_id = request.GET.get("group")
    shift = request.GET.get("shift")
    week_type = request.GET.get("week_type") or get_week_type()  # ✅ теперь учитывает фильтр

    group = Group.objects.filter(id=group_id).first() if group_id else None

    schedule_qs = (
        ClassSchedule.objects.filter(week_type=week_type)
        .select_related("discipline", "teacher", "classroom")
        .order_by("weekday", "lesson_number")
    )

    if group:
        schedule_qs = schedule_qs.filter(group=group)
    if shift:
        schedule_qs = schedule_qs.filter(shift=shift)

    schedule_by_day = {i: [] for i in range(1, 6)}
    for lesson in schedule_qs:
        schedule_by_day[lesson.weekday].append(lesson)

    print(f"DEBUG: group={group}, shift={shift}, week_type={week_type}, found={schedule_qs.count()}")

    html = render_to_string(
        "dinamic/schedule-table.html",
        {
            "schedule_by_day": schedule_by_day,
            "selected_group": group,
            "selected_week_type": week_type,
        },
        request=request
    )
    return JsonResponse({"html": html})


@csrf_exempt
def create_schedule(request):
    """Создание карточки расписания (редирект с сервера)"""
    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))

            group_id = data.get("group_id")
            if not group_id:
                return JsonResponse({"success": False, "error": "Не выбрана группа!"}, status=400)

            discipline_id = data.get("discipline_id")
            teacher_id = data.get("teacher_id")

            if not discipline_id or not teacher_id:
                return JsonResponse({"success": False, "error": "Не выбрана дисциплина или преподаватель!"}, status=400)

            group = Group.objects.get(id=group_id)
            discipline = Discipline.objects.get(id=discipline_id)
            teacher = Teacher.objects.get(id=teacher_id)

            weekday = int(data.get("weekday"))
            lesson_number = int(data.get("lesson_number"))
            shift = int(data.get("shift", 1))
            week_type = data.get("week_type", get_week_type())

            ClassSchedule.objects.create(
                group=group,
                discipline=discipline,
                teacher=teacher,
                weekday=weekday,
                lesson_number=lesson_number,
                shift=shift,
                week_type=week_type,
            )

            # 🔹 Серверный redirect
            return JsonResponse({
                "success": True,
                "message": f"Занятие добавлено для группы {group.name_group}",
                "redirect_url": f"{reverse('admin-schedule')}?group={group.id}"
            })

        except (Group.DoesNotExist, Discipline.DoesNotExist, Teacher.DoesNotExist) as e:
            return JsonResponse({"success": False, "error": str(e)}, status=404)
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=400)

    return JsonResponse({"error": "Метод не разрешен"}, status=405)

def delete_schedule(request, lesson_id):
    if request.method == "POST":
        try:
            ClassSchedule.objects.filter(id=lesson_id).delete()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})

@csrf_exempt
def update_schedule(request, schedule_id):
    """Редактирование существующей записи расписания"""
    if request.method != "POST":
        return JsonResponse({"error": "Метод не разрешен"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))

        schedule = ClassSchedule.objects.filter(id=schedule_id).first()
        if not schedule:
            return JsonResponse({"success": False, "error": "Запись расписания не найдена"}, status=404)

        # Обновляем данные, если они переданы
        group_id = data.get("group_id")
        discipline_id = data.get("discipline_id")
        teacher_id = data.get("teacher_id")
        weekday = data.get("weekday")
        lesson_number = data.get("lesson_number")
        shift = data.get("shift")
        week_type = data.get("week_type")

        if group_id:
            schedule.group = Group.objects.get(id=group_id)
        if discipline_id:
            schedule.discipline = Discipline.objects.get(id=discipline_id)
        if teacher_id:
            schedule.teacher = Teacher.objects.get(id=teacher_id)
        if weekday:
            schedule.weekday = int(weekday)
        if lesson_number:
            schedule.lesson_number = int(lesson_number)
        if shift:
            schedule.shift = int(shift)
        if week_type:
            schedule.week_type = week_type

        schedule.save()

        return JsonResponse({
            "success": True,
            "message": f"Изменения сохранены ({schedule.group.name_group}, {schedule.discipline.name_dis})"
        })

    except (Group.DoesNotExist, Discipline.DoesNotExist, Teacher.DoesNotExist) as e:
        return JsonResponse({"success": False, "error": f"Ошибка данных: {str(e)}"}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)

def get_schedule_details(request, schedule_id):
    """Возвращает данные конкретной записи для редактирования"""
    schedule = ClassSchedule.objects.filter(id=schedule_id).select_related("discipline", "teacher", "group").first()
    if not schedule:
        return JsonResponse({"error": "Запись не найдена"}, status=404)

    data = {
        "id": schedule.id,
        "group": schedule.group.id,
        "discipline": schedule.discipline.id,
        "discipline_name": schedule.discipline.name_dis,
        "teacher": schedule.teacher.id,
        "teacher_name": f"{schedule.teacher.last_name} {schedule.teacher.first_name[0]}.{schedule.teacher.patronymic[0] if schedule.teacher.patronymic else ''}.",
        "weekday": schedule.weekday,
        "lesson_number": schedule.lesson_number,
        "shift": schedule.shift,
        "week_type": schedule.week_type,
    }
    return JsonResponse(data)


# все остальное
def admin_cab(request):
    # --- обработка добавления/редактирования ---
    if request.method == "POST":
        pk = request.POST.get("id")
        number = request.POST.get("number_room")
        floor = request.POST.get("floor")
        status = request.POST.get("status")

        if pk:
            obj = get_object_or_404(Classroom, pk=pk)
            obj.number_room = number
            obj.floor = floor
            obj.status = status
            obj.save()
        else:
            Classroom.objects.create(number_room=number, floor=floor, status=status)
        return redirect("admin-cab")

    # --- Поиск ---
    search_query = request.GET.get("search", "").strip().lower()
    all_rooms = Classroom.objects.all().order_by("floor", "number_room")

    if search_query:
        all_rooms = all_rooms.filter(
            number_room__icontains=search_query
        ) | all_rooms.filter(
            floor__icontains=search_query
        ) | all_rooms.filter(
            status__icontains=search_query
        )

    # --- Пагинация ---
    paginator = Paginator(all_rooms, 10)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # --- Этажный план (всегда полный список, без пагинации) ---
    groups = defaultdict(list)
    for r in all_rooms:
        groups[r.floor].append(r)
    floors = sorted(groups.items(), key=lambda x: x[0])

    # --- AJAX: возвращаем только таблицу + пагинацию ---
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        table_html = render_to_string(
            "dinamic/cab-table.html",
            {"page_obj": page_obj},
            request=request
        )
        paginator_html = render_to_string(
            "dinamic/paginator.html",
            {"page_obj": page_obj},
            request=request
        )
        return JsonResponse({
            "table_html": table_html,
            "paginator_html": paginator_html,
            "current_page": page_obj.number,
            "num_pages": paginator.num_pages,
            "has_next": page_obj.has_next(),
            "has_previous": page_obj.has_previous(),
        })

    # --- Полный рендер ---
    return render(request, "admin/admin-cab.html", {
        "page_obj": page_obj,
        "floors": floors,
    })


def delete_auditorium(request, pk):
    if request.method == "POST":
        auditorium = get_object_or_404(Classroom, pk=pk)
        auditorium.delete()
        return JsonResponse({"success": True})
    return JsonResponse({"success": False}, status=400)




def admin_discipline(request):
    teachers = Teacher.objects.all()
    classrooms = Classroom.objects.all()

    # 🟢 Создание / редактирование предмета
    if request.method == "POST":
        discipline_id = request.POST.get("discipline_id")

        name_dis = request.POST.get("name_dis")
        name_short = request.POST.get("name_short")
        duration_hours = request.POST.get("duration_hours")
        control_type = request.POST.get("control_type")
        status = request.POST.get("status", "active")
        classroom_id = request.POST.get("classroom")
        teachers_ids = request.POST.getlist("teachers")

        if discipline_id:  # редактируем
            discipline = get_object_or_404(Discipline, id=discipline_id)
            discipline.name_dis = name_dis
            discipline.name_short = name_short
            discipline.duration_hours = duration_hours
            discipline.control_type = control_type
            discipline.status = status
            discipline.classroom_id = classroom_id or None
            discipline.save()
            discipline.teachers.set(teachers_ids)
        else:  # создаём
            discipline = Discipline.objects.create(
                name_dis=name_dis,
                name_short=name_short,
                duration_hours=duration_hours,
                control_type=control_type,
                status=status,
                classroom_id=classroom_id or None,
            )
            if teachers_ids:
                discipline.teachers.set(teachers_ids)

        return redirect("admin-discipline")

    # 🟣 AJAX-запрос для модалки редактирования
    if request.GET.get("discipline_id"):
        dis_id = request.GET.get("discipline_id")
        discipline = get_object_or_404(Discipline, id=dis_id)
        teachers_list = list(discipline.teachers.values_list("id", flat=True))
        return JsonResponse({
            "id": discipline.id,
            "name_dis": discipline.name_dis,
            "name_short": discipline.name_short or "",
            "duration_hours": discipline.duration_hours,
            "control_type": discipline.control_type,
            "status": discipline.status,
            "classroom": discipline.classroom.id if discipline.classroom else "",
            "teachers": teachers_list,
        })

    # 🔍 Универсальный поиск
    search_query = request.GET.get("search", "").strip()

    disciplines_list = Discipline.objects.select_related("classroom").prefetch_related("teachers").order_by("name_dis")

    if search_query:
        disciplines_list = disciplines_list.filter(
            Q(name_dis__icontains=search_query) |
            Q(name_short__icontains=search_query) |
            Q(classroom__number_room__icontains=search_query) |
            Q(teachers__last_name__icontains=search_query)
        ).distinct()

    # 🟡 Пагинация
    paginator = Paginator(disciplines_list, 5)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # 🧩 AJAX-пагинация и поиск
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        table_html = render_to_string(
            "dinamic/discipline-table.html",
            {"page_obj": page_obj},
            request=request
        )
        paginator_html = render_to_string(
            "dinamic/paginator.html",
            {"page_obj": page_obj},
            request=request
        )

        total_count = disciplines_list.count()
        active_count = disciplines_list.filter(status="active").count()
        inactive_count = disciplines_list.filter(status="inactive").count()

        return JsonResponse({
            "table_html": table_html,
            "paginator_html": paginator_html,
            "current_page": page_obj.number,
            "num_pages": paginator.num_pages,
            "has_next": page_obj.has_next(),
            "has_previous": page_obj.has_previous(),
            "total_count": total_count,
            "active_count": active_count,
            "inactive_count": inactive_count,
        })
    total_count = disciplines_list.count()
    active_count = disciplines_list.filter(status="active").count()
    inactive_count = disciplines_list.filter(status="inactive").count()

    # --- Основной рендер
    return render(request, "admin/admin-discipline.html", {
        "page_obj": page_obj,
        "teachers": teachers,
        "classrooms": classrooms,
        "CONTROL_CHOICES": Discipline.CONTROL_CHOICES,
        "search_query": search_query,
        "total_count": total_count,
        "active_count": active_count,
        "inactive_count": inactive_count,
    })


@require_POST
def delete_discipline(request, pk):
    try:
        discipline = get_object_or_404(Discipline, pk=pk)
        discipline.delete()
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)

def admin_group(request):
    search_query = request.GET.get("search", "").strip()
    course_filter = request.GET.get("course", "")
    page_number = request.GET.get("page", 1)

    groups = Group.objects.select_related("supervisor").all().order_by("course", "name_group")

    # 🔍 Поиск
    if search_query:
        groups = groups.filter(
            Q(name_group__icontains=search_query) |
            Q(supervisor__last_name__icontains=search_query) |
            Q(supervisor__first_name__icontains=search_query) |
            Q(supervisor__patronymic__icontains=search_query)
        ).distinct()

    # 🎓 Фильтр по курсу
    if course_filter.isdigit():
        groups = groups.filter(course=int(course_filter))

    # 📄 Пагинация
    paginator = Paginator(groups, 8)  # по 8 групп на страницу
    page_obj = paginator.get_page(page_number)

    total_groups = groups.count()
    total_students = sum(g.students_count for g in groups)
    teachers = Teacher.objects.all().order_by("last_name")

    # ✅ POST: создание, редактирование, удаление
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create":
            Group.objects.create(
                name_group=request.POST.get("name"),
                course=request.POST.get("course") or 1,
                shift=request.POST.get("shift") or 1,
                students_count=request.POST.get("students_count") or 0,
                supervisor_id=request.POST.get("supervisor") or None,
            )
            return redirect("admin-group")

        elif action == "edit":
            group = get_object_or_404(Group, id=request.POST.get("group_id"))
            group.name_group = request.POST.get("name")
            group.course = request.POST.get("course") or 1
            group.shift = request.POST.get("shift") or 1
            group.students_count = request.POST.get("students_count") or 0
            group.supervisor_id = request.POST.get("supervisor") or None
            group.save()
            return redirect("admin-group")

        elif action == "delete":
            group = get_object_or_404(Group, id=request.POST.get("group_id"))
            group.delete()
            return redirect("admin-group")

    # ⚡ AJAX: обновление таблицы и пагинатора
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        table_html = render_to_string("dinamic/group-table.html", {"groups": page_obj})
        paginator_html = render_to_string("dinamic/paginator.html", {"page_obj": page_obj})
        return JsonResponse({
            "table": table_html,
            "paginator": paginator_html,
        })

    # 🌐 Основной рендер
    return render(
        request,
        "admin/admin-group.html",
        {
            "groups": page_obj,
            "teachers": teachers,
            "total_groups": total_groups,
            "total_students": total_students,
            "page_obj": page_obj,
        },
    )


# CRUD для преподавателей
def admin_teacher(request):
    
    if request.method == "POST":
        teacher_id = request.POST.get("teacher_id")  
        if teacher_id:  # если редактируем
            teacher = get_object_or_404(Teacher, id=teacher_id)
            teacher.last_name = request.POST.get("last_name")
            teacher.first_name = request.POST.get("first_name")
            teacher.patronymic = request.POST.get("patronymic")
            teacher.phone_number = request.POST.get("phone_number")
            teacher.gmail = request.POST.get("gmail")
            teacher.position = request.POST.get("position")

            if request.FILES.get("photo"):
                teacher.photo = request.FILES.get("photo")

            teacher.save()
        else:  # если создаём
            print("FILES:", request.FILES)
            Teacher.objects.create(
                last_name=request.POST.get("last_name"),
                first_name=request.POST.get("first_name"),
                patronymic=request.POST.get("patronymic"),
                phone_number=request.POST.get("phone_number"),
                gmail=request.POST.get("gmail"),
                position=request.POST.get("position"),
                photo=request.FILES.get("photo"),
            )
        return redirect("admin-teacher")

    teachers = Teacher.objects.prefetch_related("disciplines").all()
    return render(request, "admin/admin-teacher.html", {"teachers": teachers})

@csrf_exempt
def delete_teacher(request, teacher_id):
    if request.method == "POST":
        try:
            teacher = Teacher.objects.get(id=teacher_id)
            teacher.delete()
            return JsonResponse({"success": True})
        except Teacher.DoesNotExist:
            return JsonResponse({"error": "Teacher not found"}, status=404)
    return HttpResponseNotAllowed(["POST"])


# -------------------------------------------------------------------------------------------
# Пользовательская сторона 
#  ------------------------------------------------------------------------------------------


def main(request):
    groups = Group.objects.all()
    # В будущем здесь можно будет фильтровать по группе, смене и т.д.
    schedules = ClassSchedule.objects.select_related(
        "discipline", "teacher", "classroom", "group"
    ).order_by("weekday", "lesson_number")

    # Готовим структуру: {1: [...], 2: [...], 3: [...], ...}
    schedule_by_days = {day: [] for day, _ in ClassSchedule.WEEKDAY_CHOICES}

    for item in schedules:
        schedule_by_days[item.weekday].append(item)

    return render(request, "users/main.html", {
        "schedule": schedule_by_days,
        "groups": groups 
        })

def get_schedule(request):
    group_id = request.GET.get("group_id")
    week_type = request.GET.get("week_type")

    if not group_id:
        return JsonResponse({"html": ""})

    schedule = ClassSchedule.objects.select_related(
        "discipline", "teacher", "classroom", "group"
    ).filter(
        group_id=group_id,
        week_type=week_type
    ).order_by("weekday", "lesson_number")

    schedule_by_days = {day: [] for day, _ in ClassSchedule.WEEKDAY_CHOICES}
    for item in schedule:
        schedule_by_days[item.weekday].append(item)

    html = render_to_string(
        "dinamic-user/user-schedule-main.html",
        {"schedule": schedule_by_days}
    )

    return JsonResponse({"html": html})