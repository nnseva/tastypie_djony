from tastypie.exceptions import TastypieError, Unauthorized
from tastypie.authorization import Authorization

class PonyAuthorization(Authorization):
    """
    Checks Pony object against Django-specific user got from the request to map
    ``POST / PUT / DELETE / PATCH`` to their equivalent Django auth
    permissions.
    """
    def get_pony_user_from_django_user(self,user):
        if user.id:
            return user._meta.concrete_model.p.get(id = user.id)

    def get_pony_user_from_request(self,request):
        if hasattr(request,'user'):
            return self.get_pony_user_from_django_user(request.user)

    def get_pony_user(self,bundle):
        return self.get_pony_user_from_request(bundle.request)

    def get_pony_hasperm_model(self,user,perm,pony_model):
        from djony import orm
        dm = orm.db().djony['models'][pony_model.__name__]['model']
        if perm:
            return self.get_pony_hasperm(user,dm._meta.app_label,perm,dm.__name__.lower())
        else:
            return self.get_pony_hasanyperm(user,dm._meta.app_label,dm.__name__.lower())

    def get_pony_hasperm(self,user,app_label,perm,name):
        from django.contrib.auth.models import Permission
        from djony import orm
        if not user.is_active:
            return False
        if user.is_superuser:
            return True
        codename = perm+"_"+name
        for p in orm.select(
            p for p in Permission.p
            if
                (user in p.user_set or user in p.group_set.user_set) and
                p.codename == codename and
                p.content_type.app_label == app_label
        ):
            return True
        return False

    def get_pony_hasanyperm(self,user,app_label,name):
        from django.contrib.auth.models import Permission
        from djony import orm
        if not user.is_active:
            return False
        if user.is_superuser:
            return True
        for p in orm.select(
            p for p in Permission.p
            if
                (user in p.user_set or user in p.group_set.user_set) and
                p.codename.endswith('_'+name) and
                p.content_type.app_label == app_label
        ):
            return True
        return False

    def read_list(self, object_list, bundle):
        # GET-style methods are always allowed.
        return object_list

    def read_detail(self, object_list, bundle):
        # GET-style methods are always allowed.
        return True

    def check_list(self, object_list, bundle, perm):
        user = self.get_pony_user(bundle)
        return self.get_pony_hasperm_model(user,perm,object_list._origin)

    def check_detail(self, object_list, bundle, perm):
        user = self.get_pony_user(bundle)
        if not self.get_pony_hasperm_model(user,perm,object_list._origin):
            raise Unauthorized("You are not allowed to access that resource.")
        return True

    def create_list(self, object_list, bundle):
        return self.check_list(object_list, bundle, 'add')

    def create_detail(self, object_list, bundle):
        return self.check_detail(object_list, bundle, 'add')

    def update_list(self, object_list, bundle):
        return self.check_list(object_list, bundle, 'change')

    def update_detail(self, object_list, bundle):
        return self.check_detail(object_list, bundle, 'change')

    def delete_list(self, object_list, bundle):
        return self.check_list(object_list, bundle, 'delete')

    def update_detail(self, object_list, bundle):
        return self.check_detail(object_list, bundle, 'delete')
