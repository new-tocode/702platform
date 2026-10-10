"""让审计日志的「只追加」从约定变成保证：数据库层拒掉 UPDATE / DELETE。

此前只有后台界面在拦（`AuditLogAdmin` 增改删三权限皆假），脚本、数据库客户端、
`queryset.update()` 照样能改能删。这里用 PostgreSQL 的行级触发器把口子堵上：
命中即 `RAISE EXCEPTION`，语句回滚，调用方拿到 `DatabaseError`。

**为什么是触发器而不是收权限**：应用账号就是这张表的属主，属主对自己的表始终
持有隐含权限，`REVOKE` 收不动（要另建角色、拆权限，是部署形态的改动）。触发器
只要表属主就能建，随 `migrate` 生效，也比「记得给新账号配权限」更不容易漏。

**为什么是行级（FOR EACH ROW）而不是语句级**：行级只在**真有行要被改**时才拦，
于是「无匹配行的空语句」放行。这条区别有一个真实的可见后果：删账号时
`AuditLog.user` 的 `SET_NULL` 会去更新这个人的审计行——他**有**审计行，删除就被
挡下（审计留痕不能被改）；他一条审计行都没有时，没有行会被改，删除照常成功。
语句级会把后者也一并挡掉，那是在拦一个不会改动任何留痕的操作。

**逃生口**（`docs/deploy.md` §5.3）：真需要清理时 `ALTER TABLE … DISABLE TRIGGER`
或用 superuser 会话，两者都不改这份迁移；反向迁移也会把触发器摘掉。
"""

from django.db import migrations

TRIGGER_NAME = "core_auditlog_append_only"

CREATE_TRIGGER_SQL = [
    f"""
    CREATE OR REPLACE FUNCTION {TRIGGER_NAME}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION '审计日志只追加（表 core_auditlog）：% 被拒绝。确需清理见 docs/deploy.md §5.3 的逃生口', TG_OP;
    END;
    $$;
    """,
    f"DROP TRIGGER IF EXISTS {TRIGGER_NAME} ON core_auditlog;",
    f"""
    CREATE TRIGGER {TRIGGER_NAME}
        BEFORE UPDATE OR DELETE ON core_auditlog
        FOR EACH ROW EXECUTE FUNCTION {TRIGGER_NAME}();
    """,
]

DROP_TRIGGER_SQL = [
    f"DROP TRIGGER IF EXISTS {TRIGGER_NAME} ON core_auditlog;",
    f"DROP FUNCTION IF EXISTS {TRIGGER_NAME}();",
]


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_rehome_protected_uploads"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_TRIGGER_SQL,
            reverse_sql=DROP_TRIGGER_SQL,
        ),
    ]
