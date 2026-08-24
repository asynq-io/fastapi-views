# Filters

Filter, sorting, search, pagination and field-projection models, plus the resolvers that turn them into backend queries.

For a complete walkthrough including resolver usage see [Filters](../usage/filters.md).

## Exports

`fastapi_views.filters` re-exports:

| Name | Kind |
|------|------|
| `BaseFilter`, `ModelFilter`, `Filter` | filter models |
| `BasePaginationFilter`, `PaginationFilter`, `OffsetLimitFilter`, `CursorPaginationFilter` | pagination filters |
| `OrderingFilter`, `SearchFilter`, `FieldsFilter`, `IncludeFilter` | sorting / search / projection / relationship-inclusion filters |
| `FilterDepends`, `NestedFilter` | FastAPI dependency factories |

Three modules are **not** re-exported and must be imported from their submodule:

- `fastapi_views.filters.operations` — `FieldOperation`, `FilterOperation`, `SortOperation`, `LogicalOperation`, `Operation`
- `fastapi_views.filters.types` — `QueryField`, `SearchQuery`, `Sort`, `Fields`, `AnyFields`, plus the `QueryParam` wrapper and its `unwrap_query_params` / `set_query_param` helpers
- `fastapi_views.filters.resolvers.*` — `FilterResolver` (`.abc`), `ObjectFilterResolver` (`.objects`), `SQLAlchemyFilterResolver` (`.sqlalchemy`). The `resolvers` package itself is empty, so that importing filters never imports SQLAlchemy.

## Filter models

`BaseFilter` is a Pydantic `BaseModel` that exposes its state as operations. Every subclass contributes to two class variables which are merged across the whole MRO in `__init_subclass__`: `special_fields` (fields that are not data filters and are excluded from `as_kwargs()`) and, for pagination filters, `pagination_fields` (which is merged into `special_fields`).

| Class | Adds | Query parameters | Defaults |
|-------|------|------------------|----------|
| `BaseFilter` | `filters` / `get_filters()`, `as_kwargs()`, `with_kwargs()` | — | — |
| `ModelFilter` | operations built from its own fields, `field_names` | one per declared field | per field |
| `OrderingFilter` | `ordering_fields`, `order_by` / `get_order_by()` | `sort` (repeatable) | `None` |
| `SearchFilter` | `search_fields` | `q` (field name `query`) | `None` |
| `FieldsFilter` | `fields_from`, `get_fields()` | `fields` (repeatable set) | `None` |
| `IncludeFilter` | `related_fields`, `get_related()` | `include` (repeatable set) | `None` |
| `BasePaginationFilter` | `pagination_fields`, `get_pagination()` | — | — |
| `PaginationFilter` | — | `page`, `page_size` | `1`, `100` |
| `OffsetLimitFilter` | — | `offset`, `limit` | `0`, `100` |
| `CursorPaginationFilter` | — | `cursor`, `page_size` | `None`, `100` |
| `Filter` | all of the above | `page`, `page_size`, `sort`, `q`, `fields` + own fields | — |

`Filter` inherits from `PaginationFilter`, `OrderingFilter`, `SearchFilter`, `FieldsFilter` and `ModelFilter`, in that order. `IncludeFilter` is not part of it — compose it explicitly, whitelisting relationship paths in `related_fields` (invalid values yield a 422, like `ordering_fields`).

`ModelFilter` derives an operation's operator from the segment after the **last** `__` in the field name (`user__name__gt` → field `user__name`, operator `gt`) and uses `eq` only for names without any `__`, so a nested equality lookup must be written `user__name__eq`. `BaseFilter.__pydantic_init_subclass__` unwraps the `QueryParam` metadata of every field, which is what makes query-backed fields ordinary `None`-defaulted pydantic fields. `FieldsFilter.fields_from` narrows the annotation on the declaring subclass only.

`page`/`page_size` use the `PageNumber` / `PageSize` aliases and `cursor` uses `Cursor` from [`fastapi_views.pagination`](pagination.md), which also documents the page container each pagination filter pairs with.

::: fastapi_views.filters.models
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

---

## Operations

`get_filters()` returns a list of these dataclasses; `get_order_by()` returns `SortOperation`s. `set_prefix()` is what `NestedFilter` uses to namespace a nested filter's fields as `prefix__field`.

| Class | Fields |
|-------|--------|
| `FieldOperation` | `field`; base class providing `set_prefix(prefix)` |
| `FilterOperation` | `field`, `operator`, `values` |
| `SortOperation` | `field`, `desc = False` |
| `LogicalOperation` | `operator` (`"and"` / `"or"`), `values` (list of operations) |

`Operation` is the union `FilterOperation | SortOperation | LogicalOperation`.

::: fastapi_views.filters.operations
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

---

## Query parameter types

Annotated aliases that make a Pydantic field behave as a FastAPI query parameter. Each carries `Field(None)` as the pydantic default plus a `fastapi.Query` wrapped in `QueryParam`, so pydantic does not absorb the parameter definition; `BaseFilter.__pydantic_init_subclass__` calls `unwrap_query_params` to put the real `Query` back into the built field's metadata, where FastAPI finds it. Consequences: the runtime default is a plain `None`, re-declaring `= None` is harmless, and several such fields in one filter stay independent parameters. A list-typed field declared *without* one of these aliases is inferred as a request body.

| Alias | Type |
|-------|------|
| `QueryField[T]` | `Annotated[T \| None, Field(None), QueryParam(Query())]` |
| `SearchQuery` | `str \| None`, aliased to `q` |
| `Sort` | `list[str] \| None` |
| `Fields[T]` | `set[T] \| None` |
| `AnyFields` | `Fields[str]` |
| `Includes` | `set[str] \| None` |

`set_query_param` replaces an existing `QueryParam` / `Query` in a field's metadata — `OrderingFilter` uses it to give each subclass its own `sort` description without touching the base class.

::: fastapi_views.filters.types
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_signature_annotations: true

---

## Dependencies

`FilterDepends` and `NestedFilter` are FastAPI dependency factories used to inject filter instances into view methods. `FilterDepends` re-raises Pydantic `ValidationError` as `RequestValidationError` so invalid query parameters yield `422` instead of `500`. `NestedFilter(model, prefix=...)` additionally applies an alias generator that renames the nested query parameters to `prefix__field`.

::: fastapi_views.filters.dependencies
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_signature_annotations: true

---

## Resolvers

A resolver translates a filter into a data-layer query. `apply_filter(filter, queryset, exclude=None, **context)` is the entry point; it runs `apply_base_filter`, then `apply_fields_filter`, `apply_related_filter`, `apply_ordering_filter` and `apply_pagination_filter` for the filter bases that apply, skipping any step named in `exclude` (`"filter"`, `"fields"`, `"related"`, `"sort"`, `"paginate"`) and forwarding `context` to each step. Note the abstract steps take `(queryset, filter)` while `apply_filter` takes `(filter, queryset)`.

Operator support per resolver:

| Operator | `SQLAlchemyFilterResolver` | `ObjectFilterResolver` |
|----------|----------------------------|------------------------|
| `eq`, `ne`, `lt`, `le`, `gt`, `ge` | yes | yes |
| `in`, `not_in` | yes | no |
| `is_null` | yes | yes |
| `like`, `ilike` | yes, value wrapped in `%…%` with `\`, `%`, `_` escaped | substring test (`ilike` lowercases both sides) |
| `and`, `or` (`LogicalOperation`) | `operator.and_` / `or_` reduced over the values | `all()` / `any()` |

`ObjectFilterResolver` defines only `is_null`, `like` and `ilike` explicitly and falls back to `getattr(operator, name)`, so any stdlib `operator` function name works while `in` / `not_in` raise `AttributeError`.

### `FilterResolver`

::: fastapi_views.filters.resolvers.abc
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

### `ObjectFilterResolver`

Filters a `list` in memory. `getter` is the accessor factory (`operator.attrgetter` by default; pass `operator.itemgetter` for dicts). Pagination slices the list and supports `OffsetLimitFilter` and `PaginationFilter` only — `CursorPaginationFilter` raises `NotImplementedError`. `apply_fields_filter` returns a **new** list in which every element is projected down to only the attributes named in `?fields`: objects become shallow copies with the other entries removed from their `__dict__`, mappings become new dicts, and values with no `__dict__` (tuples, `__slots__` classes) pass through unchanged. The input list and its objects are never mutated, and an empty `?fields` returns the queryset itself.

::: fastapi_views.filters.resolvers.objects
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true

### `SQLAlchemyFilterResolver`

Subclass it and set `filter_model` to the mapped class the filter's unprefixed fields belong to; it needs no constructor arguments, so `Depends()` can instantiate it. SQLAlchemy itself is optional — the module imports without it and raises `NotImplementedError` when used.

| Member | Description |
|--------|-------------|
| `filter_model` | mapped class used for unprefixed fields |
| `operators` | operator name → callable mapping |
| `resolve(operation, **context)` | one operation → SQLAlchemy expression |
| `resolve_model_field(field, **context)` | `field` or `prefix__field` → column; `context["table"]` overrides the base model, then `context[prefix]["table"]`, then a relationship path on the base model (multi-hop), then a mapper-registry lookup by `__tablename__` |
| `_resolve_related_field(field, **context)` | relationship path → `RelatedField(relationships, column)`, or `None` when the path is not a relationship chain or `context[prefix]["table"]` was supplied |
| `_exists(relationships, predicate)` | wraps `predicate` in one `EXISTS` per hop — `.any()` for to-many, `.has()` for to-one; a `SortOperation` on such a path raises `NotImplementedError` |
| `_cache` / `_get_model_cache(registry)` | registry → `{tablename: model}` memo, a `WeakKeyDictionary` created lazily per resolver subclass, so lookups are cached per registry and per class and cannot leak across two bases sharing a `__tablename__` |
| `get_filters(filter, **context)` | list of `WHERE` expressions |
| `get_order_by(filter, extra=None, **context)` | list of `ORDER BY` expressions, `extra` appended |
| `apply_fields_filter` | `load_only()` for top-level fields; `relation__field` paths become chained eager loaders ending in `.load_only(...)` |
| `apply_related_filter` | `?include` paths become eager loader options: `joinedload` per to-one hop, `selectinload` per to-many hop; unknown paths are skipped |
| `apply_cursor_pagination(queryset, page, page_size, **context)` | raises `NotImplementedError`; override for keyset pagination, keeping `**context` — `apply_pagination_filter` forwards the resolver context |

`Column` and `_Queryset` are typing protocols. `Column` documents the SQLAlchemy column methods the resolver calls — its unbound methods are used as the `in`, `not_in`, `is_null`, `like` and `ilike` implementations, with the real column passed as `self`. `_Queryset` is the minimal queryset surface: `filter()`, `options()`, `order_by()`, `offset()`, `limit()`.

::: fastapi_views.filters.resolvers.sqlalchemy
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
