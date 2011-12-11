# -*- coding: utf-8 -*-

from django.template import Library

register = Library()

@register.inclusion_tag('admin/filter.html')
def report_choices(title, choices):
    return {'title': title, 'choices' : choices}

