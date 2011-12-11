from django.shortcuts import render

import reporting

def report_list(request):
    return render(request, 'reporting/list.html')

def view_report(request, slug):
    report = reporting.get_report(slug)(request)
    data = {'report': report, 'title':report.verbose_name}
    return render(request, report.template_name, data)