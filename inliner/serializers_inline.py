from django.db import models
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from rest_framework import serializers

_registered_inliners = {}
_registered_model_serializers = {None.__class__: serializers.Serializer}


def register_model_serializer(serializer_class):
    _registered_model_serializers[serializer_class.Meta.model] = serializer_class


def register_inline_attribute(singular_desc, plural_desc, kwargs=None):
    _registered_inliners[singular_desc] = (singular_desc, plural_desc, kwargs or {})
    _registered_inliners[plural_desc] = (singular_desc, plural_desc, kwargs or {})


def register_inline(singular_desc, plural_desc, serializer_class, kwargs=None):
    if singular_desc == plural_desc:
        raise Exception('Error singular_desc shouldn\'t be equal to plural_desc')

    register_inline_attribute(singular_desc, plural_desc, kwargs)
    register_model_serializer(serializer_class)


class InlinerSerializerMixin(object):
    def __init__(self, *args, **kwargs):
        self.inlined_fields = kwargs.pop('inlined_fields', None)
        super(InlinerSerializerMixin, self).__init__(*args, **kwargs)

    def generate_inlines(self, instance):
        inlined_fields = self.inlined_fields

        if not inlined_fields:
            if not self.context or not self.context.get('request', None):
                return

            request = self.context.get('request', None)

            inlined_fields = request.query_params.get('inline', None)
            if not inlined_fields:
                return

        for inlined_field in inlined_fields.split(','):
            next_level_inlined_fields = ''

            if '.' in inlined_field:
                inlined_field, next_level_inlined_fields = inlined_field.split('.', 1)

            if inlined_field not in _registered_inliners:
                raise FieldDoesNotExist('Inline "%s" not found.' % (inlined_field,))

            singular_desc, plural_desc, kwargs = _registered_inliners[inlined_field]
            try:
                inlined_object = instance.__getattribute__(inlined_field)
            except ObjectDoesNotExist:
                inlined_object = None
            except AttributeError:
                try:
                    inlined_object = instance.__getattribute__(singular_desc + '_set')
                    kwargs['source'] = singular_desc + '_set'
                except AttributeError:
                    raise FieldDoesNotExist('''Can't Inline field "%s" for object "%s".''' % (inlined_field, instance))

            many = isinstance(inlined_object, models.Manager)
            if many:
                serializer_class = _registered_model_serializers[inlined_object.model]
            else:
                serializer_class = _registered_model_serializers[inlined_object.__class__]
            kwargs['many'] = many

            # If the serializer class isn't an inliner then it can't handle the inlined_fields kwarg.
            if issubclass(serializer_class, InlinerSerializerMixin):
                serializer = serializer_class(inlined_fields=next_level_inlined_fields, **kwargs)
            else:
                serializer = serializer_class(**kwargs)
            self.fields[inlined_field] = serializer
            self.fields[inlined_field].parent = None

    @property
    def _readable_fields(self):
        return [field for field in self.fields.values() if not field.write_only]

    def to_representation(self, instance):
        self.generate_inlines(instance)
        return super(InlinerSerializerMixin, self).to_representation(instance)
