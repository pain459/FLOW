CHECKS = [
    (
        "transfer_state",
        "transfers",
        """SELECT count(*) FROM transfers t LEFT JOIN accounts a ON a.id=t.source_account_id LEFT JOIN accounts b ON b.id=t.destination_account_id
 WHERE t.amount_minor<=0 OR t.source_account_id=t.destination_account_id OR t.status<>'committed' OR a.id IS NULL OR b.id IS NULL OR t.currency<>a.currency OR t.currency<>b.currency""",
    ),
    (
        "idempotency_uniqueness",
        "transfers",
        """SELECT count(*) FROM (SELECT idempotency_key FROM transfers GROUP BY idempotency_key HAVING count(*)>1
 UNION ALL SELECT id::text FROM transfers GROUP BY id HAVING count(*)>1) q""",
    ),
]
