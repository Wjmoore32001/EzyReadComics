from django.shortcuts import render


def home(request):
    return render(request, "comics/home.html")