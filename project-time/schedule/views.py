from collections import defaultdict
import json
import datetime
from datetime import time

from asgiref.sync import sync_to_async
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse, HttpResponseNotAllowed
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import (
    Classroom,
    Teacher,
    Direction,
    Discipline,
    Group,
    ClassSchedule,
    GroupWeekState,
    DirectionDiscipline,
    GroupPracticeClassroom,
)


# =========================================================
# ОБЩИЕ ХЕЛПЕРЫ
# =========================================================
def get_week_type():
    current_week = datetime.date.today().isocalendar()[1]
    return "numerator" if current_week % 2 != 0 else "denominator"


LESSON_TIME_BY_SHIFT = {
    1: {
        1: (time(8, 0), time(9, 20)),
        2: (time(9, 30), time(10, 50)),
        3: (time(11, 0), time(12, 20)),
        4: (time(12, 30), time(13, 50)),
    },
    2: {
        1: (time(13, 0), time(14, 20)),
        2: (time(14, 30), time(15, 50)),
        3: (time(16, 0), time(17, 20)),
        4: (time(17, 30), time(18, 50)),
    }
}


def get_latest_group_state(group: Group):
    return (
        GroupWeekState.objects
        .filter(group=group)
        .order_by("-week_number")
        .first()
    )


def build_schedule_by_days(schedule_qs):
    schedule_by_days = {day: [] for day, _ in ClassSchedule.WEEKDAY_CHOICES}
    for item in schedule_qs:
        schedule_by_days[item.weekday].append(item)
    return schedule_by_days


def serialize_group(group: Group):
    return {
        "id": group.id,
        "name_group": group.name_group,
        "course": group.course,
        "shift": group.shift,
        "shift_label": group.get_shift_display() if hasattr(group, "get_shift_display") else str(group.shift),
        "direction_code": group.direction.code if getattr(group, "direction", None) else None,
    }


async def update_classroom_status_async(classroom_id: int):
    classroom = await sync_to_async(
        lambda: Classroom.objects.filter(id=classroom_id).first()
    )()

    if not classroom:
        return None

    if classroom.status == "repair":
        return "repair"

    now = timezone.localtime()
    current_weekday = now.isoweekday()
    current_time = now.time()
    current_week_type = get_week_type()

    lessons = await sync_to_async(list)(
        ClassSchedule.objects.select_related("group")
        .filter(
            classroom_id=classroom_id,
            weekday=current_weekday,
            week_type=current_week_type
        )
    )

    new_status = "free"

    for lesson in lessons:
        group_shift = lesson.group.shift if lesson.group else 1
        lesson_time = LESSON_TIME_BY_SHIFT.get(group_shift, {}).get(lesson.lesson_number)

        if not lesson_time:
            continue

        start_time, end_time = lesson_time

        if start_time <= current_time <= end_time:
            new_status = "busy"
            break

    if classroom.status != new_status:
        classroom.status = new_status
        await sync_to_async(classroom.save)(update_fields=["status"])

    return new_status


async def update_all_classrooms_status_async():
    classroom_ids = await sync_to_async(list)(
        Classroom.objects.values_list("id", flat=True)
    )

    results = []
    for classroom_id in classroom_ids:
        classroom = await sync_to_async(
            lambda cid=classroom_id: Classroom.objects.filter(id=cid).first()
        )()
        status = await update_classroom_status_async(classroom_id)

        if classroom:
            results.append({
                "id": classroom.id,
                "number_room": classroom.number_room,
                "status": status,
            })

    return results


async def refresh_classroom_statuses(request):
    data = await update_all_classrooms_status_async()
    return JsonResponse({
        "success": True,
        "classrooms": data
    })


# =========================================================
# ADMIN SIDE
# =========================================================
def admin_schedule(request):
    group_id = request.GET.get("group")
    shift = request.GET.get("shift")
    direction_id = request.GET.get("direction")
    week_type = request.GET.get("week_type") or get_week_type()

    groups = Group.objects.select_related("direction", "supervisor").all().order_by("course", "name_group")
    directions = Direction.objects.all().order_by("code")

    if shift:
        groups = groups.filter(shift=shift)

    if direction_id:
        groups = groups.filter(direction_id=direction_id)

    group = groups.filter(id=group_id).first() if group_id else None

    schedule_qs = (
        ClassSchedule.objects
        .filter(week_type=week_type)
        .select_related("discipline", "teacher", "classroom", "group")
        .order_by("weekday", "lesson_number")
    )

    if group:
        schedule_qs = schedule_qs.filter(group=group)

    if shift:
        schedule_qs = schedule_qs.filter(group__shift=shift)

    schedule_by_day = {i: [] for i in range(1, 6)}
    for lesson in schedule_qs:
        schedule_by_day[lesson.weekday].append(lesson)

    context = {
        "groups": groups,
        "directions": directions,
        "selected_group": group,
        "selected_direction": int(direction_id) if direction_id and direction_id.isdigit() else None,
        "selected_shift": int(shift) if shift and shift.isdigit() else (group.shift if group else None),
        "selected_week_type": week_type,
        "today": timezone.now().date(),
        "schedule_by_day": schedule_by_day,
    }
    return render(request, "admin/admin-schedule-main.html", context)


def get_next_lesson(request):
    group_id = request.GET.get("group")
    weekday = request.GET.get("weekday")
    week_type = request.GET.get("week_type")

    if not group_id or not weekday or not week_type:
        return JsonResponse({"error": "Не хватает параметров"}, status=400)

    try:
        existing = ClassSchedule.objects.filter(
            group_id=group_id,
            weekday=weekday,
            week_type=week_type
        ).values_list("lesson_number", flat=True)

        all_lessons = [1, 2, 3, 4]
        free_lessons = [n for n in all_lessons if n not in existing]
        next_lesson = min(free_lessons) if free_lessons else 1

        return JsonResponse({"next_lesson": next_lesson})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


def load_schedule_table(request):
    group_id = request.GET.get("group")
    shift = request.GET.get("shift")
    week_type = request.GET.get("week_type") or get_week_type()

    group = (
        Group.objects
        .select_related("supervisor", "direction")
        .filter(id=group_id)
        .first()
        if group_id else None
    )

    current_state = get_latest_group_state(group) if group else None

    schedule_qs = (
        ClassSchedule.objects
        .filter(week_type=week_type)
        .select_related("discipline", "teacher", "classroom", "group")
        .order_by("weekday", "lesson_number")
    )

    if group:
        schedule_qs = schedule_qs.filter(group=group)

    if shift:
        schedule_qs = schedule_qs.filter(group__shift=shift)

    schedule_by_day = {i: [] for i in range(1, 6)}
    for lesson in schedule_qs:
        schedule_by_day[lesson.weekday].append(lesson)

    html = render_to_string(
        "dinamic/schedule-table.html",
        {
            "schedule_by_day": schedule_by_day,
            "selected_group": group,
            "selected_week_type": week_type,
            "current_state": current_state,
        },
        request=request
    )

    return JsonResponse({
        "html": html,
        "group_state": current_state.state if current_state else None,
        "practice_name": current_state.practice_name if current_state else None,
    })


@csrf_exempt
def create_schedule(request):
    if request.method != "POST":
        return JsonResponse({"error": "Метод не разрешен"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))

        group_id = data.get("group_id")
        discipline_id = data.get("discipline_id")
        teacher_id = data.get("teacher_id")
        weekday = data.get("weekday")
        lesson_number = data.get("lesson_number")
        week_type = data.get("week_type", get_week_type())
        room_input = data.get("room")

        if not group_id:
            return JsonResponse({"success": False, "error": "Не выбрана группа!"}, status=400)

        if not discipline_id or not teacher_id:
            return JsonResponse({"success": False, "error": "Не выбрана дисциплина или преподаватель!"}, status=400)

        if not weekday or not lesson_number:
            return JsonResponse({"success": False, "error": "Не указан день недели или номер пары!"}, status=400)

        group = Group.objects.select_related("direction").get(id=group_id)
        discipline = Discipline.objects.get(id=discipline_id)
        teacher = Teacher.objects.get(id=teacher_id)

        current_state = get_latest_group_state(group)
        if current_state and current_state.state != "theory":
            return JsonResponse({
                "success": False,
                "error": f"Для группы сейчас нельзя создавать расписание. Состояние: {current_state.get_state_display()}"
            }, status=400)

        classroom_obj = None
        if room_input:
            classroom_obj = Classroom.objects.filter(number_room=room_input).first()
            if not classroom_obj:
                return JsonResponse({
                    "success": False,
                    "error": f"Кабинет '{room_input}' не найден в списке аудиторий!"
                }, status=400)

            if classroom_obj.status == "repair":
                return JsonResponse({
                    "success": False,
                    "error": f"Кабинет '{room_input}' находится в ремонте и не может быть добавлен в расписание!"
                }, status=400)

        weekday = int(weekday)
        lesson_number = int(lesson_number)

        duplicate = ClassSchedule.objects.filter(
            group=group,
            weekday=weekday,
            lesson_number=lesson_number,
            week_type=week_type
        ).exists()

        if duplicate:
            return JsonResponse({
                "success": False,
                "error": "На эту пару уже существует занятие для выбранной группы."
            }, status=400)

        if classroom_obj:
            room_busy = ClassSchedule.objects.filter(
                classroom=classroom_obj,
                weekday=weekday,
                lesson_number=lesson_number,
                week_type=week_type
            ).exists()

            if room_busy:
                return JsonResponse({
                    "success": False,
                    "error": f"Кабинет '{room_input}' уже занят на эту пару."
                }, status=400)

        ClassSchedule.objects.create(
            group=group,
            discipline=discipline,
            teacher=teacher,
            weekday=weekday,
            lesson_number=lesson_number,
            week_type=week_type,
            classroom=classroom_obj
        )

        return JsonResponse({
            "success": True,
            "message": f"Занятие добавлено для группы {group.name_group}",
            "redirect_url": f"{reverse('admin-schedule')}?group={group.id}"
        })

    except Group.DoesNotExist:
        return JsonResponse({"success": False, "error": "Группа не найдена"}, status=404)
    except Discipline.DoesNotExist:
        return JsonResponse({"success": False, "error": "Дисциплина не найдена"}, status=404)
    except Teacher.DoesNotExist:
        return JsonResponse({"success": False, "error": "Преподаватель не найден"}, status=404)
    except Exception as e:
        print(f"Ошибка при создании: {e}")
        return JsonResponse({"success": False, "error": f"Системная ошибка: {str(e)}"}, status=400)


def delete_schedule(request, lesson_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request"}, status=405)

    try:
        lesson = ClassSchedule.objects.filter(id=lesson_id).first()
        if not lesson:
            return JsonResponse({"success": False, "error": "Занятие не найдено"}, status=404)

        lesson.delete()
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@csrf_exempt
def update_schedule(request, schedule_id):
    if request.method != "POST":
        return JsonResponse({"error": "Метод не разрешен"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))

        schedule = (
            ClassSchedule.objects
            .select_related("group", "discipline", "teacher", "classroom")
            .filter(id=schedule_id)
            .first()
        )
        if not schedule:
            return JsonResponse({"success": False, "error": "Запись расписания не найдена"}, status=404)

        group_id = data.get("group_id")
        discipline_id = data.get("discipline_id")
        teacher_id = data.get("teacher_id")
        weekday = data.get("weekday")
        lesson_number = data.get("lesson_number")
        week_type = data.get("week_type")
        room_input = data.get("room")

        new_group = schedule.group
        if group_id:
            new_group = Group.objects.get(id=group_id)

        current_state = get_latest_group_state(new_group)
        if current_state and current_state.state != "theory":
            return JsonResponse({
                "success": False,
                "error": f"Для группы сейчас нельзя редактировать расписание. Состояние: {current_state.get_state_display()}"
            }, status=400)

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
        if week_type:
            schedule.week_type = week_type

        if room_input is not None:
            if room_input == "":
                schedule.classroom = None
            else:
                classroom_obj = Classroom.objects.filter(number_room=room_input).first()
                if not classroom_obj:
                    return JsonResponse({
                        "success": False,
                        "error": f"Кабинет '{room_input}' не найден в списке аудиторий!"
                    }, status=400)

                if classroom_obj.status == "repair":
                    return JsonResponse({
                        "success": False,
                        "error": f"Кабинет '{room_input}' находится в ремонте и не может быть назначен в расписание!"
                    }, status=400)

                room_busy = ClassSchedule.objects.filter(
                    classroom=classroom_obj,
                    weekday=schedule.weekday,
                    lesson_number=schedule.lesson_number,
                    week_type=schedule.week_type
                ).exclude(id=schedule.id).exists()

                if room_busy:
                    return JsonResponse({
                        "success": False,
                        "error": f"Кабинет '{room_input}' уже занят на эту пару."
                    }, status=400)

                schedule.classroom = classroom_obj

        duplicate = ClassSchedule.objects.filter(
            group=schedule.group,
            weekday=schedule.weekday,
            lesson_number=schedule.lesson_number,
            week_type=schedule.week_type
        ).exclude(id=schedule.id).exists()

        if duplicate:
            return JsonResponse({
                "success": False,
                "error": "На эту пару уже существует занятие для выбранной группы."
            }, status=400)

        schedule.save()

        return JsonResponse({
            "success": True,
            "message": f"Изменения сохранены ({schedule.group.name_group}, {schedule.discipline.name_dis})"
        })

    except (Group.DoesNotExist, Discipline.DoesNotExist, Teacher.DoesNotExist) as e:
        return JsonResponse({"success": False, "error": f"Ошибка данных: {str(e)}"}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


def search_discipline(request):
    q = request.GET.get("q", "")
    disciplines = Discipline.objects.filter(name_dis__icontains=q)[:10]

    data = [
        {"id": d.id, "name": d.name_dis}
        for d in disciplines
    ]

    return JsonResponse(data, safe=False)


def get_discipline_details(request, discipline_id):
    discipline = Discipline.objects.filter(id=discipline_id).first()
    if not discipline:
        return JsonResponse({"error": "Дисциплина не найдена"}, status=404)

    teachers = discipline.teachers.all()
    teachers_data = [
        {"id": t.id, "name": f"{t.last_name} {t.first_name}"}
        for t in teachers
    ]

    classrooms = discipline.classroom.all()
    rooms_data = [str(c.number_room) for c in classrooms if c.status != "repair"]

    return JsonResponse({
        "teachers": teachers_data,
        "rooms": rooms_data
    })


def get_groups_by_shift(request):
    shift = request.GET.get("shift")
    direction_id = request.GET.get("direction")

    groups = Group.objects.select_related("direction").all().order_by("course", "name_group")

    if shift:
        groups = groups.filter(shift=shift)

    if direction_id:
        groups = groups.filter(direction_id=direction_id)

    data = {
        "groups": [
            {
                "id": g.id,
                "name_group": g.name_group,
                "course": g.course,
                "shift": g.shift,
                "direction_id": g.direction.id if g.direction else None,
                "direction_code": g.direction.code if g.direction else None,
            }
            for g in groups
        ]
    }
    return JsonResponse(data)


def get_group_shift(request):
    group_id = request.GET.get("group_id")
    group = Group.objects.filter(id=group_id).first()

    if not group:
        return JsonResponse({"error": "Группа не найдена"}, status=404)

    return JsonResponse({
        "shift": group.shift
    })


def get_schedule_details(request, schedule_id):
    schedule = (
        ClassSchedule.objects
        .filter(id=schedule_id)
        .select_related("discipline", "teacher", "group", "classroom")
        .first()
    )
    if not schedule:
        return JsonResponse({"error": "Запись не найдена"}, status=404)

    data = {
        "id": schedule.id,
        "group": schedule.group.id,
        "discipline": schedule.discipline.id,
        "discipline_name": schedule.discipline.name_dis,
        "teacher": schedule.teacher.id if schedule.teacher else None,
        "teacher_name": (
            f"{schedule.teacher.last_name} {schedule.teacher.first_name[0]}."
            f"{schedule.teacher.patronymic[0] if schedule.teacher and schedule.teacher.patronymic else ''}."
            if schedule.teacher else ""
        ),
        "weekday": schedule.weekday,
        "lesson_number": schedule.lesson_number,
        "shift": schedule.group.shift,
        "week_type": schedule.week_type,
        "room": schedule.classroom.number_room if schedule.classroom else "",
    }
    return JsonResponse(data)


async def admin_cab(request):
    await update_all_classrooms_status_async()

    if request.method == "POST":
        pk = request.POST.get("id")
        number = request.POST.get("number_room")
        floor = request.POST.get("floor")
        status = request.POST.get("status")

        if pk:
            obj = await sync_to_async(get_object_or_404)(Classroom, pk=pk)
            obj.number_room = number
            obj.floor = floor
            obj.status = status
            await sync_to_async(obj.save)()
        else:
            await sync_to_async(Classroom.objects.create)(
                number_room=number,
                floor=floor,
                status=status
            )
        return redirect("admin-cab")

    search_query = request.GET.get("search", "").strip().lower()

    all_rooms = await sync_to_async(list)(
        Classroom.objects.all().order_by("floor", "number_room")
    )

    if search_query:
        all_rooms = [
            room for room in all_rooms
            if (
                search_query in str(room.number_room).lower()
                or search_query in str(room.floor).lower()
                or search_query in str(room.status).lower()
            )
        ]

    paginator = Paginator(all_rooms, 10)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    groups = defaultdict(list)
    for r in all_rooms:
        groups[r.floor].append(r)
    floors = sorted(groups.items(), key=lambda x: x[0])

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        table_html = render_to_string("dinamic/cab-table.html", {"page_obj": page_obj}, request=request)
        paginator_html = render_to_string("dinamic/paginator.html", {"page_obj": page_obj}, request=request)
        return JsonResponse({
            "table_html": table_html,
            "paginator_html": paginator_html,
            "current_page": page_obj.number,
            "num_pages": paginator.num_pages,
            "has_next": page_obj.has_next(),
            "has_previous": page_obj.has_previous(),
        })

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
    classrooms = Classroom.objects.exclude(status="repair")
    directions = Direction.objects.all().order_by("code")

    if request.method == "POST":
        discipline_id = request.POST.get("discipline_id")

        name_dis = request.POST.get("name_dis")
        name_short = request.POST.get("name_short")
        duration_hours = request.POST.get("duration_hours")
        control_type = request.POST.get("control_type")
        status = request.POST.get("status", "active")
        classroom_ids = request.POST.getlist("classroom")
        teachers_ids = request.POST.getlist("teachers")
        direction_values = request.POST.getlist("direction")
        course_values = request.POST.getlist("course")

        valid_classroom_ids = list(
            Classroom.objects
            .exclude(status="repair")
            .filter(id__in=classroom_ids)
            .values_list("id", flat=True)
        )

        valid_direction_ids = []
        for direction in direction_values:
            try:
                direction_int = int(direction)
                if Direction.objects.filter(id=direction_int).exists():
                    valid_direction_ids.append(direction_int)
            except (TypeError, ValueError):
                continue

        valid_courses = []
        for course in course_values:
            try:
                course_int = int(course)
                if course_int in [1, 2, 3, 4]:
                    valid_courses.append(course_int)
            except (TypeError, ValueError):
                continue

        if discipline_id:
            discipline = get_object_or_404(Discipline, id=discipline_id)
            discipline.name_dis = name_dis
            discipline.name_short = name_short
            discipline.duration_hours = duration_hours
            discipline.control_type = control_type
            discipline.status = status
            discipline.save()
        else:
            discipline = Discipline.objects.create(
                name_dis=name_dis,
                name_short=name_short,
                duration_hours=duration_hours,
                control_type=control_type,
                status=status,
            )

        discipline.teachers.set(teachers_ids)
        discipline.classroom.set(valid_classroom_ids)

        DirectionDiscipline.objects.filter(discipline=discipline).delete()

        for direction_id in valid_direction_ids:
            for course in valid_courses:
                DirectionDiscipline.objects.create(
                    direction_id=direction_id,
                    discipline=discipline,
                    is_required=True,
                    course=course
                )

        return redirect("admin-discipline")

    if request.GET.get("discipline_id"):
        dis_id = request.GET.get("discipline_id")
        discipline = get_object_or_404(Discipline, id=dis_id)

        teachers_list = list(discipline.teachers.values_list("id", flat=True))
        classrooms_list = list(
            discipline.classroom.exclude(status="repair").values_list("id", flat=True)
        )

        direction_links = (
            DirectionDiscipline.objects
            .filter(discipline=discipline)
            .select_related("direction")
        )

        directions_list = list(
            direction_links.values_list("direction_id", flat=True).distinct()
        )

        courses_list = list(
            direction_links.exclude(course__isnull=True).values_list("course", flat=True).distinct()
        )

        return JsonResponse({
            "id": discipline.id,
            "name_dis": discipline.name_dis,
            "name_short": discipline.name_short or "",
            "duration_hours": discipline.duration_hours,
            "control_type": discipline.control_type,
            "status": discipline.status,
            "classroom": classrooms_list,
            "teachers": teachers_list,
            "directions": directions_list,
            "courses": courses_list,
        })

    search_query = request.GET.get("search", "").strip()
    disciplines_list = (
        Discipline.objects
        .prefetch_related("classroom", "teachers", "direction_discipline_links__direction")
        .order_by("name_dis")
    )

    if search_query:
        disciplines_list = disciplines_list.filter(
            Q(name_dis__icontains=search_query) |
            Q(name_short__icontains=search_query) |
            Q(classroom__number_room__icontains=search_query) |
            Q(teachers__last_name__icontains=search_query) |
            Q(direction_discipline_links__direction__code__icontains=search_query)
        ).distinct()

    paginator = Paginator(disciplines_list, 5)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        table_html = render_to_string("dinamic/discipline-table.html", {"page_obj": page_obj}, request=request)
        paginator_html = render_to_string("dinamic/paginator.html", {"page_obj": page_obj}, request=request)

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

    return render(request, "admin/admin-discipline.html", {
        "page_obj": page_obj,
        "teachers": teachers,
        "classrooms": classrooms,
        "directions": directions,
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

    groups = Group.objects.select_related("supervisor", "direction").all().order_by("course", "name_group")

    if search_query:
        groups = groups.filter(
            Q(name_group__icontains=search_query) |
            Q(supervisor__last_name__icontains=search_query) |
            Q(supervisor__first_name__icontains=search_query) |
            Q(supervisor__patronymic__icontains=search_query) |
            Q(direction__code__icontains=search_query)
        ).distinct()

    if course_filter.isdigit():
        groups = groups.filter(course=int(course_filter))

    paginator = Paginator(groups, 10)
    page_obj = paginator.get_page(page_number)

    total_groups = groups.count()
    total_students = sum(g.students_count for g in groups)
    teachers = Teacher.objects.all().order_by("last_name")

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

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        table_html = render_to_string("dinamic/group-table.html", {"groups": page_obj}, request=request)
        paginator_html = render_to_string("dinamic/paginator.html", {"page_obj": page_obj}, request=request)
        return JsonResponse({
            "table": table_html,
            "paginator": paginator_html,
        })

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


def admin_teacher(request):
    if request.method == "POST":
        teacher_id = request.POST.get("teacher_id")
        if teacher_id:
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
        else:
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


# =========================================================
# USER SIDE
# =========================================================
def main(request, any_path=None):
    groups = Group.objects.select_related("direction").all().order_by("course", "name_group")

    selected_group_id = request.GET.get("group")
    selected_group = None
    current_state = None
    schedule_by_days = {day: [] for day, _ in ClassSchedule.WEEKDAY_CHOICES}

    if selected_group_id:
        selected_group = Group.objects.select_related("direction").filter(id=selected_group_id).first()
        if selected_group:
            current_state = get_latest_group_state(selected_group)

            if current_state and current_state.state == "theory":
                week_type = get_week_type()
                schedules = (
                    ClassSchedule.objects.select_related("discipline", "teacher", "classroom", "classroom2","group")
                    .filter(group=selected_group, week_type=week_type)
                    .order_by("weekday", "lesson_number")
                )
                schedule_by_days = build_schedule_by_days(schedules)

    return render(request, "users/main.html", {
        "schedule": schedule_by_days,
        "groups": groups,
        "selected_group": selected_group,
        "current_state": current_state,
    })


def get_schedule(request):
    group_id = request.GET.get("group_id")
    week_type = request.GET.get("week_type") or get_week_type()

    if not group_id:
        return JsonResponse({
            "mode": "empty",
            "html": "",
            "state": None,
        })

    group = Group.objects.select_related("direction").filter(id=group_id).first()
    if not group:
        return JsonResponse({
            "mode": "empty",
            "html": "",
            "error": "Группа не найдена",
        }, status=404)

    current_state = get_latest_group_state(group)

    if not current_state:
        html = render_to_string(
            "dinamic-user/user-schedule-empty.html",
            {
                "group": group,
                "message": "Для группы пока нет состояния на текущую неделю."
            },
            request=request
        )
        return JsonResponse({
            "mode": "empty",
            "state": None,
            "group": serialize_group(group),
            "html": html,
        })

    if current_state.state == "practice":
        html = render_to_string(
            "dinamic-user/user-schedule-practice.html",
            {
                "group": group,
                "current_state": current_state,
            },
            request=request
        )
        return JsonResponse({
            "mode": "practice",
            "state": current_state.state,
            "group": serialize_group(group),
            "practice_name": current_state.practice_name,
            "practice_code": current_state.practice_code,
            "html": html,
        })

    practice_classroom = None

    if current_state.practice_code == "УП":
        practice_classroom = (
            GroupPracticeClassroom.objects
            .select_related("classroom")
            .filter(
                group=group,
                week_number=current_state.week_number
            )
            .first()
        )

    html = render_to_string(
        "dinamic-user/user-schedule-practice.html",
        {
            "group": group,
            "current_state": current_state,
            "practice_classroom": practice_classroom,
        },
        request=request
    )

    if current_state.state in {"vacation", "holiday", "no_schedule"}:
        html = render_to_string(
            "dinamic-user/user-schedule-empty.html",
            {
                "group": group,
                "current_state": current_state,
                "message": current_state.practice_name or "На этой неделе расписание не выдается."
            },
            request=request
        )
        return JsonResponse({
            "mode": "empty",
            "state": current_state.state,
            "group": serialize_group(group),
            "html": html,
        })

    schedule = (
        ClassSchedule.objects.select_related("discipline", "teacher", "classroom", "classroom2","group")
        .filter(group_id=group_id, week_type=week_type)
        .order_by("weekday", "lesson_number")
    )

    schedule_by_days = build_schedule_by_days(schedule)

    html = render_to_string(
        "dinamic-user/user-schedule-main.html",
        {
            "schedule": schedule_by_days,
            "group": group,
            "current_state": current_state,
        },
        request=request
    )

    return JsonResponse({
        "mode": "schedule",
        "state": current_state.state,
        "group": serialize_group(group),
        "html": html,
    })


def api_group_state(request, group_id):
    group = get_object_or_404(Group.objects.select_related("direction"), id=group_id)
    current_state = get_latest_group_state(group)

    if not current_state:
        return JsonResponse({
            "group": serialize_group(group),
            "state": None,
        })

    return JsonResponse({
        "group": serialize_group(group),
        "state": {
            "week_number": current_state.week_number,
            "state": current_state.state,
            "practice_code": current_state.practice_code,
            "practice_name": current_state.practice_name,
            "start_date": current_state.start_date.isoformat() if current_state.start_date else None,
            "end_date": current_state.end_date.isoformat() if current_state.end_date else None,
        }
    })


def api_groups_full(request):
    groups = Group.objects.select_related("direction").all().order_by("course", "name_group")
    return JsonResponse({
        "groups": [serialize_group(group) for group in groups]
    })





# -------------------------------
# TEACHER SIDE BAR
# -------------------------------



def get_teacher_full_name(teacher):
    return f"{teacher.last_name} {teacher.first_name} {teacher.patronymic or ''}".strip()


def teacher(request):
    all_teachers = Teacher.objects.all().order_by("last_name", "first_name", "patronymic")

    unique = {}
    for t in all_teachers:
        name = get_teacher_full_name(t)
        if name not in unique:
            unique[name] = t

    teachers = list(unique.values())

    return render(request, "teacher/teacher.html", {
        "teachers": teachers,
        "selected_week_type": request.GET.get("week_type") or get_week_type(),
    })


def get_teacher_schedule(request):
    teacher_id = request.GET.get("teacher_id")
    week_type = request.GET.get("week_type") or get_week_type()

    if not teacher_id:
        return JsonResponse({"success": False, "error": "Не выбран преподаватель"}, status=400)

    teacher_obj = Teacher.objects.filter(id=teacher_id).first()

    if not teacher_obj:
        return JsonResponse({"success": False, "error": "Преподаватель не найден"}, status=404)

    teacher_name = get_teacher_full_name(teacher_obj)

    same_teachers = Teacher.objects.filter(
        last_name=teacher_obj.last_name,
        first_name=teacher_obj.first_name,
        patronymic=teacher_obj.patronymic
    )

    teacher_ids = same_teachers.values_list("id", flat=True)

    schedule = {
        "1": {str(day): {str(pair): [] for pair in range(1, 5)} for day in range(1, 7)},
        "2": {str(day): {str(pair): [] for pair in range(1, 5)} for day in range(1, 7)},
    }

    lessons = (
        ClassSchedule.objects
        .select_related("discipline", "group", "classroom", "teacher")
        .filter(teacher_id__in=teacher_ids, week_type=week_type)
        .order_by("group__shift", "weekday", "lesson_number", "group__name_group")
    )

    for lesson in lessons:
        if not lesson.group:
            continue

        shift = str(lesson.group.shift)
        weekday = str(lesson.weekday)
        pair = str(lesson.lesson_number)

        if shift not in schedule:
            continue

        if weekday not in schedule[shift]:
            continue

        if pair not in schedule[shift][weekday]:
            continue

        schedule[shift][weekday][pair].append({
            "id": lesson.id,
            "discipline": lesson.discipline.name_dis if lesson.discipline else "Без предмета",
            "group": lesson.group.name_group if lesson.group else "Без группы",
            "room": lesson.classroom.number_room if lesson.classroom else "—",
            "weekday": lesson.weekday,
            "lesson_number": lesson.lesson_number,
            "shift": lesson.group.shift,
        })

    return JsonResponse({
        "success": True,
        "teacher": {
            "id": teacher_obj.id,
            "name": teacher_name,
        },
        "week_type": week_type,
        "schedule": schedule,
    })


def main2(request ):
    return render(request, "main/main.html")