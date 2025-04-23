import hashlib

from django import template

from bots.models import WebhookTriggerTypes

register = template.Library()


@register.filter
def modulo(num, val):
    return int(num) % val


@register.filter
def integer_divide(num, val):
    return int(num) // val


@register.filter
def get_next(value, current_index):
    try:
        return value[current_index + 1]
    except IndexError:
        return value[current_index]  # fallback to current item if next doesn't exist


@register.filter
def participant_color(uuid):
    """Generate a consistent color from a participant's UUID"""
    if not uuid:
        return "#808080"  # Default gray for participants without UUID

    # Generate a hash of the UUID
    hash_object = hashlib.md5(str(uuid).encode())
    hash_hex = hash_object.hexdigest()

    # Use the first 6 characters of the hash as a color code
    # Adjust brightness to ensure readable colors (avoiding too light or dark)
    r = int(hash_hex[:2], 16)
    g = int(hash_hex[2:4], 16)
    b = int(hash_hex[4:6], 16)

    # Ensure minimum brightness
    min_brightness = 64
    r = max(r, min_brightness)
    g = max(g, min_brightness)
    b = max(b, min_brightness)

    # Ensure maximum brightness
    max_brightness = 200
    r = min(r, max_brightness)
    g = min(g, max_brightness)
    b = min(b, max_brightness)

    return f"#{r:02x}{g:02x}{b:02x}"


@register.filter
def md5(value):
    return hashlib.md5(str(value).encode()).hexdigest()


@register.filter
def map_trigger_types(trigger_or_triggers):
    """Transform webhook trigger types to their API codes, works for both single triggers and lists"""
    if hasattr(trigger_or_triggers, "__iter__") and not isinstance(trigger_or_triggers, str):
        return [WebhookTriggerTypes.trigger_type_to_api_code(x) for x in trigger_or_triggers]
    return WebhookTriggerTypes.trigger_type_to_api_code(trigger_or_triggers)
