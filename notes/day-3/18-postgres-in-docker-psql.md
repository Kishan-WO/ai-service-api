# Looking inside PostgreSQL running in Docker (`psql`)

Question: how do I check the database with `psql` when it runs in Docker?

The database container is `ai-service-postgres`, the user is `postgres`, the database is `ai_service` (all from `docker-compose.yml`).

## 1. One-off commands
```bash
docker exec ai-service-postgres psql -U postgres -d ai_service -c "\dt"
docker exec ai-service-postgres psql -U postgres -d ai_service -c "select * from alembic_version"
docker exec ai-service-postgres psql -U postgres -d ai_service -c "\d documents"
```
`docker exec` runs a command **inside** a running container; `psql` is the PostgreSQL client already in the image.

## 2. An interactive session
```bash
docker exec -it ai-service-postgres psql -U postgres -d ai_service
```
`-it` gives an interactive terminal. The prompt becomes `ai_service=#`. Type SQL ending with `;`, and `\q` to leave.

## 3. What the options mean
| Part | Meaning |
|---|---|
| `docker exec` | Run a command in a running container |
| `ai-service-postgres` | The container name (`container_name` in the compose file) |
| `-U postgres` | Log in as the database user `postgres` |
| `-d ai_service` | Use the database `ai_service` |
| `-c "..."` | Run one command, then exit |
| `-it` | Interactive terminal |

## 4. Useful `psql` commands (they start with a backslash)
| Command | Shows |
|---|---|
| `\dt` | Tables |
| `\d tablename` | Columns, indexes, constraints of one table |
| `\di` | Indexes |
| `\l` | All databases |
| `\conninfo` | Who and where I am connected |
| `\x` | Toggle vertical output for wide rows |
| `\q` | Quit |

Ordinary SQL works too:
```sql
select id, email from users;
select count(*) from documents;
select tenant_id, count(*) from documents group by tenant_id;
```

## 5. What I saw
`\dt` after the first migration:
```
 public | alembic_version | table
 public | documents       | table
 public | tenants         | table
 public | users           | table
```
`\d documents` shows the types the models produced: `uuid` keys, `timestamp with time zone`, `jsonb` for `metadata`, the primary key, the index `ix_documents_tenant_id`, and the unique constraint `uq_documents_tenant_content_hash`.

After `alembic downgrade base`, only `alembic_version` is left, with **0 rows**.

## 6. Connecting from the host instead
Needs a `psql` installed on Windows, and the **mapped port** 5433 (not 5432, which my Windows PostgreSQL uses):
```bash
psql -h localhost -p 5433 -U postgres -d ai_service
```
Password: `postgres`.

## 7. If it says "no such container"
```bash
docker ps
```
The `NAMES` column should list `ai-service-postgres` with `Up ... (healthy)`. If not: `docker compose up -d postgres`.

## Common mistakes
| Mistake | What happens |
|---|---|
| Using port 5432 from the host | Connects to the Windows PostgreSQL, not the container |
| Forgetting `-it` for an interactive session | The prompt does not work |
| Missing `;` at the end of SQL | `psql` waits for more input |
| Wrong container name | "No such container" |
| Quoting `\dt` badly in PowerShell | Use double quotes around the command |

## Quick check
- What does `docker exec ... psql` do?
- What do `-U`, `-d` and `-c` mean?
- Which `psql` command shows the columns of a table?
- Why connect to port 5433 from the host?
