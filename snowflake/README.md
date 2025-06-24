`SnowSQL` - CLI for Snowflake

Run all changed files in the repository
```shell
for sql_file in $(git diff --name-only $CI_COMMIT_BEFORE_SHA $CI_COMMIT_SHA | grep '\.sql$'); do
    snowsql -o exit_on_error=true -f "$sql_file"
done
```
