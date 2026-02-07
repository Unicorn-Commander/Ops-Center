---
name: postgresql-ops
description: Query and monitor PostgreSQL databases (read-only operations)
actions:
  - name: list_databases
    description: List all PostgreSQL databases with sizes
    confirmation_required: false
    parameters: {}

  - name: list_tables
    description: List all tables in a database with sizes
    confirmation_required: false
    parameters:
      database:
        type: string
        description: Database name
        default: unicorn_db

  - name: query
    description: Run a read-only SQL query (SELECT, EXPLAIN only)
    confirmation_required: false
    parameters:
      query:
        type: string
        description: SQL query to execute (SELECT or EXPLAIN only)
        required: true
      database:
        type: string
        description: Database name
        default: unicorn_db

  - name: stats
    description: Get PostgreSQL database statistics (connections, transactions)
    confirmation_required: false
    parameters: {}
---
PostgreSQL operations skill. Provides read-only access to PostgreSQL databases
running in the unicorn-postgresql container. Write operations (INSERT, UPDATE,
DELETE, DROP, ALTER) are blocked for safety.
