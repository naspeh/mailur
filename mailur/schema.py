from jsonschema import Draft4Validator, FormatChecker, validators


# Based on https://python-jsonschema.readthedocs.org/en/latest/faq/
def fill_defaults(validator_class):
    validate_props = validator_class.VALIDATORS['properties']

    def set_defaults(validator, props, instance, schema):
        for prop, subschema in props.items():
            if isinstance(instance, dict) and 'default' in subschema:
                instance.setdefault(prop, subschema['default'])

        for error in validate_props(validator, props, instance, schema):
            yield error

    return validators.extend(validator_class, {'properties': set_defaults})


Draft4WithDefaults = fill_defaults(Draft4Validator)


class Error(Exception):
    def __init__(self, errors, schema):
        self.schema = schema
        self.errors = errors
        super().__init__(errors, schema)


def validate(value, schema):
    """Collect all errors during validation"""
    validator = Draft4WithDefaults(schema, format_checker=FormatChecker())
    errs = sorted(validator.iter_errors(value), key=lambda e: e.path)
    errs = ['%s: %s' % (list(e.schema_path), e.message) for e in errs]
    if errs:
        raise Error(errs, schema)
    return value
