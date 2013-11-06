from tastypie.fields import RelatedField, ApiField, NOT_PROVIDED
from tastypie.resources import Bundle

from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ugettext_noop

import datetime

class GMTDateTimeNaiveField(ApiField):
    """
    A datetime field for naive Greenwich-based datetime values - returns iso-8601
    """
    dehydrated_type = 'string'
    help_text = 'A GMT date & time as a string iso-8601. Ex: "2010-11-10T03:07:43Z"'

    def convert(self, value):
        if value is None:
            return None
        if isinstance(value,datetime.datetime):
            value = value.strftime("%Y-%m-%dT%H:%M:%SZ")

        return value

    def hydrate(self, bundle):
        value = super(GMTDateTimeNaiveField, self).hydrate(bundle)

        if isinstance(value, basestring):
            match = DATETIME_RE.match(value)

            if match:
                data = match.groupdict()
                value = datetime_safe.datetime(
                    int(data['year']),
                    int(data['month']),
                    int(data['day']),
                    int(data['hour']),
                    int(data['minute']),
                    int(data['second'])
                )
        
        return value

class SetField(RelatedField):
    """
    Provides access to related data via a join table (Pony ORM)

    This subclass requires Pony ORM layer to work properly.
    """
    is_m2m = True
    help_text = 'Many related resources. Can be either a list of URIs or list of individually nested resource data.'

    def __init__(self, to, attribute, related_name=None, default=NOT_PROVIDED,
                 null=False, blank=False, readonly=False, full=False,
                 unique=False, help_text=None, use_in='all', full_list=True, full_detail=True):
        super(SetField, self).__init__(
            to, attribute, related_name=related_name, default=default,
            null=null, blank=blank, readonly=readonly, full=full,
            unique=unique, help_text=help_text, use_in=use_in,
            full_list=full_list, full_detail=full_detail
        )
        self.m2m_bundles = []

    def dehydrate(self, bundle, for_list=True):
        the_m2ms = None
        previous_obj = bundle.obj
        attr = self.attribute

        if isinstance(self.attribute, basestring):
            attrs = self.attribute.split('__')
            the_m2ms = bundle.obj

            for attr in attrs:
                previous_obj = the_m2ms
                #try:
                #    the_m2ms = getattr(the_m2ms, attr, None)
                #except ObjectDoesNotExist:
                #    the_m2ms = None
                the_m2ms = getattr(the_m2ms, attr)

                if not the_m2ms:
                    break


        elif callable(self.attribute):
            the_m2ms = self.attribute(bundle)

        if not the_m2ms:
            if not self.null:
                raise ApiFieldError("The model '%r' has an empty attribute '%s' and doesn't allow a null value." % (previous_obj, attr))

            return []

        self.m2m_resources = []
        m2m_dehydrated = []

        for m2m in the_m2ms:
            m2m_resource = self.get_related_resource(m2m)
            m2m_bundle = Bundle(obj=m2m, request=bundle.request)
            self.m2m_resources.append(m2m_resource)
            m2m_dehydrated.append(self.dehydrate_related(m2m_bundle, m2m_resource, for_list=for_list))

        return m2m_dehydrated

    def hydrate(self, bundle):
        pass

    def hydrate_m2m(self, bundle):
        if self.readonly:
            return None

        # TODO: why the original code works? don't know a while
        # the EMPTY list differs from ABSENCE of list:
        #    the EMPTY list leads to cleanup, while
        #    the ABSENCE of list leads to leave the object set unchanged
        if bundle.data.get(self.instance_name) is None:
            return None

        m2m_hydrated = []

        for value in bundle.data.get(self.instance_name):
            if value is None:
                continue

            kwargs = {
                'request': bundle.request,
            }

            if self.related_name:
                kwargs['related_obj'] = bundle.obj
                kwargs['related_name'] = self.related_name

            m2m_hydrated.append(self.build_related_resource(value, **kwargs))

        return m2m_hydrated
