CHECKS = [
    (
        "transfer_double_entry",
        "transfers",
        """SELECT count(*) FROM (SELECT t.id FROM transfers t LEFT JOIN ledger_entries l ON t.id=l.transfer_id GROUP BY t.id
 HAVING count(l.id)<>2 OR coalesce(sum(l.signed_amount_minor),0)<>0
 OR count(*) FILTER(WHERE l.entry_kind='transfer_debit' AND l.account_id=t.source_account_id AND l.signed_amount_minor=-t.amount_minor AND l.currency=t.currency)<>1
 OR count(*) FILTER(WHERE l.entry_kind='transfer_credit' AND l.account_id=t.destination_account_id AND l.signed_amount_minor=t.amount_minor AND l.currency=t.currency)<>1) q""",
    ),
    (
        "ledger_topology",
        "ledger_entries",
        """SELECT count(*) FROM ledger_entries l LEFT JOIN accounts a ON a.id=l.account_id LEFT JOIN transfers t ON t.id=l.transfer_id LEFT JOIN seed_runs s ON s.id=l.seed_run_id
 WHERE a.id IS NULL OR a.currency<>l.currency OR (l.entry_kind='provisioning' AND (l.transfer_id IS NOT NULL OR s.id IS NULL OR l.signed_amount_minor<=0 OR l.currency<>s.currency OR l.signed_amount_minor<>s.balance_per_account))
 OR (l.entry_kind IN ('transfer_debit','transfer_credit') AND (t.id IS NULL OR l.seed_run_id IS NOT NULL)) OR l.entry_kind NOT IN ('transfer_debit','transfer_credit','provisioning')""",
    ),
]
