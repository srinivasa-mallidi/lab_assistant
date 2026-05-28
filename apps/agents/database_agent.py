"""
Database Agent
Converts natural language to safe, read-only SQL for SampleManager LIMS.
Supports SQL Server, Oracle, PostgreSQL.
"""

import logging
import json
import time
import re
from dataclasses import dataclass, field
from typing import Optional, Any, Tuple

import ollama as ollama_client

from django.conf import settings

logger = logging.getLogger("lab_assistant")
audit_logger = logging.getLogger("audit")


def _call_ollama(prompt: str, temperature: float = 0.0) -> str:
    """Call Ollama using the ollama Python library."""
    model_key = settings.OLLAMA_DEFAULT_MODEL
    model = settings.SUPPORTED_MODELS.get(model_key, {"name": "llama3:latest"})["name"]
    response = ollama_client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": temperature},
    )
    return response["message"]["content"]


@dataclass
class DBResult:
    data: Optional[list] = None
    sql: Optional[str] = None
    formatted_result: str = ""
    row_count: int = 0
    error: Optional[str] = None
    columns: list = field(default_factory=list)


# ─── Real SampleManager LIMS Schema ──────────────────────────────────────────
# Based on actual Oracle RDS schema (LUBACC / SLUA user)
SAMPLEMANAGER_SCHEMA = """
SampleManager LIMS Database — Real Oracle Schema (READ-ONLY):

TABLE: SAMPLE_TABLE   (main samples table)
  ID_NUMERIC       NUMBER        -- numeric sample ID (internal key)
  ID_TEXT          VARCHAR2      -- text sample ID shown to users e.g. "LAB-2026-001"
  JOB_NAME         VARCHAR2      -- job/batch name
  STATUS           VARCHAR2      -- current status e.g. 'U' (unreported), 'A' (authorised), 'X' (cancelled)
  OLD_STATUS       VARCHAR2      -- previous status
  SAMPLED_DATE     DATE          -- when sample was taken
  RECD_DATE        DATE          -- when sample was received in lab
  DATE_STARTED     DATE          -- when analysis started
  DATE_COMPLETED   DATE          -- when analysis completed
  DATE_AUTHORISED  DATE          -- when sample was authorised/approved
  COMPLETER        VARCHAR2      -- who completed the analysis
  AUTHORISER       VARCHAR2      -- who authorised
  AUTHORISATION_NOTES VARCHAR2   -- authorisation comments
  PRODUCT          VARCHAR2      -- product name e.g. "Crude Oil", "Fuel Oil"
  PRODUCT_VERSION  VARCHAR2      -- product version
  GRADE_CODE       VARCHAR2      -- grade/spec code
  SAMPLE_NAME      VARCHAR2      -- sample description
  DESCRIPTION      VARCHAR2      -- additional description
  SAMPLE_TYPE      VARCHAR2      -- type of sample
  BATCH_NAME       VARCHAR2      -- batch reference
  SAMPLING_POINT   VARCHAR2      -- where sample was taken
  PRIORITY         NUMBER        -- priority level (higher = more urgent)
  PROJECT_ID       VARCHAR2      -- project reference
  LOCATION_ID      VARCHAR2      -- location reference
  CUSTOMER_ID      VARCHAR2      -- customer reference
  TESTS_TO_DO      NUMBER        -- total number of tests
  ON_WKS           VARCHAR2      -- on worksheet flag
  LOGIN_DATE       DATE          -- when logged into system
  LOGIN_BY         VARCHAR2      -- who logged the sample
  PREPARATION      VARCHAR2      -- sample preparation method
  HAZARD           VARCHAR2      -- hazard information
  ORIGINAL_SAMPLE  VARCHAR2      -- original sample reference
  RE_SAMPLED       VARCHAR2      -- resampled flag

TABLE: TEST_TABLE   (test results table)
  TEST_NUMBER      VARCHAR2      -- unique test identifier
  ANALYSIS         VARCHAR2      -- analysis/test type name
  SAMPLE           VARCHAR2      -- FK to SAMPLE_TABLE.ID_TEXT
  STATUS           VARCHAR2      -- test status: 'U' unreported, 'A' authorised, 'X' cancelled
  OLD_STATUS       VARCHAR2      -- previous status
  DATE_STARTED     DATE          -- when test started
  DATE_COMPLETED   DATE          -- when test completed
  DATE_AUTHORISED  DATE          -- when test authorised
  STARTER          VARCHAR2      -- who started the test
  COMPLETER        VARCHAR2      -- who completed the test
  AUTHORISER       VARCHAR2      -- who authorised the test
  ON_SPEC          VARCHAR2      -- is result within spec? 'Y' or 'N'
  VALIDATION_STATUS VARCHAR2     -- validation state
  AUTHORISATION_COMMENT VARCHAR2 -- approval notes
  TEST_PRIORITY    NUMBER        -- test priority
  INSTRUMENT       VARCHAR2      -- instrument used
  REPLICATE_TEST   VARCHAR2      -- replicate test reference
  TEST_COUNT       NUMBER        -- number of test entries
  WORKSHEET        VARCHAR2      -- worksheet reference
  PREPARATION      VARCHAR2      -- preparation method

TABLE: APPROVAL   (approval workflow table)
  -- Contains approval workflow records
  -- Join to SAMPLE_TABLE via sample ID

TABLE: ACCESS_LOG   (audit trail)
TABLE: ACTIVITY_LOG (activity records)
"""

NL_TO_SQL_PROMPT = """You are an Oracle SQL expert for a SampleManager LIMS database.
Generate a safe, READ-ONLY Oracle SQL query (SELECT only).

DATABASE ENGINE: Oracle
TODAY'S DATE: {today_date}

{schema}

CRITICAL ORACLE SYNTAX RULES:
1. ONLY SELECT — NO INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, EXEC
2. ALWAYS end query with: FETCH FIRST 200 ROWS ONLY
3. Oracle date syntax ONLY — NEVER use GETDATE(), DATEADD(), TOP N, LIMIT
4. All parentheses MUST be balanced
5. No SQL comments (--)
6. Use single quotes for strings: STATUS = 'U'

STATUS VALUES in SampleManager:
  'U' = Unreported/Pending
  'A' = Authorised/Completed
  'X' = Cancelled
  'C' = In progress

DATE FUNCTIONS (Oracle only):
  Today:           TRUNC(SYSDATE)
  Last 7 days:     SYSDATE - 7
  Last week:       TRUNC(SYSDATE) - 7
  This month:      TRUNC(SYSDATE, 'MM')
  Yesterday:       TRUNC(SYSDATE) - 1
  Date column:     TRUNC(RECD_DATE) = TRUNC(SYSDATE)

CORRECT ORACLE EXAMPLES — follow these exactly:

Example 1 — Last week samples:
SELECT ID_TEXT, SAMPLE_NAME, STATUS, PRODUCT, RECD_DATE, LOGIN_BY
FROM SAMPLE_TABLE
WHERE RECD_DATE >= SYSDATE - 7
ORDER BY RECD_DATE DESC
FETCH FIRST 200 ROWS ONLY

Example 2 — Pending/unreported samples today:
SELECT ID_TEXT, SAMPLE_NAME, STATUS, PRODUCT, PRIORITY, RECD_DATE
FROM SAMPLE_TABLE
WHERE STATUS = 'U'
AND TRUNC(RECD_DATE) = TRUNC(SYSDATE)
ORDER BY PRIORITY DESC
FETCH FIRST 200 ROWS ONLY

Example 3 — Failed/out-of-spec tests:
SELECT t.TEST_NUMBER, t.ANALYSIS, t.SAMPLE, t.ON_SPEC, t.DATE_COMPLETED
FROM TEST_TABLE t
WHERE t.ON_SPEC = 'N'
AND t.DATE_COMPLETED >= SYSDATE - 7
ORDER BY t.DATE_COMPLETED DESC
FETCH FIRST 200 ROWS ONLY

Example 4 — Join samples and tests:
SELECT s.ID_TEXT, s.PRODUCT, t.ANALYSIS, t.ON_SPEC, t.DATE_COMPLETED
FROM SAMPLE_TABLE s
JOIN TEST_TABLE t ON t.SAMPLE = s.ID_TEXT
WHERE t.ON_SPEC = 'N'
AND t.DATE_COMPLETED >= SYSDATE - 7
ORDER BY t.DATE_COMPLETED DESC
FETCH FIRST 200 ROWS ONLY

Example 5 — Samples by product this month:
SELECT ID_TEXT, SAMPLE_NAME, PRODUCT, STATUS, RECD_DATE
FROM SAMPLE_TABLE
WHERE RECD_DATE >= TRUNC(SYSDATE, 'MM')
AND PRODUCT = 'Fuel Oil'
ORDER BY RECD_DATE DESC
FETCH FIRST 200 ROWS ONLY

USER QUESTION: {user_question}

Generate ONLY the Oracle SQL. No markdown, no explanation, no comments, no backticks:"""


RESULT_SUMMARY_PROMPT = """You are a laboratory data analyst. Summarize these query results clearly.

ORIGINAL QUESTION: {user_question}
SQL EXECUTED: {sql_query}
TOTAL ROWS: {row_count}
RESULTS:
{results_json}

Create a clear, professional summary:
- Start with a direct answer to the question
- Highlight key statistics (counts, percentages)
- Flag urgent items (STAT priority, FAILED status, overdue samples)
- Use bullet points for lists
- If no results, explain what that means

SUMMARY:"""


class SQLSafetyValidator:
    """Validates generated SQL for safety before execution."""

    # Forbidden SQL keywords
    FORBIDDEN_PATTERNS = [
        r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b",
        r"\bCREATE\b", r"\bALTER\b", r"\bTRUNCATE\b", r"\bEXEC\b",
        r"\bEXECUTE\b", r"\bSP_\w+", r"\bXP_\w+", r"\bMERGE\b",
        r"\bGRANT\b", r"\bREVOKE\b", r"\bDENY\b",
        r"--",          # SQL comment injection
        r"/\*",         # Block comment injection
        r";\s*\w",      # Multiple statements
        r"\bSYSOBJECTS\b", r"\bINFORMATION_SCHEMA\b",  # Schema exploration
        r"\bSYSCOLUMNS\b", r"\bSYSTABLES\b",
    ]

    @classmethod
    def validate(cls, sql: str) -> Tuple[bool, str]:
        """
        Returns (is_safe, reason).
        """
        if not sql or not sql.strip():
            return False, "Empty SQL query"

        upper_sql = sql.upper().strip()

        # Must start with SELECT
        if not upper_sql.startswith("SELECT"):
            return False, f"Query must start with SELECT, got: {upper_sql[:20]}"

        # Check forbidden patterns
        for pattern in cls.FORBIDDEN_PATTERNS:
            if re.search(pattern, upper_sql, re.IGNORECASE):
                return False, f"Forbidden SQL pattern detected: {pattern}"

        # Ensure has FROM clause (sanity)
        if "FROM" not in upper_sql:
            return False, "Query must contain FROM clause"

        # Check for excessive row requests
        if "LIMIT" not in upper_sql and "TOP" not in upper_sql and "ROWNUM" not in upper_sql:
            logger.warning("SQL query missing row limit - will add default")

        return True, "OK"

    @classmethod
    def add_limit(cls, sql: str, db_engine: str, max_rows: int = 200) -> str:
        """Add row limit if missing."""
        upper = sql.upper().strip()
        if "LIMIT" in upper or "TOP" in upper or "ROWNUM" in upper:
            return sql

        if db_engine in ("mssql", "sqlserver"):
            # Add TOP after SELECT
            return re.sub(r"^SELECT\s+", f"SELECT TOP {max_rows} ", sql, flags=re.IGNORECASE)
        elif db_engine == "postgresql":
            return sql.rstrip(";") + f" LIMIT {max_rows}"
        elif db_engine == "oracle":
            return f"SELECT * FROM ({sql}) WHERE ROWNUM <= {max_rows}"

        return sql


class LIMSConnection:
    """Manages read-only database connections to SampleManager."""

    _instances: dict = {}

    @classmethod
    def get_connection(cls, db_config: dict):
        engine = db_config.get("ENGINE", "mssql")

        if engine not in cls._instances:
            cls._instances[engine] = cls._create_connection(db_config)

        return cls._instances[engine]

    @classmethod
    def _create_connection(cls, db_config: dict):
        engine = db_config.get("ENGINE", "mssql")
        host = db_config["HOST"]
        port = int(db_config.get("PORT", 1521))
        name = db_config["NAME"]   # service name for Oracle
        user = db_config["USER"]
        password = db_config["PASSWORD"]

        try:
            if engine in ("mssql", "sqlserver"):
                import pyodbc
                conn_str = (
                    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                    f"SERVER={host},{port};DATABASE={name};"
                    f"UID={user};PWD={password};"
                    f"ReadOnly=1;"
                )
                return pyodbc.connect(conn_str, autocommit=True)

            elif engine == "oracle":
                # Try modern python-oracledb first, fall back to cx_Oracle
                try:
                    import oracledb
                    # python-oracledb thin mode — no Oracle Client install needed
                    oracledb.init_oracle_client()   # thick mode if client available
                except Exception:
                    pass

                try:
                    import oracledb
                    dsn = f"{host}:{port}/{name}"
                    conn = oracledb.connect(user=user, password=password, dsn=dsn)
                    logger.info(f"Connected via oracledb (thin) to {host}:{port}/{name}")
                    return conn
                except ImportError:
                    pass

                # Fallback: cx_Oracle (older driver)
                import cx_Oracle
                dsn = cx_Oracle.makedsn(host, port, service_name=name)
                conn = cx_Oracle.connect(user=user, password=password, dsn=dsn)
                logger.info(f"Connected via cx_Oracle to {host}:{port}/{name}")
                return conn

            elif engine == "postgresql":
                import psycopg2
                return psycopg2.connect(
                    host=host, port=port, dbname=name,
                    user=user, password=password,
                    options="-c default_transaction_read_only=on"
                )

        except ImportError as e:
            logger.error(f"Database driver not installed: {e}")
            raise
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

    @classmethod
    def execute_query(cls, sql: str, params=None) -> Tuple[list, list]:
        """Execute SQL and return (rows, columns)."""
        conn = cls.get_connection(settings.LIMS_DATABASE)
        cursor = conn.cursor()
        cursor.execute(sql, params or [])
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        cursor.close()
        return rows, columns


class DatabaseAgent:
    def __init__(self):
        self.validator = SQLSafetyValidator()
        self.db_engine = settings.LIMS_DATABASE.get("ENGINE", "mssql")

    async def query(self, context) -> DBResult:
        """Full NL → SQL → Execute → Summarize pipeline."""
        from datetime import date

        start = time.time()

        # 1. Generate SQL
        sql = self._generate_sql(context.message)
        if not sql:
            return DBResult(
                formatted_result="I could not generate a valid SQL query for your question.",
                error="SQL generation failed"
            )

        # 2. Validate safety
        is_safe, reason = self.validator.validate(sql)
        if not is_safe:
            security_logger = logging.getLogger("security")
            security_logger.warning(
                f"UNSAFE SQL blocked for user {context.user_id}: {reason}\nSQL: {sql}"
            )
            return DBResult(
                sql=sql,
                formatted_result=f"The generated query was blocked for security: {reason}",
                error="SQL_SAFETY_BLOCK"
            )

        # 3. Add limit if missing
        sql = self.validator.add_limit(sql, self.db_engine)

        # 4. Audit log
        audit_logger.info(
            f"SQL QUERY | user={context.user_id} | session={context.session_id} | "
            f"intent={context.intent} | sql={sql[:500]}"
        )

        # 5. Execute
        try:
            rows, columns = LIMSConnection.execute_query(sql)
        except Exception as e:
            logger.error(f"SQL execution error: {e}")
            return DBResult(
                sql=sql,
                formatted_result=f"Database query failed: {str(e)}. Please verify LIMS connectivity.",
                error=str(e)
            )

        # 6. Summarize results
        result_preview = json.dumps(rows[:20], default=str, indent=2)
        summary = self._summarize_results(context.message, sql, result_preview, len(rows))

        elapsed = int((time.time() - start) * 1000)
        logger.info(f"DB query completed in {elapsed}ms, {len(rows)} rows")

        return DBResult(
            data=rows,
            sql=sql,
            formatted_result=summary,
            row_count=len(rows),
            columns=columns,
        )

    def _generate_sql(self, question: str) -> Optional[str]:
        from datetime import date
        prompt = NL_TO_SQL_PROMPT.format(
            schema=SAMPLEMANAGER_SCHEMA,
            user_question=question,
            db_engine=self.db_engine,
            today_date=date.today().isoformat(),
        )
        try:
            raw = _call_ollama(prompt, temperature=0.0)
            raw = re.sub(r"```sql\n?", "", raw)
            raw = re.sub(r"```\n?", "", raw)
            return raw.strip()
        except Exception as e:
            logger.error(f"SQL generation failed: {e}")
            return None

    def _summarize_results(self, question: str, sql: str, results_json: str, row_count: int) -> str:
        prompt = RESULT_SUMMARY_PROMPT.format(
            user_question=question,
            sql_query=sql,
            results_json=results_json,
            row_count=row_count,
        )
        try:
            return _call_ollama(prompt, temperature=0.1)
        except Exception as e:
            logger.error(f"Result summarization failed: {e}")
            return f"Query returned {row_count} results."