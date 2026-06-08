import asyncio, asyncpg, sys
from pathlib import Path
sys.path.insert(0, ".smoke")
from smoke_test import load_env

env = load_env(Path(".env"))

async def go():
    conn = await asyncpg.connect(env["DATABASE_URL"])
    try:
        # All non-system schemas
        schemas = await conn.fetch(
            """
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast')
              AND schema_name NOT LIKE 'pg_temp_%'
              AND schema_name NOT LIKE 'pg_toast_%'
            ORDER BY schema_name
            """
        )
        print("SCHEMAS:", [r["schema_name"] for r in schemas])

        # Does household_members exist ANYWHERE?
        rows = await conn.fetch(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_name IN ('household_members','households','receipts','categories')
            ORDER BY table_schema, table_name
            """
        )
        print("APP TABLES FOUND:")
        for r in rows:
            print(f"  {r['table_schema']}.{r['table_name']}")
        print(f"-- {len(rows)} rows --")

        # search_path
        sp = await conn.fetchval("SHOW search_path")
        print("search_path:", sp)

        # DB name + current_database
        cdb = await conn.fetchval("SELECT current_database()")
        cu = await conn.fetchval("SELECT current_user")
        print(f"db={cdb} user={cu}")
    finally:
        await conn.close()

asyncio.run(go())
