import imp
from base import Report, BandReport, DetailBandReport, CrossReport, \
                 CrossGridReport, current_year, current_month, \
                 GROUP_BY_VAR, SORTTYPE_VAR, SORT_VAR



_registry = {}
_groups = {}

def register(slug, group, klass):
    _registry[slug] = klass
    try:
        _groups[group][slug] = klass
    except KeyError:
        _groups[group] = {slug: klass}

def get_report(slug):
    try:
        return _registry[slug]
    except KeyError:
        raise Exception("No such report '%s'" % slug)
    
def get_group(group):
    try:
        return _groups[group]
    except KeyError:
        raise Exception("No such group '%s'" % group)

def get_groups():
    return _groups.items()

def get_reports():
    return _registry.items()


def autodiscover():
    from django.conf import settings
    REPORTING_SOURCE_FILE =  getattr(settings, 'REPORTING_SOURCE_FILE', 'reports') 
    for app in settings.INSTALLED_APPS:
        try:
            app_path = __import__(app, {}, {}, [app.split('.')[-1]]).__path__
        except AttributeError:
            continue

        try:
            imp.find_module(REPORTING_SOURCE_FILE, app_path)
        except ImportError:
            continue
        __import__('%s.%s' % (app, REPORTING_SOURCE_FILE))


def DistinctCount(field):
    from django.db.models import Count
    return Count(field, distinct=True)
