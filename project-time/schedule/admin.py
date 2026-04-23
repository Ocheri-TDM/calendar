from django.contrib import admin
from .models import Teacher, Group, Classroom, Discipline, ClassSchedule


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "patronymic", "position", "gmail", "phone_number")
    search_fields = ("last_name", "first_name", "gmail", "position")
    list_filter = ("position",)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name_group", "supervisor", "students_count")
    search_fields = ("name_group",)
    list_filter = ("supervisor",)


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ("number_room", "floor", "status")
    list_filter = ("floor", "status")
    search_fields = ("number_room",)


@admin.register(Discipline)
class DisciplineAdmin(admin.ModelAdmin):
    list_display = ("name_dis", "duration_hours", "control_type", "status")
    list_filter = ("status", "classroom")
    search_fields = ("name_dis", "control_type")




@admin.register(ClassSchedule)
class ClassScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "discipline",
        "teacher",
        "weekday",
        "lesson_number",
        "week_type",
        "classroom",
    )

    list_filter = (
        "week_type",
        "weekday",
        "group__shift",  # если хочешь фильтр по смене
    )
    search_fields = (
        "group__name_group",
        "discipline__name_dis",
        "teacher__last_name",
        "teacher__first_name",
        "classroom__number_room",
    )
    ordering = ("weekday", "lesson_number", "group")
    list_per_page = 25

    # Показываем выпадающие списки вместо больших таблиц выбора
    autocomplete_fields = ("group", "discipline", "teacher", "classroom")

    # Автоматически заполняем start_time и end_time при сохранении
    def save_model(self, request, obj, form, change):
        obj.save()  # save() уже всё расставляет автоматически