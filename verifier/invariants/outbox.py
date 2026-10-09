CHECKS = [
    (
        "durable_event_contract",
        "outbox_events",
        """WITH normalized AS (
 SELECT *, CASE WHEN jsonb_typeof(payload)='object' THEN payload ELSE '{}'::jsonb END AS p FROM outbox_events)
 SELECT count(*) FROM normalized WHERE NOT coalesce((aggregate_type='transfer' AND event_type='TransferCommitted'
 AND schema_version=1 AND jsonb_typeof(payload)='object' AND p->>'event_id'=id::text
 AND p->>'transfer_id'=aggregate_id::text AND p->'schema_version'='1'::jsonb AND p->>'event_type'='TransferCommitted'
 AND p-ARRAY['event_id','transfer_id','schema_version','event_type','metadata']='{}'::jsonb
 AND jsonb_typeof(p->'metadata')='object'
 AND NOT EXISTS(SELECT 1 FROM jsonb_each(CASE WHEN jsonb_typeof(p->'metadata')='object' THEN p->'metadata' ELSE '{}'::jsonb END) m WHERE jsonb_typeof(m.value)<>'string')),false)""",
    ),
    (
        "committed_outbox",
        "transfers",
        """SELECT count(*) FROM (SELECT t.id FROM transfers t LEFT JOIN outbox_events o ON o.aggregate_id=t.id AND o.aggregate_type='transfer'
 AND o.event_type='TransferCommitted' AND o.schema_version=1 AND o.payload->>'event_id'=o.id::text AND o.payload->>'transfer_id'=t.id::text
 AND o.payload->>'schema_version'='1' AND o.payload->>'event_type'='TransferCommitted' GROUP BY t.id HAVING count(o.id)<>1) q""",
    ),
    (
        "projection_receipts",
        "event_projections",
        """SELECT count(*) FROM (
 SELECT p.event_id FROM event_projections p LEFT JOIN consumer_receipts r ON r.event_id=p.event_id AND r.consumer_name='projection-v1' LEFT JOIN outbox_events o ON o.id=p.event_id
 WHERE r.event_id IS NULL OR o.id IS NULL OR o.aggregate_id<>p.transfer_id OR p.projection_type<>'transfer_notification'
 UNION ALL SELECT r.event_id FROM consumer_receipts r LEFT JOIN event_projections p ON p.event_id=r.event_id WHERE r.consumer_name='projection-v1' AND p.event_id IS NULL
 UNION ALL SELECT event_id FROM event_projections GROUP BY event_id HAVING count(*)>1
 UNION ALL SELECT min(event_id::text)::uuid FROM event_projections GROUP BY transfer_id,projection_type HAVING count(*)>1
 UNION ALL SELECT event_id FROM consumer_receipts GROUP BY consumer_name,event_id HAVING count(*)>1) q""",
    ),
]
