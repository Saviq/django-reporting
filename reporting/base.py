from datetime import date

from django.contrib.admin import FieldListFilter
from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.admin.util import get_model_from_relation,\
    get_fields_from_path, NotRelationField
from django.utils.http import urlencode
from django.utils.encoding import smart_str
from django.db import models
from django.db.models.fields.related import RelatedField, ManyToOneRel
from django.db.models.fields import FieldDoesNotExist
from django.utils.text import capfirst
from django.utils.html import escape, format_html
from django.utils.translation import ugettext_lazy as _
from django.core.urlresolvers import reverse    
from django.core.exceptions import ImproperlyConfigured


class ModelAdminMock(object):
    def __init__(self, model):
        self.model = model
        
    def queryset(self, request):
        return self.model.objects.all()
    


GROUP_VAR = 'g'
ORDER_VAR = 'o'
ORDER_TYPE_VAR = 'ot'

IGNORED_PARAMS = (
    GROUP_VAR, ORDER_VAR, ORDER_TYPE_VAR)


class Cell(object):
    tag = 'td'
    contents = ""
    css_class = None
    
    def __init__(self, text, classes=()):
        self.contents = format_html(u'<div class="grp-text"><span>{}</span></div>', text)
        self.css_class = set(classes)

class SpanCell(Cell):
    span = True
        
class Header(Cell):
    tag = 'th'

class SpanHeader(Header):
    span = True

class SortHeader(Header):
    def __init__(self, text, field, report, classes=()):
        super(Header, self).__init__(text, classes)
        order = 'asc'

        self.css_class.update(('sortable',))

        context = {
                'text': text,
                'url_remove': report.get_query_string(remove=[ORDER_VAR, ORDER_TYPE_VAR]),
                'url_toggle': report.get_query_string({ORDER_VAR: field, ORDER_TYPE_VAR: order}),
        }

        if field == report.order_by:
            order = {'asc':'desc', 'desc': 'asc'}[report.order]
            self.css_class.update(('sorted', '%sending' % report.order))
            context.update({
                'order': report.order,
                'url_toggle': report.get_query_string({ORDER_VAR: field, ORDER_TYPE_VAR: order}),
            })
            self.contents = format_html('<div class="grp-sortoptions">'
                                        '<a class="grp-toggle grp-{order}ending" href={url_toggle} />'
                                        '<a class="grp-sortremove" href="{url_remove}" />'
                                        '</div>'
                                        '<div class="grp-text"><a href="{url_toggle}">{text}</a></div>', **context)
        else:
            self.contents = format_html('<div class="grp-text"><a href="{url_toggle}">{text}</a></div>', **context)



def current_year():
    return date.today().year

def current_month():
    return date.today().month

class Report(object):
    template_name = None
    filter = {}
    group_by = ()

    list_filter = None
    date_hierarchy = None

    order_by = None
    order = 'asc'
    
    defaults = {}
    
    def __init__(self, request=None):
        if not request:
            return
        
        self.request = request
        admin_mock = ModelAdminMock(self.model)

        self.params = dict(self.request.GET.items())

        self.selected_group_by = self.get_param(self.group_by, GROUP_VAR)

        self.opts = self.model._meta

        self.order_by = self.params.get(ORDER_VAR, None)
        self.order = self.params.get(ORDER_TYPE_VAR, 'asc')

        self.filter_specs, self.has_filters = self.get_filters(admin_mock)

        self.get_results()
        self.get_aggregations()

    @property
    def query_set(self):
        return self.queryset

    @property
    def queryset(self):
        return self.get_queryset(by_date=False)

    def get_aggregations(self):
        aggregates = [func(field) for field, func in self.aggregate]
        aggregate = self.get_queryset().aggregate(*aggregates)
        
        self.aggregate_results = aggregate
        return aggregate
    
    def get_headers(self):
        ind = 0
        output = []
        if self.selected_group_by:
            output.append(Header(self, ind, self.get_title(self.selected_group_by)))
            ind += 1
        for title in self.annotate_titles:
            output.append(Header(self, ind, title))
            ind += 1
        return output
    
    def group_count(self):
        return len(self.selected_group_by)

    def get_param(self, choices, param):
        if choices:
            f = self.params.get(param, None)
            if f is None:
                return choices[0]
            else:
                f = tuple(f.split(','))
                for item in choices:
                    if isinstance(item, basestring) and f == (item,) \
                    or isinstance(item[0], basestring) and f == tuple(item) \
                    or f == tuple(item[0]):
                        return item
        return None

    def get_queryset(self, by_date=True):
        qs = self.model.objects.all()

        lookups = {key: value for key, value in self.params.iteritems()
                   if not (key in IGNORED_PARAMS
                           or (not by_date and key.startswith(self.date_hierarchy)))}

        lookups.update(self.filter)

        for filter_spec in self.filter_specs:
            new_qs = filter_spec.queryset(self.request, qs)
            if new_qs is not None:
                qs = new_qs

        return qs.filter(**lookups)

    def get_filters(self, model_admin):
        filter_specs = []
        if self.list_filter:
            for filter_name in self.list_filter:
                field = self.get_field(filter_name)
                spec = FieldListFilter.create(field, self.request, self.params.copy(), self.model, model_admin, field_path=filter_name)
                if spec and spec.has_output():
                    filter_specs.append(spec)
        return filter_specs, bool(filter_specs)

    def get_query_string(self, new_params={}, remove=[]):
        try:
            p = self.params.copy()
        except AttributeError:
            p = {}
        for r in remove:
            for k in p.keys():
                if k.startswith(r):
                    del p[k]
        for k, v in new_params.items():
            if v is None:
                if k in p:
                    del p[k]
            elif callable(v):
                p[k] = v()
            else:
                p[k] = v
        return '?%s' % urlencode(p)

    def get_default_query_string(self):
        return self.get_query_string(self.defaults)

    def group_by_choices(self):
        result = []
        for f in self.group_by:
            result.append(
                {'selected': self.selected_group_by == f,
                 'query_string': self.get_query_string({GROUP_VAR: ",".join(self.get_lookups(f))}),
                 'display': self.get_title(f)})
        return result
    
    def get_field(self, name):
        return get_fields_from_path(self.model, name)[-1]
    
    def get_title_for_lookup(self, lookup):
        f = self.get_field(lookup)
        if isinstance(f, (models.ManyToManyField,
                          models.ManyToOneRel)):
            # no direct field on this model, get name from other model
            other_model = get_model_from_relation(f)
            title = other_model._meta.verbose_name
        else:
            title = f.verbose_name # use field name
        return capfirst(unicode(title))
    
    def get_lookups(self, item):
        if isinstance(item, basestring):
            return (item,)
        elif isinstance(item[0], basestring):
            return item
        elif hasattr(item[0], '__iter__'):
            return item[0]
        else:
            raise ImproperlyConfigured("Lookups need to be a single field, a tuple of fields, \
                                        or a two-tuple of ((field,), title)")
    
    def get_title(self, item):
        if isinstance(item, basestring):
            # single field
            return self.get_title_for_lookup(item)
        elif isinstance(item[0], basestring):
            # multiple fields
            return ", ".join([self.get_title_for_lookup(lookup) for lookup in item])
        elif hasattr(item[0], '__iter__'):
            # custom title
            return item[-1]
        else:
            raise ImproperlyConfigured("Lookups need to be a single field, a tuple of fields, \
                                        or a two-tuple of ((field,), title)")

    def dereference_values(self, field_names, results):
        for field_name in field_names:
            try:
                field = self.get_field(field_name)
            except NotRelationField:
                continue
            if isinstance(field, RelatedField) or isinstance(field, ManyToOneRel):
                for result in results:
                    result[field_name] = get_model_from_relation(field).objects.get(pk=result[field_name])
        return results
       

class BandReport(Report):
    annotate = []
    aggregate = ()
    
    template_name = 'reporting/band.html'
    
    def get_annotations(self):
        annotates = []
        for item in self.annotate:
            field, func = self.get_lookups(item)
            annotates.append(func(field))
        self.annotates = annotates
        return annotates
    
    def get_results(self):
        self.get_annotations()
        
        values = self.get_lookups(self.selected_group_by)
        results = self.get_queryset().values(*values).annotate(*self.annotates)
        self.dereference_values(self.get_lookups(self.selected_group_by), results)
        self.results = results
        
        return [{'values': row} for row in results]
        
    def result_count(self):
        return len(self.results)
    
    def header_count(self):
        return len(self.get_lookups(self.selected_group_by)) \
               + len(self.annotates)

class DetailBandReport(BandReport):
    template_name = 'reporting/band_details.html'
    detail_list_display = None

    def get_results(self):
        results = super(DetailBandReport, self).get_results()
        
        return [{'values': row, 'details': self.get_details(row)} for row in results]
        
    def header_count(self):
        return super(DetailBandReport, self).header_count() + len(self.detail_list_display)
    
    def get_details_headers(self):
        return [self.get_title(i) for i in self.detail_list_display]

    def get_details(self, row):
        queryset = self.get_queryset().filter(**{key: row["values"][key] for key in self.get_lookups(self.selected_group_by)})
        output = []
        for obj in queryset:
            item = []
            for attr in self.detail_list_display:
                try:
                    if '__' in attr:
                        value = obj
                        for part in attr.split('__'):
                            value = getattr(value, part)
                    elif hasattr(obj, attr):
                        value = getattr(obj, attr)
                    elif hasattr(self, attr):
                        value = getattr(self, attr)
                        if callable(value):
                            value = value(obj)
                    else:
                        raise AttributeError()
                except AttributeError:
                    raise Exception("Could not resolve '%s' into value" % attr)
                if attr in self.detail_link_fields:
                    value = format_html('<a href="{}">{}</a>', self.details_url(obj), escape(value))
                item.append(value)
            output.append(item)
        return output


class CrossReport(Report):
    row = None
    column = None
    
    row_headers = None
    column_headers = None
    
    row_links = ()
    column_links = ()
    
    row_annotate = ()
    column_annotate = ()
    cross_annotate = ()
    
    row_aggregate = ()
    column_aggregate = ()
    cross_aggregate = ()
    
    cell_values = ()
    cell_annotate = ()


    def get_annotations(self):
        row_annotate = self.cross_aggregate + self.row_aggregate + \
                       self.cross_annotate + self.row_annotate
                          

        column_annotate = self.cross_aggregate + self.column_aggregate + \
                          self.cross_annotate + self.column_annotate

        row_annotates = tuple(func(field) for field, func in row_annotate)
        column_annotates = tuple(func(field) for field, func in column_annotate)
        cell_annotates = tuple(func(field) for field, func in self.cell_annotate)
        
        self.row_annotates = row_annotates
        self.column_annotates = column_annotates
        self.cell_annotates = cell_annotates
        
        return row_annotates, column_annotates, cell_annotates 


    def get_results(self):
        self.get_annotations()

        self.row_aliases = tuple(annotation.default_alias for annotation in self.row_annotates)
        self.column_aliases = tuple(annotation.default_alias for annotation in self.column_annotates)
        self.cell_aliases = tuple(annotation.default_alias for annotation in self.cell_annotates)
        
        row_values = (self.row,) + self.row_headers + self.row_aliases
        column_values = (self.column,) + self.column_headers + self.column_aliases
        cell_values = (self.row, self.column) + self.cell_values + self.cell_aliases
        
        row_results = self.get_queryset().values(self.row) \
                          .annotate(*self.row_annotates)\
                          .values(*row_values)
        # order row results
        if self.order_by in self.row_headers + self.row_aliases:
            row_results = self.order == 'desc' and row_results.order_by('-' + self.order_by) \
                          or row_results.order_by(self.order_by)

        column_results = self.get_queryset().values(self.column) \
                             .annotate(*self.column_annotates)\
                             .values(*column_values)
        # order column results
        if self.order_by in self.column_headers + self.column_aliases:
            column_results = self.order == 'desc' and column_results.order_by('-' + self.order_by) \
                          or column_results.order_by(self.order_by)
                                  
        cell_results = self.get_queryset().annotate(*self.cell_annotates).values(*cell_values)

        self.dereference_values(self.row_headers, row_results)
        self.dereference_values(self.column_headers, column_results)
        self.dereference_values(self.cell_values, cell_results)

        self.row_results = row_results
        self.column_results = column_results
        self.cell_results = cell_results

        return row_results, column_results, cell_results

    def result_count(self):
        return len(self.row_results)


    def get_aggregations(self):        
        row_aggregates = (func(field) for field, func in self.row_aggregate)
        column_aggregates = (func(field) for field, func in self.column_aggregate)
        cross_aggregates = (func(field) for field, func in self.cross_aggregate)
        
        row_aggregate = self.get_queryset().aggregate(*row_aggregates)
        column_aggregate = self.get_queryset().aggregate(*column_aggregates)
        cross_aggregate = self.get_queryset().aggregate(*cross_aggregates)
        
        self.row_aggregate_results = row_aggregate
        self.column_aggregate_results = column_aggregate
        self.cross_aggregate_results = cross_aggregate
        
        return row_aggregate, column_aggregate, cross_aggregate


class CrossGridReport(CrossReport):
    template_name = 'reporting/grid.html'
    
    def column_post_header_count(self):
        return len(self.cross_aggregate) + \
            len(self.row_aggregate) + \
            int(bool(self.column_aggregate)) + \
            len(self.cross_annotate) + \
            len(self.row_annotate)

    def row_post_header_count(self):
        return len(self.cross_aggregate) + \
            len(self.column_aggregate) + \
            int(bool(self.row_aggregate)) + \
            len(self.cross_annotate) + \
            len(self.column_annotate)

    def cell_values_count(self):
        return len(self.cell_values) + \
            len(self.cell_annotate)

    def values_row_count(self):
        return (self.cell_values_count() * len(self.row_results))
    
    def header_column_count(self):
        return len(self.row_headers) + \
            len(self.column_results)

    def full_column_count(self):
        return len(self.row_headers) + \
        len(self.column_results) + \
        len(self.cross_aggregate) + \
        len(self.row_aggregate) + \
        len(self.cross_annotate) + \
        len(self.row_annotate)

    def get_headers(self):
        headers = []

        # top headers
        row_header = [SortHeader(self.get_title(field), field, self) for field in self.row_headers]

        # top object header
        row_header.append(Header(self.get_title(self.column), ('grp-text',)))

        # cross and column aggregation headers
        for field, func in self.cross_aggregate + self.row_aggregate + \
                           self.cross_annotate + self.row_annotate:
            row_header.append(Header(self.get_title(field)))
        # totals for column aggregations
        if self.column_aggregate:
            row_header.append(Header(_("Totals")))

        headers.append(row_header)

        # top header values
        for index, field in enumerate(self.column_headers):
            column_header = [SortHeader(self.get_title(field), field, self)]
            for column in self.column_results:
                column_header.append(Header(column[field]))
            headers.append(column_header)
        
        return headers
    
    def get_rows(self):
        results = []
        cells = {}
        
        for cell in self.cell_results:
            try:
                cells[cell[self.row]][cell[self.column]] = cell
            except KeyError:
                cells[cell[self.row]] = {cell[self.column]: cell}
                
        for row in self.row_results:
            for index, field in enumerate(self.cell_values + self.cell_aliases):
                result = []
                # row headers
                if index == 0:
                    result = [SpanHeader(row[header]) for header in self.row_headers]
                # row values
                for column in self.column_results:                    
                    try:
                        result.append(Cell(cells[row[self.row]][column[self.column]][field]))
                    except KeyError:
                        result.append(None)
                # row annotations
                if index == 0:
                    result.extend([SpanCell(row[header], ('annotate',)) for header in self.row_aliases])

                results.append(result)

        for index, (field, func) in enumerate(self.cross_aggregate + self.column_aggregate):
            result = [Header(self.get_title(field))]
            
            for column in self.column_results:
                # cross/column annotations from aggregations
                result.append(Cell(column[func(field).default_alias], ('aggregate',)))

            if (field, func) in self.cross_aggregate:
                # cross aggregations
                result.extend(Cell('') for n in range(index))
                result.append(Cell(self.cross_aggregate_results[func(field).default_alias], ('aggregate',)))
                result.extend(Cell('') for n in range(len(self.row_annotates) - index - \
                                                       int(not bool(self.column_aggregate))))
            else:
                # column aggregations
                result.extend(Cell('') for n in range(len(self.row_annotates)))
                result.append(Cell(self.column_aggregate_results[func(field).default_alias], ('aggregate',)))
            results.append(result)
    
        for field, func in self.cross_annotate + self.column_annotate:
            result = [Header(self.get_title(field))]
            
            for column in self.column_results:
                # cross/column annotations
                result.append(Cell(column[func(field).default_alias], ('annotate',)))

            result.extend(Cell('') for n in range(len(self.row_annotates) + \
                                                  int(bool(self.column_aggregate))))
            
            results.append(result)
    
        if self.row_aggregate:
            result = [Header(_("Totals"))]

            result.extend(Cell('') for n in range(len(self.cross_aggregate)))

            for field, func in self.row_aggregate:
                # row aggregations
                result.append(Cell(self.row_aggregate_results[func(field).default_alias], ('aggregate',)))            
            
            result.extend(Cell('') for n in range(len(self.cross_annotate) + \
                                                  len(self.row_annotate) + \
                                                  int(bool(self.column_aggregate))))
            
            results.append(result)
        
        # left object header
        results[0].insert(0, Header(self.get_title(self.row)))
        return results