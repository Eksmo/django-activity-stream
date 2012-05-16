from UserDict import UserDict
from django.conf import settings
from django.db.models import get_model
from django.utils.functional import  memoize

class LazyModels(dict):

    def __getitem__(self, item):
        v = dict.__getitem__(self, item)
        return get_model(*tuple(v))

    def values(self):
        return [get_model(*tuple(value)) for value in dict.values(self)]


MODELS = LazyModels()
for model in getattr(settings, 'ACTSTREAM_ACTION_MODELS', ('auth.User',)):
    MODELS[model.lower()] = model.split('.')

MANAGER_MODULE = getattr(settings, 'ACTSTREAM_MANAGER',
    'actstream.managers.ActionManager')
a, j = MANAGER_MODULE.split('.'), lambda l: '.'.join(l)
MANAGER_MODULE = getattr(__import__(j(a[:-1]), {}, {}, [a[-1]]), a[-1])
