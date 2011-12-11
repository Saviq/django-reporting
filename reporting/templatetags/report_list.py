from django import template

import reporting

register = template.Library()

class ReportGroupsNode(template.Node):
    def __init__(self, limit, varname):
        self.limit, self.varname = limit, varname

    def __repr__(self):
        return "<GetReportGroups Node>"

    def render(self, context):
        if self.limit:
            count = 0
            context[self.varname] = []
            for group in reporting.get_groups():
                context[self.varname].append(group)
                count += len(group[1].keys())
                if count > self.limit:
                    break
        else:
            context[self.varname] = reporting.get_groups()
        return ''

class DoGetReportGroups:
    """
    Populates a template variable with a list of groups of reports.

    Usage::

        {% get_report_groups [limit] as [varname] %}

    Examples::

        {% get_report_groups as reports %}
        {% get_report_groups 10 as reports %}

    """
    def __init__(self, tag_name):
        self.tag_name = tag_name

    def __call__(self, parser, token):
        tokens = token.contents.split()
        if len(tokens) < 3:
            raise template.TemplateSyntaxError("'%s' statements require two arguments" % self.tag_name)
        if len(tokens) == 3:
            if tokens[1] != 'as':
                raise template.TemplateSyntaxError("First argument in '%s' must be an integer or 'as'" % self.tag_name)
            return ReportGroupsNode(limit=None, varname=tokens[2])
        elif len(tokens) == 4:
            if not tokens[1].isdigit():
                raise template.TemplateSyntaxError("First argument in '%s' must be an integer or 'as'" % self.tag_name)
            elif tokens[2] != 'as':
                raise template.TemplateSyntaxError("Second argument in '%s' must be 'as'" % self.tag_name)
            return ReportGroupsNode(limit=tokens[1], varname=tokens[3])

register.tag('get_report_groups', DoGetReportGroups('get_report_groups'))
