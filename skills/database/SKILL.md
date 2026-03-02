# Database

## When to use this skill
Use when writing queries, making schema changes, adding indexes, or debugging slow database operations.

## Protocol
1. **Schema changes** — Always write a migration; never ALTER TABLE manually in production.
   - Use Alembic (Python) or the framework's migration tool
   - Every migration must have an `upgrade()` and `downgrade()`
   - Test both up and down before committing

2. **Query optimisation** — Measure before changing anything.
   - Run `EXPLAIN ANALYZE` to see the query plan
   - Only add an index after confirming a full-table scan is the bottleneck
   - Add index on foreign keys that are used in JOINs or WHERE clauses

3. **N+1 detection** — If you fetch related records in a loop, rewrite as JOIN or batch fetch.
   - Symptom: 1 query to get N objects, then N queries to get related data
   - Fix: `SELECT ... JOIN ...` or `WHERE id IN (...)`

4. **Transactions** — Wrap every multi-step write in a transaction.
   - Any failure inside the transaction must trigger a rollback
   - Never leave the database in a partial-write state

5. **Parameterized queries** — Never concatenate user input into SQL strings.
   - Use `cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))`
   - Never: `f"SELECT * FROM users WHERE id = {user_id}"`

## Commands
```bash
# Postgres: explain a query
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT ...;

# Postgres: find slow queries (requires pg_stat_statements)
SELECT query, mean_exec_time FROM pg_stat_statements
ORDER BY mean_exec_time DESC LIMIT 10;

# SQLite: query plan
EXPLAIN QUERY PLAN SELECT ...;

# Alembic
alembic upgrade head
alembic downgrade -1
alembic revision --autogenerate -m "add_users_email_index"
alembic history --verbose
```

## Output interpretation
- `Seq Scan` in EXPLAIN output → full table scan; consider adding an index
- `Index Scan` → good; query is using an index
- `Hash Join` / `Nested Loop` → check row estimates; large row counts may need tuning
- `mean_exec_time > 100ms` for a hot query → investigate and optimise
- Migration failure with `relation already exists` → migration was already applied; check alembic_version table

## Done criteria
- All schema changes are in versioned migrations (not manual ALTER statements)
- No N+1 queries in hot paths
- EXPLAIN shows index usage on all queries that filter/sort large tables
- All multi-step writes are wrapped in transactions
- No string concatenation in SQL queries
