from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin-schedule", views.admin_schedule, name="admin-schedule"),
    path("search-discipline/", views.search_discipline, name="search_discipline"),
    path("get-discipline-details/<int:discipline_id>/", views.get_discipline_details, name="get_discipline_details"),
    path("api/groups/", views.get_groups_by_shift, name="api_groups_by_shift"),
    
    path("create-schedule/", views.create_schedule, name="create_schedule"),
    path("get-schedule-details/<int:schedule_id>/", views.get_schedule_details, name="get-schedule-details"),
    path("update-schedule/<int:schedule_id>/", views.update_schedule, name="update-schedule"),

    path("api/get-next-lesson/", views.get_next_lesson, name="get_next_lesson"),
    path("load-schedule-table/", views.load_schedule_table, name="load_schedule_table"),
    path("api/get-group-shift/", views.get_group_shift, name="get-group-shift"),


    path('admin-cab', views.admin_cab, name='admin-cab'),
    path("auditoriums/delete/<int:pk>/", views.delete_auditorium, name="delete_auditorium"),


    path('admin-discipline', views.admin_discipline, name='admin-discipline'),
    path("delete-discipline/<int:pk>/", views.delete_discipline, name="delete_discipline"),

    path('admin-teacher', views.admin_teacher, name='admin-teacher'),
    path("delete-teacher/<int:teacher_id>/", views.delete_teacher, name="delete_teacher"),

    path('admin-group', views.admin_group, name='admin-group'),
    path('', views.main, name='main'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)