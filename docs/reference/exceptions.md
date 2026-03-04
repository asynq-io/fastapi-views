# Exceptions

HTTP error classes following [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457.html). Import from `fastapi_views.exceptions`.

Every `APIError` subclass automatically:

- generates a typed Pydantic model (`cls.model`) with constant `status`, `title`, and `type` fields
- is registered as a possible response in the OpenAPI spec for any route that declares it
- is converted to a JSON response by the error handler installed by `configure_app`

## Built-in error classes

| Class | Status |
|-------|--------|
| `BadRequest` | 400 |
| `Unauthorized` | 401 |
| `Forbidden` | 403 |
| `NotFound` | 404 |
| `Conflict` | 409 |
| `UnprocessableEntity` | 422 |
| `Throttled` | 429 |
| `InternalServerError` | 500 |
| `Unavailable` | 503 |

## Defining custom errors

Subclass `APIError` and set `status`. The `title` and `type` are derived automatically from the class name and HTTP status code:

```python
from fastapi_views.exceptions import APIError
from starlette.status import HTTP_402_PAYMENT_REQUIRED

class PaymentRequired(APIError):
    """Payment is required to access this resource."""
    status = HTTP_402_PAYMENT_REQUIRED
```

Add extra fields to the error model by annotating them on the class:

```python
class RateLimited(APIError):
    """Rate limit exceeded."""
    status = 429
    retry_after: int  # becomes a required field in the error model
```

---

::: fastapi_views.exceptions
    handler: python
    options:
        show_root_heading: false
        members_order: source
        show_bases: true
        show_signature_annotations: true
