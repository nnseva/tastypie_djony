from tastypie.resources import Resource, ResourceOptions, DeclarativeMetaclass, Bundle
from tastypie.exceptions import NotFound
from tastypie.fields import *
from tastypie_djony.fields import *
from tastypie.constants import ALL,ALL_WITH_RELATIONS

from pony import orm
from pony.converting import str2date, str2datetime, str2time

from django.conf.urls import patterns, include, url

from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned

from tastypie.exceptions import NotFound, BadRequest, InvalidFilterError, HydrationError, InvalidSortError, ImmediateHttpResponse, Unauthorized

from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ugettext_noop

try:
    from django.db.models.constants import LOOKUP_SEP
except ImportError:
    from django.db.models.sql.constants import LOOKUP_SEP

import decimal
import datetime

QUERY_TERMS = {
    'gt':lambda attribute,value: '%(attribute)s > %(value)s' % {'attribute':attribute,'value':value},
    'gte':lambda attribute,value: '%(attribute)s >= %(value)s' % {'attribute':attribute,'value':value},
    'lt':lambda attribute,value: '%(attribute)s < %(value)s' % {'attribute':attribute,'value':value},
    'lte':lambda attribute,value: '%(attribute)s <= %(value)s' % {'attribute':attribute,'value':value},
    'contains':lambda attribute,value: '%(value)s in %(attribute)s' % {'attribute':attribute,'value':value}, # TODO: make contains case-dependent (how?)
    'icontains':lambda attribute,value: '%(value)s in %(attribute)s' % {'attribute':attribute,'value':value}, # TODO: make icontains like this
    'startswith':lambda attribute,value: '%(attribute)s.startswith(%(value)s)' % {'attribute':attribute,'value':value},
    'istartswith':lambda attribute,value: '%(attribute)s.startswith(%(value)s)' % {'attribute':attribute,'value':value},
    'endswith':lambda attribute,value: '%(attribute)s.endswith(%(value)s)' % {'attribute':attribute,'value':value},
    'iendswith':lambda attribute,value: '%(attribute)s.endswith(%(value)s)' % {'attribute':attribute,'value':value},
    'exact':lambda attribute,value: '%(attribute)s == %(value)s' % {'attribute':attribute,'value':value},
    'iexact':lambda attribute,value: '%(attribute)s == %(value)s' % {'attribute':attribute,'value':value},
    'day':lambda attribute,value: '%(attribute)s.day == %(value)s' % {'attribute':attribute,'value':value},
    'month':lambda attribute,value: '%(attribute)s.month == %(value)s' % {'attribute':attribute,'value':value},
    'year':lambda attribute,value: '%(attribute)s.year == %(value)s' % {'attribute':attribute,'value':value},
    'isnull':lambda attribute,value: ('%(attribute)s is None' if value == 'True' else 'not (%(attribute)s is None)') % {'attribute':attribute,'value':value},
    'in':lambda attribute,value:'%(attribute)s in (%(value)s)' % { 'attribute':attribute,'value':','.join(v for v in value)},
    'range':lambda attribute,value:'%(attribute)s >= %(v0)s and (attribute)s <= %(v1)s' % { 'attribute':attribute,'v0':value[0],'v1':value[1]},
    # TODO: implement
    # 'week_day', 'regex','isearch', 'search', 'iregex', 'regex',
}

NONE_REPR = set(['None','none','Null','null'])
TRUE_REPR = set(['true','True','yes','Yes'])
FALSE_REPR = set(['false','False','no','No'])

QUERY_TERM_CONVERT_VALUE = {
    bool:lambda x: None if x in NONE_REPR else True if x in TRUE_REPR else False if x in FALSE_REPR else x,
    int:lambda x:  None if x in NONE_REPR else int(x),
    long:lambda x:  None if x in NONE_REPR else long(x),
    datetime.date:lambda x: None if x in NONE_REPR else str2date(x),
    datetime.datetime:lambda x: None if x in NONE_REPR else str2datetime(x),
    datetime.time:lambda x: None if x in NONE_REPR else str2time(x),
    datetime.timedelta:lambda x: None if x in NONE_REPR else datetime.timedelta(0,x),
    str:lambda x:  None if x in NONE_REPR else x.encode('utf-8'),
    unicode:lambda x:  None if x in NONE_REPR else x,
    decimal.Decimal: lambda x:  None if x in NONE_REPR else decimal.Decimal(x),
    float: lambda x:  None if x in NONE_REPR else float(x),
}

class DjonyDeclarativeMetaclass(DeclarativeMetaclass):
    def __new__(cls, name, bases, attrs):
        new_class = super(DjonyDeclarativeMetaclass, cls).__new__(cls, name, bases, attrs)
        include_fields = getattr(new_class._meta, 'fields', [])
        excludes = getattr(new_class._meta, 'excludes', [])
        object_model = getattr(new_class._meta, 'object_model', None)
        if Resource in bases:
            return new_class
            
        object_model = getattr(new_class._meta, 'object_model', None)
        if not object_model:
            raise SyntaxError("The object_model member should be present in the Meta for DjonyResource class")

        setattr(new_class._meta, 'object_class', object_model.p)

        field_names = new_class.base_fields.keys()

        for field_name in field_names:
            if field_name == 'resource_uri':
                continue
            if field_name in new_class.declared_fields:
                continue
            if len(include_fields) and not field_name in include_fields:
                del(new_class.base_fields[field_name])
            if len(excludes) and field_name in excludes:
                del(new_class.base_fields[field_name])

        # Add in the new fields.
        new_class.base_fields.update(new_class.get_fields(include_fields, excludes))

        if getattr(new_class._meta, 'include_absolute_url', True):
            if not 'absolute_url' in new_class.base_fields:
                new_class.base_fields['absolute_url'] = CharField(attribute='get_absolute_url', readonly=True)
        elif 'absolute_url' in new_class.base_fields and not 'absolute_url' in attrs:
            del(new_class.base_fields['absolute_url'])

        return new_class

class DjonyResource(Resource):
    __metaclass__ = DjonyDeclarativeMetaclass

    @classmethod
    def get_fields(cls, fields=None, excludes=None):
        """
        Given any explicit fields to include and fields to exclude, add
        additional fields based on the associated model.
        """
        final_fields = {}
        fields = fields or []
        excludes = excludes or []

        if not cls._meta.object_class:
            return final_fields

        for f in cls._meta.object_class._attrs_:
            # If the field name is already present, skip
            if f.name in cls.base_fields:
                continue

            # If field is not present in explicit field listing, skip
            if fields and f.name not in fields:
                continue

            # If field is in exclude list, skip
            if excludes and f.name in excludes:
                continue

            if cls.should_skip_field(f):
                continue

            api_field_class = cls.api_field_from_pony_field(f)

            kwargs = {
                'attribute': f.name,
            }

            kwargs['null'] = not f.is_required

            kwargs['unique'] = f.is_unique

            kwargs['default'] = f.default

            # always readonly primary key because of update restrictions
            if f.is_pk:# and not issubclass(f.py_type,orm.core.Entity):
                #print "DEBUG!!!",cls.__name__,f.name,kwargs,'...'
                kwargs['readonly'] = True

            final_fields[f.name] = api_field_class(**kwargs)

            #if f.is_pk and not issubclass(f.py_type,orm.core.Entity):
            #    print "...",cls.__name__,final_fields[f.name].readonly

            final_fields[f.name].instance_name = f.name
            try:
                mf = cls._meta.object_model._meta.get_field_by_name(f.name)[0]
                if mf.help_text:
                    final_fields[f.name].help_text = mf.help_text
            except:
                pass

        return final_fields

    @classmethod
    def api_field_from_pony_field(cls, f, default=CharField):
        """
        Returns the field type that would likely be associated with each
        Pony type.
        """
        result = default

        if issubclass(f.py_type,datetime.datetime):
            result = GMTDateTimeNaiveField
        elif issubclass(f.py_type,datetime.date):
            result = DateField
        elif issubclass(f.py_type,bool):
            result = BooleanField
        elif issubclass(f.py_type,float):
            result = FloatField
        elif issubclass(f.py_type,decimal.Decimal):
            result = DecimalField
        elif issubclass(f.py_type,(int,long)):
            result = IntegerField
        elif issubclass(f.py_type,datetime.time):
            result = TimeField

        return result

    @classmethod
    def should_skip_field(cls, field):
        """
        Given a Pony model field, return if it should be included in the
        contributed ApiFields.
        """
        # Ignore certain fields (related fields).
        if issubclass(field.py_type,orm.core.Entity):
            return True

        return False

    def get_bundle_detail_data(self, bundle):
        """
        Convenience method to return the ``detail_uri_name`` attribute of
        ``bundle.obj``.
        """
        return ','.join([("%s" % v) for v in bundle.obj._get_raw_pkval_()])

    def detail_uri_kwargs(self, bundle_or_obj):
        """
        Given a ``Bundle`` or an object (typically a ``pony.core.orm.Entity`` instance),
        it returns the extra kwargs needed to generate a detail URI.

        By default, it uses the model's primary key in order to create the URI.
        """
        kwargs = {}

        obj = bundle_or_obj
        if isinstance(bundle_or_obj, Bundle):
            obj = bundle_or_obj.obj

        kwargs[self._meta.detail_uri_name] = ','.join([("%s" % v) for v in obj._get_raw_pkval_()])
        return kwargs

    @orm.db_session
    def dispatch_list(self,*args,**kw):
        return Resource.dispatch_list(self,*args,**kw)

    @orm.db_session
    def dispatch_detail(self,*args,**kw):
        return Resource.dispatch_detail(self,*args,**kw)

    @orm.db_session
    def get_schema(self,*args,**kw):
        return Resource.get_schema(self,*args,**kw)

    @orm.db_session
    def get_multiple(self,*args,**kw):
        return Resource.get_multiple(self,*args,**kw)

    def apply_sorting(self, obj_list, options=None):
        if options is None:
            options = {}

        if not 'order_by' in options:
            return obj_list

        order_by_args = []

        parameter_name = 'order_by'

        if hasattr(options, 'getlist'):
            order_bits = options.getlist(parameter_name)
        else:
            order_bits = options.get(parameter_name)

            if not isinstance(order_bits, (list, tuple)):
                order_bits = [order_bits]

        for order_by in order_bits:
            order_by_bits = order_by.split(LOOKUP_SEP)

            field_name = order_by_bits[0]
            order = '%s'
            order_by_name = order_by

            if order_by_bits[0].startswith('-'):
                field_name = order_by_bits[0][1:]
                order = 'orm.desc(%s)'
                order_by_name = order_by_name[1:]

            if not field_name in self.fields:
                # It's not a field we know about. Move along citizen.
                raise InvalidSortError("No matching '%s' field for ordering on." % field_name)

            if not order_by_name in self._meta.ordering:
                raise InvalidSortError("The resourse doesn't allow ordering by '%s'." % order_by_name)

            if self.fields[field_name].attribute is None:
                raise InvalidSortError("The '%s' field has no 'attribute' for ordering with." % field_name)

            order_by_args.append(order % ('.'.join(['o',self.fields[field_name].attribute] + order_by_bits[1:])))

        return obj_list.order_by(', '.join(order_by_args))

    def get_object_list(self, request):
        return orm.select(o for o in self._meta.object_class)

    def obj_get_list(self, bundle, **kwargs):
        """
        A ORM-specific implementation of ``obj_get_list``.

        Takes an optional ``request`` object, whose ``GET`` dictionary can be
        used to narrow the query.
        
        Emulates native tastypie django-specific filters.
        """
        filters = {}

        if hasattr(bundle.request, 'GET'):
            # Grab a mutable copy.
            filters = bundle.request.GET.copy()

        # Update with the provided kwargs.
        filters.update(kwargs)
        applicable_filters = self.build_filters(filters=filters)

        objects = self.apply_filters(bundle.request, applicable_filters)
        return self.authorized_read_list(objects, bundle)

        #try:
        #    objects = self.apply_filters(bundle.request, applicable_filters)
        #    return self.authorized_read_list(objects, bundle)
        #except ValueError:
        #    raise BadRequest("Invalid resource lookup data provided (mismatched type).")

    def apply_filters(self, request, filters):
        """
        An ORM-specific implementation of ``apply_filters``.
        
        Emulates native tastypie django-specific filters.
        """

        qs_filters = []

        qs_set_filters = {}

        for filter_expr, value in filters.items():
            filter_bits = filter_expr.split(LOOKUP_SEP)
            field_name = filter_bits.pop(0)
            filter_type = 'exact'

            if not field_name in self.fields:
                # It's not a field we know about. Move along citizen.
                continue

            # resolve filter type
            if len(filter_bits) and filter_bits[-1] in QUERY_TERMS:
                filter_type = filter_bits.pop()

            lookup_bits = self.check_filtering(field_name, filter_type, filter_bits)

            # check, whether the specified atribute is a single value or set;
            # also get final attribute type
            # (Pony ORM-specific)
            is_set = False
            t = self._meta.object_class
            for bit in lookup_bits:
                a = getattr(t,bit,None)
                if not a:
                    raise InvalidFilterError("The attribute %s not found for %s" % (bit,t))
                t = a.py_type
                if issubclass(t,orm.core.Entity) and isinstance(a,orm.Set):
                    is_set = True

            # split single and set-oriented filters to emulate django filters
            if not is_set:
                flt = self.combine_lookup_and_value(t,filter_type,lookup_bits,value,'o.')
                if flt:
                    qs_filters.append(flt)
            else:
                set_object = tuple(lookup_bits[:-1])
                flt = self.combine_lookup_and_value(t,filter_type,lookup_bits[-1:],value,'p.')
                if flt:
                    if not set_object in qs_set_filters:
                        qs_set_filters[set_object] = []
                    qs_set_filters[set_object].append(flt)
        q = self.get_object_list(request)
        for f in qs_filters:
            q.filter(f)
        for set_object in qs_set_filters:
            q.filter("orm.exists(p for p in %s if %s)" % (
                'o.'+'.'.join(set_object),
                ' and '.join([('(%s)' % flt) for flt in qs_set_filters[set_object]])
            ))
        return q

    def combine_lookup_and_value(self,final_type,filter_type,lookup_bits,value,prefix):
        attribute = prefix + '.'.join(lookup_bits)
        value_convertor = QUERY_TERM_CONVERT_VALUE[final_type]
        if filter_type == 'isnull':
            value_convertor = QUERY_TERM_CONVERT_VALUE[bool]
        elif filter_type in ('day','month','year'):
            value_convertor = QUERY_TERM_CONVERT_VALUE[int]
        try:
            if filter_type in ('in','range'):
                value = [repr(value_convertor(v)) for v in value.split(',')]
            else:
                value = repr(value_convertor(value))
        except:
            raise InvalidFilterError("Value %s is not allowed for '%s' filter with attribute '%s'" % (repr(value),filter_type,'.'.join(lookup_bits)))
        expr = QUERY_TERMS[filter_type]
        return expr(attribute,value)

    def check_filtering(self, field_name, filter_type='exact', filter_bits=None):
        """
        Given a field name, a optional filter type and an optional list of
        additional relations, determine if a field can be filtered on.

        If a filter does not meet the needed conditions, it should raise an
        ``InvalidFilterError``.

        If the filter meets the conditions, a list of attribute names (not
        field names) will be returned.
        
        (copy from ModelResource)
        """
        if filter_bits is None:
            filter_bits = []

        if not field_name in self._meta.filtering:
            raise InvalidFilterError("The '%s' field does not allow filtering." % field_name)

        # Check to see if it's an allowed lookup type.
        if not self._meta.filtering[field_name] in (ALL, ALL_WITH_RELATIONS):
            # Must be an explicit whitelist.
            if not filter_type in self._meta.filtering[field_name]:
                raise InvalidFilterError("'%s' is not an allowed filter on the '%s' field." % (filter_type, field_name))

        if self.fields[field_name].attribute is None:
            raise InvalidFilterError("The '%s' field has no 'attribute' for searching with." % field_name)

        # Check to see if it's a relational lookup and if that's allowed.
        if len(filter_bits):
            if not getattr(self.fields[field_name], 'is_related', False):
                raise InvalidFilterError("The '%s' field does not support relations." % field_name)

            if not self._meta.filtering[field_name] == ALL_WITH_RELATIONS:
                raise InvalidFilterError("Lookups are not allowed more than one level deep on the '%s' field." % field_name)

            # Recursively descend through the remaining lookups in the filter,
            # if any. We should ensure that all along the way, we're allowed
            # to filter on that field by the related resource.
            related_resource = self.fields[field_name].get_related_resource(None)
            return [self.fields[field_name].attribute] + related_resource.check_filtering(filter_bits[0], filter_type, filter_bits[1:])

        return [self.fields[field_name].attribute]

    def obj_get(self, bundle, **kwargs):
        try:
            obj = None
            if self._meta.detail_uri_name in kwargs:
                pk = tuple(kwargs[self._meta.detail_uri_name].split(','))
                obj = self._meta.object_class._get_by_raw_pkval_(pk)
                obj._load_()
            else:
                obj = self._meta.object_class.get(**kwargs)
            if not obj:
                raise ObjectDoesNotExist("Couldn't find an instance of '%s'" % self._meta.object_class.__name__)
            bundle.obj = obj
            self.authorized_read_detail([obj,], bundle)
            return bundle.obj
        except orm.MultipleObjectsFoundError:
            raise MultipleObjectsReturned("More than one '%s' matched" % self._meta.object_class.__name__)
        except orm.core.UnrepeatableReadError:
            raise NotFound("Invalid resource lookup data provided (wrong id).")
        except ValueError:
            raise NotFound("Invalid resource lookup data provided (mismatched type).")

    # overriden from Resource due to incompatibility
    def build_bundle(self, obj=None, data=None, request=None, objects_saved=None):
        """
        Given either an object, a data dictionary or both, builds a ``Bundle``
        for use throughout the ``dehydrate/hydrate`` cycle.
        """

        return Bundle(
            obj=obj,
            data=data,
            request=request,
            objects_saved=objects_saved
        )

    # overriden from Resource to extend schema by some additional info
    def build_schema(self):
        schema = Resource.build_schema(self)
        for field_name, field_object in self.fields.items():
            help_text = field_object.help_text
            if field_object.attribute:
                mf = self._meta.object_model._meta.get_field_by_name(field_object.attribute)[0]
                # try to fix help_text from the model field
                if not help_text or help_text == type(field_object).help_text:
                    ht = mf.help_text
                    if ht:
                        help_text = ht
                # try to fix help_text from other side verbose name for relationships
                if not help_text or help_text == type(field_object).help_text:
                    if isinstance(field_object,SetField):
                        help_text = mf.rel.to._meta.verbose_name_plural
                    elif isinstance(field_object,ToOneField):
                        help_text = mf.rel.to._meta.verbose_name
                schema['fields'][field_name]['verbose_name'] = mf.verbose_name
            if isinstance(field_object,RelatedField):
                # add embedded field descriptors for full-filled relation
                if field_object.full:
                    fields = field_object.to_class().build_schema()['fields']
                    for fn,fo in field_object.to_class().fields.items():
                        if getattr(fo,'hidden',False):
                            del fields[fn]
                    schema['fields'][field_name]['fields'] = fields
            schema['fields'][field_name]['help_text'] = help_text

            if hasattr(field_object,'full'):
                schema['fields'][field_name]['full'] = field_object.full
                if not field_object.full:
                    schema['fields'][field_name]['schema_uri'] = field_object.to_class()._build_reverse_url(
                        "api_get_schema",
                        kwargs=field_object.to_class().resource_uri_kwargs()
                    )
        if 'resource_uri' in schema['fields']:
            schema['fields']['resource_uri']['help_text'] = _("URI to access the object using API")
            schema['fields']['resource_uri']['verbose_name'] = _("Resource URI")
        return schema

    ########## UPDATE ##########
    def obj_update(self, bundle, skip_errors=False, **kwargs):
        """
        A ORM-specific implementation of ``obj_update``.
        """
        if not bundle.obj or not self.get_bundle_detail_data(bundle):
            try:
                lookup_kwargs = self.lookup_kwargs_with_identifiers(bundle, kwargs)
            except:
                # if there is trouble hydrating the data, fall back to just
                # using kwargs by itself (usually it only contains a "pk" key
                # and this will work fine.
                lookup_kwargs = kwargs

            try:
                bundle.obj = self.obj_get(bundle=bundle, **lookup_kwargs)
            except ObjectDoesNotExist:
                raise NotFound("A model instance matching the provided arguments could not be found.")

        bundle = self.full_hydrate(bundle)
        return self.save(bundle, skip_errors=skip_errors)

    def save(self, bundle, skip_errors=False):
        self.is_valid(bundle)

        if bundle.errors and not skip_errors:
            raise ImmediateHttpResponse(response=self.error_response(bundle.request, bundle.errors))

        # Check if they're authorized.
        if bundle.obj._get_raw_pkval_()[0]:
            self.authorized_update_detail(self.get_object_list(bundle.request), bundle)
        else:
            self.authorized_create_detail(self.get_object_list(bundle.request), bundle)

        # Save FKs just in case.
        self.save_related(bundle)

        # Save the main object.
        #bundle.obj.save() - not necessary for Pony
        bundle.objects_saved.add(self.create_identifier(bundle.obj))

        # Now pick up the M2M bits.
        m2m_bundle = self.hydrate_m2m(bundle)
        self.save_m2m(m2m_bundle)

        # commit changes
        return bundle

    def save_related(self, bundle):
        for field_name, field_object in self.fields.items():
            if not getattr(field_object, 'is_related', False):
                continue

            if getattr(field_object, 'is_m2m', False):
                continue

            if not field_object.attribute:
                continue

            if field_object.readonly:
                continue

            if field_object.blank and not bundle.data.has_key(field_name):
                continue

            # Get the object.
            try:
                related_obj = getattr(bundle.obj, field_object.attribute)
            except ObjectDoesNotExist:
                related_obj = bundle.related_objects_to_save.get(field_object.attribute, None)

            # Because sometimes it's ``None`` & that's OK.
            if related_obj:
                if field_object.related_name:
                    if not self.get_bundle_detail_data(bundle):
                        bundle.obj.save()

                    setattr(related_obj, field_object.related_name, bundle.obj)

                related_resource = field_object.get_related_resource(related_obj)

                # Before we build the bundle & try saving it, let's make sure we
                # haven't already saved it.
                obj_id = related_resource.create_identifier(related_obj)

                if obj_id in bundle.objects_saved:
                    # It's already been saved. We're done here.
                    continue

                if bundle.data.get(field_name) and hasattr(bundle.data[field_name], 'keys'):
                    # Only build & save if there's data, not just a URI.
                    related_bundle = related_resource.build_bundle(
                        obj=related_obj,
                        data=bundle.data.get(field_name),
                        request=bundle.request,
                        objects_saved=bundle.objects_saved
                    )
                    related_resource.save(related_bundle)

                setattr(bundle.obj, field_object.attribute, related_obj)

    def save_m2m(self, bundle):
        for field_name, field_object in self.fields.items():
            if not getattr(field_object, 'is_m2m', False):
                continue

            if not field_object.attribute:
                continue

            if field_object.readonly:
                continue

            # Get the manager.
            related_mngr = None

            if isinstance(field_object.attribute, basestring):
                related_mngr = getattr(bundle.obj, field_object.attribute)
            elif callable(field_object.attribute):
                related_mngr = field_object.attribute(bundle)

            if related_mngr is None:
                continue

            #if hasattr(related_mngr, 'clear'):
            #    # FIXME: Dupe the original bundle, copy in the new object &
            #    #        check the perms on that (using the related resource)?

            #    # Clear it out, just to be safe.
            #    related_mngr.clear()

            related_objs = []

            if bundle.data.get(field_name) is None:
                continue # skip empty

            for related_bundle in bundle.data[field_name]:
                related_resource = field_object.get_related_resource(bundle.obj)

                # Before we build the bundle & try saving it, let's make sure we
                # haven't already saved it.
                obj_id = related_resource.create_identifier(related_bundle.obj)

                if obj_id in bundle.objects_saved:
                    # It's already been saved. We're done here.
                    continue

                # Only build & save if there's data, not just a URI.
                updated_related_bundle = related_resource.build_bundle(
                    obj=related_bundle.obj,
                    data=related_bundle.data,
                    request=bundle.request,
                    objects_saved=bundle.objects_saved
                )
                
                #Only save related models if they're newly added.
                if not updated_related_bundle.obj._get_raw_pkval_()[0]:
                    related_resource.save(updated_related_bundle)
                related_objs.append(updated_related_bundle.obj)

            # Adding/removing members avoiding extra data changes
            # What is better - cleanup and fill-in again, or
            # this algorithm? Don't know really
            to_remove = set(related_mngr)
            for o in related_objs:
                if not o in related_mngr:
                    related_mngr.add(o)
                if o in to_remove:
                    to_remove.remove(o)
            for o in to_remove:
                related_mngr.remove(o)

    def create_identifier(self, obj):
        return u"%s.%s.%s" % (type(obj).__name__, type(obj).__module__, '.'.join([("%s" % v) for v in obj._get_raw_pkval_()]))

    def full_hydrate(self, bundle):
        #if bundle.obj is None: # TODO: should be changed!
        #    bundle.obj = self._meta.object_class()

        bundle = self.hydrate(bundle)

        attribute_values = {}

        for field_name, field_object in self.fields.items():
            if field_object.readonly is True:
                continue

            # Check for an optional method to do further hydration.
            method = getattr(self, "hydrate_%s" % field_name, None)

            if method:
                bundle = method(bundle)

            if field_object.attribute:
                value = field_object.hydrate(bundle)

                # NOTE: We only get back a bundle when it is related field.
                if isinstance(value, Bundle) and value.errors.get(field_name):
                    bundle.errors[field_name] = value.errors[field_name]
                if value is not None or field_object.null:
                    # We need to avoid populating M2M data here as that will
                    # cause things to blow up.
                    if not getattr(field_object, 'is_related', False):
                        #setattr(bundle.obj, field_object.attribute, value)
                        attribute_values[field_object.attribute] = value
                    elif not getattr(field_object, 'is_m2m', False):
                        if value is not None:
                            attribute_values[field_object.attribute] = value.obj
                        elif field_object.blank:
                            continue
                        elif field_object.null:
                            #setattr(bundle.obj, field_object.attribute, value)
                            attribute_values[field_object.attribute] = value

        if bundle.obj is None:
            bundle.obj = self._meta.object_class(**attribute_values)
        else:
            for a,v in attribute_values.items():
                setattr(bundle.obj,a,v)

        return bundle

    def obj_create(self, bundle, **kwargs):
        #bundle.obj = self._meta.object_class(**kwargs)
        self.authorized_create_detail(self.get_object_list(bundle.request), bundle)
        bundle = self.full_hydrate(bundle)
        return self.save(bundle)
    '''
    def hydrate_m2m(self, bundle):
        """
        Populate the ManyToMany data on the instance.

        Fixed from base to avoid deleting references on ABSENT data,
        """
        if bundle.obj is None:
            raise HydrationError("You must call 'full_hydrate' before attempting to run 'hydrate_m2m' on %r." % self)

        for field_name, field_object in self.fields.items():
            if not getattr(field_object, 'is_m2m', False):
                continue

            if field_object.attribute:
                # Note that we only hydrate the data, leaving the instance
                # unmodified. It's up to the user's code to handle this.
                
                bundle.data[field_name] = field_object.hydrate_m2m(bundle)

        for field_name, field_object in self.fields.items():
            if not getattr(field_object, 'is_m2m', False):
                continue

            method = getattr(self, "hydrate_%s" % field_name, None)

            if method:
                method(bundle)

        return bundle
    '''

    def obj_delete_list(self, bundle, **kwargs):
        """
        A ORM-specific implementation of ``obj_delete_list``.
        """
        objects_to_delete = self.obj_get_list(bundle=bundle, **kwargs)
        deletable_objects = self.authorized_delete_list(objects_to_delete, bundle)

        if hasattr(deletable_objects, 'delete'):
            # It's likely a ``QuerySet``. Call ``.delete()`` for efficiency.
            deletable_objects.delete()
        else:
            for authed_obj in deletable_objects:
                authed_obj.delete()

    def obj_delete_list_for_update(self, bundle, **kwargs):
        """
        A ORM-specific implementation of ``obj_delete_list_for_update``.
        """
        objects_to_delete = self.obj_get_list(bundle=bundle, **kwargs)
        deletable_objects = self.authorized_update_list(objects_to_delete, bundle)

        if hasattr(deletable_objects, 'delete'):
            # It's likely a ``QuerySet``. Call ``.delete()`` for efficiency.
            deletable_objects.delete()
        else:
            for authed_obj in deletable_objects:
                authed_obj.delete()

    def obj_delete(self, bundle, **kwargs):
        """
        A ORM-specific implementation of ``obj_delete``.

        Takes optional ``kwargs``, which are used to narrow the query to find
        the instance.
        """
        if not hasattr(bundle.obj, 'delete'):
            try:
                bundle.obj = self.obj_get(bundle=bundle, **kwargs)
            except ObjectDoesNotExist:
                raise NotFound("A model instance matching the provided arguments could not be found.")

        if bundle.obj == None:
            raise NotFound("A model instance matching the provided arguments could not be found.")

        self.authorized_delete_detail(self.get_object_list(bundle.request), bundle)
        bundle.obj.delete()
