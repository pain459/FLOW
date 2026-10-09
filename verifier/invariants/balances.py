CHECKS = [
    (
        "global_conservation",
        "accounts",
        """SELECT CASE WHEN
 (SELECT coalesce(sum(balance_minor),0) FROM accounts)=
 (SELECT coalesce(sum(signed_amount_minor),0) FROM ledger_entries WHERE entry_kind='provisioning') THEN 0 ELSE 1 END""",
    ),
    (
        "ledger_balance_reconciliation",
        "accounts",
        """SELECT count(*) FROM accounts a LEFT JOIN
 (SELECT account_id,sum(signed_amount_minor) balance FROM ledger_entries GROUP BY account_id) l ON l.account_id=a.id
 WHERE a.balance_minor<>coalesce(l.balance,0)""",
    ),
    (
        "account_state",
        "accounts",
        "SELECT count(*) FROM accounts WHERE balance_minor<0 OR status NOT IN ('active','suspended','closed') OR currency !~ '^[A-Z]{3}$'",
    ),
    (
        "provisioning_evidence",
        "seed_runs",
        """SELECT count(*) FROM seed_runs s LEFT JOIN
 (SELECT seed_run_id,sum(signed_amount_minor) issued,count(*) n FROM ledger_entries WHERE entry_kind='provisioning' GROUP BY seed_run_id) l ON s.id=l.seed_run_id
 WHERE s.issued_minor<>coalesce(l.issued,0) OR s.account_count<>coalesce(l.n,0) OR s.issued_minor<>s.account_count::numeric*s.balance_per_account""",
    ),
]
