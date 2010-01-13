from django.contrib.admin.options import IncorrectLookupParameters
from django.utils.http import urlencode
from django.utils.encoding import smart_str
from django.db import models
from django.db.models.fields.related import RelatedField
from django.db.models.fields import FieldDoesNotExist
from django.utils.text import capfirst
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.core.urlresolvers import reverse

from filterspecs import *


def get_model_field(model, name):
    return model._meta.get_field(name)

def get_lookup_value(model, original, lookup):
    parts = lookup.split('__')
    try:
        field = get_model_field(model, parts[0])
        if not isinstance(field, RelatedField):
            return original
        rel_model = field.rel.to
        if len(parts) == 1:
            return unicode(rel_model.objects.get(pk=original))
        next_lookup = '__'.join(parts[1:])
        return get_lookup_value(rel_model, original, next_lookup)
    except:
        return original
    


class ModelAdminMock(object):
    def __init__(self, model):
        self.model = model
        
    def queryset(self, request):
        return self.model.objects.all()
    

GROUP_BY_VAR = 'gruop_by_'
SORT_VAR = 's'
SORTTYPE_VAR = 'st'
DETAILS_SWITCH_VAR = 'ds'


class Header(object):
    def __init__(self, report, ind, text):
        self.text = text
        self.css_class = ''
        order_type = 'asc'
        
        if ind == report.sort_by:
            order_type = {'asc':'desc', 'desc': 'asc'}[report.sort_type]
            self.css_class = 'sorted %sending' % report.sort_type
        self.url = report.get_query_string({SORT_VAR: ind, SORTTYPE_VAR: order_type})

class Report(object):
    list_filter = None
    detail_list_display = None
    date_hierarchy = None
    aggregate = None
    
    def __init__(self, request):
        self.request = request
        admin_mock = ModelAdminMock(self.model)
        
        self.annotate, self.annotate_titles = self.split_annotate_titles(self.annotate)
        self.aggregate, self.aggregate_titles = self.split_annotate_titles(self.aggregate)
        self.group_by, self.group_by_titles = self.split_titles(self.group_by)
        if self.detail_list_display and not hasattr(self, 'detail_link_fields'):
            self.detail_link_fields = [self.detail_list_display[0]]
        
        self.params = dict(self.request.GET.items())
        self.selected_group_by = self.get_group_by_field()
        self.sort_by = int(self.params.get(SORT_VAR, '0'))
        self.show_details = self.params.get(DETAILS_SWITCH_VAR) is not None
        self.sort_type = self.params.get(SORTTYPE_VAR, 'asc')
        self.filter_specs, self.has_filters = self.get_filters(admin_mock)
        self.get_results()
        self.query_set = self.get_queryset()
        self.get_aggregation()
        
    
    def get_results(self):
        qs = self.get_queryset()
        
        annotate_args = {}
        for field, func in self.annotate:
            annotate_args[field] = func(field)
        
        values = [self.selected_group_by]
        
        rows = qs.values(*values).annotate(**annotate_args).order_by(values[0])
        
        self.results = []
        for row in rows:
            row_vals = [self.get_value(row, self.selected_group_by)]
            for field, func in self.annotate:
                row_vals.append(row[field])
            details = None
            if self.detail_list_display and self.show_details:
                details = self.get_details(row)
            self.results.append({'values': row_vals, 
                                 'details': details})
        
        self.sort_results()
    
    def sort_results(self):
        """
        Sorting is performed manually since queries are with annotations
        """
        def cmp(x,y):
            if self.sort_type == 'asc':
                val1 = x['values'][self.sort_by]
                val2 = y['values'][self.sort_by]
            else:
                val1 = y['values'][self.sort_by]
                val2 = x['values'][self.sort_by]
            if val2 > val1:
                return -1
            elif val2 < val1:
                return 1
            return 0
        self.results.sort(cmp)
    
    def get_aggregation(self):
        if self.aggregate is None:
            return None
        aggregate_args = {}
        for field, func in self.aggregate:
            aggregate_args[field] = func(field)
        
        data = self.get_queryset().aggregate(**aggregate_args)
        
        result = []
        ind = 0
        for field, func in self.aggregate:
            title = self.aggregate_titles[ind]
            #field_name = self.get_lookup_title(field)
            #text = '%s %s' % (field_name, func.__name__.replace ('Sum', 'Total'))
            result.append((title, data[field]))
            ind += 1
        return result
            
    
    def get_value(self, data, field):
        value = data[field]
        if '__' in field:
            return get_lookup_value(self.model, value, field)
        field_obj = self.get_field(field)
        if isinstance(field_obj, models.ForeignKey):
            return get_lookup_value(self.model, value, field)
        return value
    
    def get_headers(self):
        output = [Header(self, 0, self.get_lookup_title(self.selected_group_by))]
        ind = 1
        for title in self.annotate_titles:
            output.append(Header(self, ind, title))
            ind += 1
        return output
    
    def header_count(self):
        return len(self.annotate) + 1#+1 group by
    
    def get_details_headers(self):
        return [self.get_lookup_title(i) for i in self.detail_list_display]
    
    def get_group_by_field(self):
        return self.params.get(GROUP_BY_VAR, self.group_by[0])
    
    def get_queryset(self):
        lookup_params = self.params.copy()
        qs = self.model.objects.all()
        for field in [GROUP_BY_VAR, SORT_VAR, SORTTYPE_VAR, DETAILS_SWITCH_VAR]:
            if field in lookup_params:
                del lookup_params[field]
        for key, value in lookup_params.items():
            if not isinstance(key, str):
                # 'key' will be used as a keyword argument later, so Python
                # requires it to be a string.
                del lookup_params[key]
                lookup_params[smart_str(key)] = value

            # if key ends with __in, split parameter into separate values
            if key.endswith('__in'):
                lookup_params[key] = value.split(',')
        try:
            qs = qs.filter(**lookup_params)
        except:
            raise IncorrectLookupParameters
        return qs
        

    def get_filters(self, model_admin):
        filter_specs = []
        if self.list_filter:
            #fields = []
            for field_name in self.list_filter:
                try:
                    field = self.get_field(field_name)
                except:
                    filter_specs.append(LookupFilterSpec(field_name, self.request, self.params, self.model, model_admin))
                    continue
                spec = FilterSpec.create(field, self.request, self.params, self.model, model_admin)
                if spec and spec.has_output():
                    filter_specs.append(spec)
        return filter_specs, bool(filter_specs)
    
    def get_query_string(self, new_params=None, remove=None):
        if new_params is None: new_params = {}
        if remove is None: remove = []
        p = self.params.copy()
        for r in remove:
            for k in p.keys():
                if k.startswith(r):
                    del p[k]
        for k, v in new_params.items():
            if v is None:
                if k in p:
                    del p[k]
            else:
                p[k] = v
        return '?%s' % urlencode(p)
    
    def group_by_links(self):
        result = []
        for f in self.group_by:
            url = './' + self.get_query_string({GROUP_BY_VAR:f})
            name = self.group_by_titles[f]
            selected = self.params.get(GROUP_BY_VAR, self.group_by[0]) == f
            result.append((url, name, selected))
        return result
    

    def get_details(self, row):
        val = row[self.selected_group_by]
        key = str(self.selected_group_by)
        queryset = self.get_queryset().filter(**{key: val})
        output = []
        for obj in queryset:
            item = []
            for attr in self.detail_list_display:
                if hasattr(obj, attr):
                    value = getattr(obj, attr)
                elif hasattr(self, attr):
                    value = getattr(self, attr)
                    if callable(value):
                        value = value(obj)
                else:
                    raise Exception("Couldnot resove '%s' into value" % attr)
                if attr in self.detail_link_fields:
                    value = mark_safe('<a href="%s">%s</a>' % 
                                      (self.details_url(obj), escape(value)))
                item.append(value)
            output.append(item)
        return output
    
    def details_url(self, obj):
        view_name = 'admin:%s_%s_change' % (obj._meta.app_label, obj._meta.module_name)
        return reverse(view_name, args=[obj.pk])
    
    def get_details_summary(self, row):
        return None
        
    def details_switch(self):
        "Link for turning on/off details view"
        if self.show_details:
            title = 'Hide'
            url = self.get_query_string({}, DETAILS_SWITCH_VAR)
        else:
            title = 'Show'
            url = self.get_query_string({DETAILS_SWITCH_VAR:'y'})
        return '<a href="%s">%s</a>' % (url, title)
        
    
    def get_field(self, name):
        return get_model_field(self.model, name)
    
    def get_lookup_title(self, lookup):
        try:
            return capfirst(self.get_field(lookup).verbose_name)
        except FieldDoesNotExist:
            if '__' not in lookup and not hasattr(self, lookup):
                raise
            parts = lookup.split('__')
            return ', '.join([capfirst(i.replace('_', ' ')) for i in parts])
    
    def split_annotate_titles(self, items):
        data, titles = [], []
        for item in items:
            if len(item) == 3:
                data.append(item[:2])
                titles.append(item[-1])
            else:
                data.append(item)
                field_name = self.get_lookup_title(item[0])
                text = '%s %s' % (field_name, item[1].__name__)
                titles.append(text)
        return data, titles
    
    def split_titles(self, items):
        data, titles = [], {}
        for item in items:
            if not isinstance(item, (list, tuple)):
                data.append(item)
                titles[item] = self.get_lookup_title(item)
            else:
                assert len(item) == 2
                data.append(item[0])
                titles[item[0]] = item[1]
        return data, titles
                
       
