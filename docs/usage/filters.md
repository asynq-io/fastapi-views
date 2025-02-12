## Available filter classes

- `BaseFilter` - base class for all filters
- `ModelFilter` - class for filtering by pydantic model fields
- `OrderingFilter` - class for ordering by fields
- `SearchFilter` - class for searching by fields
- `PaginationFilter` - class for pagination
- `Filter` - All of the above


## Available resolvers

- `ObjectFilterResolver` - class for filtering by object fields, works for lists of objects/dictionaries.
- `SQLAlchemyFilterResolver` - class for filtering by SQLAlchemy model fields

## Helpers & Dependencies

- `NestedFilter` - class for filtering by nested fields
- `FilterDependency` - class for filtering by dependencies

## Usage

```python

class PostModel(Base):
    __tablename__ = "post"
    title: str = mapped_column(sa.String())
    content: str = mapped_column(sa.String())
    created_at: datetime = mapped_column(sa.DateTime())
    user_id: int = mapped_column(sa.Integer(), sa.ForeignKey("user.id"))

class UserModel(Base):
    __tablename__ = "user"
    id: int = mapped_column(sa.Integer(), primary_key=True)
    name: str = mapped_column(sa.String())
    email: str = mapped_column(sa.String())
    created_at: datetime = mapped_column(sa.DateTime())


class PostFilter(ModelFilter):
    title: str | None = None


class UserFilter(Filter):
    name: str | None = None
    email: str | None = None

    post: PostFilter = NestedFilter(
        PostFilter, prefix="post"
    ) # query parameter with become post__title

    search_fields = {"name", "email", "post__name"}  # django-like syntax for search fields
    ordering_fields = {"name", "created_at"}


class AsyncListView(AsyncListAPIView):

    async def list(self, filter: Filter = FilterDepends(UserFilter), resolver: SQLAlchemyFilterResolver = Depends()):
        queryset = resolver.apply_filter(filter, select(UserModel))
        # applies ordering, pagination, searching etc.
        async with self.db_session() as session:
            users = await session.execute(queryset)
            return users.scalars().all()

```
