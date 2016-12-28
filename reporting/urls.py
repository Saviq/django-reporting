from django.conf.urls import *

urlpatterns = patterns('reporting.views',
    url('^$', 'report_list', name='reporting-list'),
    url('^(?P<slug>.*)/$', 'view_report', name='reporting-view'),
)
