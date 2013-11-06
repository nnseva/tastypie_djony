=======
Tastypie-Djony
=======

Whats new?
----------

2013-11-06:

The first release

Base
----

This package may be used to make your Tastypie-based API faster with Pony ORM.

The package uses Djony (http://github.com/nnseva/djony) package
to integrate Pony ORM (http://doc.ponyorm.com/) into the
Django, and inherits Tastypie (http://django-tastypie.readthedocs.org/en/latest/)
package using it's infrastructure to implement Pony-based API.

The preliminary tests show that the resulting API is faster 1-4 times
comparing with Tastypie-native API based on Django ORM. Results
very depend on number of objects got, using inheritance and
especially impressive with One-To-Many reltionships.

Note that you need to install the djony package and include `djony`
at the END (required) of `INSTALLED_APPS`.

Limitations
-----------

- Django-style inheritance is not supported by Djony, so use underlining
  one-to-one relationship in the API declaration instead
- `regex`, `week_day`, and `search` filters are not supported yet


Using
-----

Compare the following API declarations:

Django-based (old-style)::

```python
from django.contrib.auth import models as auth_models

from tastypie.constants import ALL,ALL_WITH_RELATIONS
from tastypie import ModelResource
from tastypie import ToManyField, ToOneField

class PermissionResource(ModelResource):
    class Meta:
        queryset = auth_models.Permission.objects.all()
        object_model = queryset.model
        filtering = dict([(n,ALL_WITH_RELATIONS) for n in object_model._meta.get_all_field_names()])
        resource_name = 'auth/permission'
class UserResource(ModelResource):
    user_permissions = ToManyField(PermissionResource,'user_permissions',related_name='user_set',null=True)
    class Meta:
        queryset = auth_models.User.objects.all()
        object_model = queryset.model
        filtering = dict([(n,ALL_WITH_RELATIONS) for n in object_model._meta.get_all_field_names()])
        resource_name = 'auth/user'
```

Pony-based (new-style)::

```python
...
from django.contrib.auth import models as auth_models

from tastypie.constants import ALL,ALL_WITH_RELATIONS
from tastypie import ModelResource
from tastypie import ToManyField, ToOneField

from tastypie_djony.resources import DjonyResource
from tastypie_djony.fields import SetField

class PermissionResource(DjonyResource):
    class Meta:
        object_model = auth_models.Permission
        filtering = dict([(n,ALL_WITH_RELATIONS) for n in object_model._meta.get_all_field_names()])
        resource_name = 'auth/permission'

class UserResource(DjonyResource):
    user_permissions = SetField(PermissionResource,'user_permissions',related_name='user_set',null=True)
    class Meta:
        object_model = auth_models.User
        filtering = dict([(n,ALL_WITH_RELATIONS) for n in object_model._meta.get_all_field_names()])
        resource_name = 'auth/user'
```

Use `DjonyResource` instead of tastypie-native `ModelResource`.

Use `SetField` instead of the tastypie-native `ToManyField`. You can use tastypie-native `ToOneField`
as before, without notable changes.

Use `object_model` instead of `queryset` member of the Meta class for the resource declaration as
you can see in the example above.

TODO-LIST
---------

1. Regression testing

Pull requests are very appretiated!

Roadmap
-------

1. Pony-based API authorization and authentication
