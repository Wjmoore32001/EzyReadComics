from django import template

from reading.models import VolumeProgress


register = template.Library()


@register.simple_tag
def volume_progress_for(volume, user):
    if not getattr(user, "is_authenticated", False):
        return None

    if not volume or not getattr(volume, "id", None):
        return None

    return VolumeProgress.objects.filter(
        user=user,
        volume=volume,
    ).first()


@register.simple_tag
def volume_status_choices():
    return VolumeProgress.STATUS_CHOICES
