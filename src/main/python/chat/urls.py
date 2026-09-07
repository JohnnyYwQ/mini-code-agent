from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.index, name="index"),
    path("conversations/new/", views.new_conversation, name="new_conversation"),
    path("api/chat/", views.chat_api, name="chat_api"),
]
