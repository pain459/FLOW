"""Exact Pumba 1.2.1 unfiltered eth0 plans; reject arbitrary exec/shell payloads.

Derived from pkg/tc/netem.go at the pinned Pumba release (Apache-2.0).
Only the validated 150ms delay and owned 504d: cleanup are admitted.
"""

START = """state=$(tc qdisc show dev 'eth0')
if printf '%s\\n' "$state" | grep -Eq '^qdisc (noqueue|fq|fq_codel|pfifo_fast) 0: root'; then
  tc qdisc add dev 'eth0' root handle 504d: netem 'delay' '150ms'
else
  echo 'refusing to replace a foreign or stale root qdisc' >&2
  exit 1
fi
"""
STOP = """state=$(tc qdisc show dev 'eth0')
if [ -z "$state" ] || printf '%s\\n' "$state" | grep -Eq '^qdisc (noqueue|fq|fq_codel|pfifo_fast) 0: root'; then
  exit 0
fi
printf '%s\\n' "$state" | grep -Eq '^qdisc netem 504d: root' || { echo 'refusing to remove a foreign root qdisc' >&2; exit 1; }
tc qdisc del dev 'eth0' root handle 504d:
"""
EXEC_COMMANDS = (["sh", "-ec", START], ["sh", "-ec", STOP])
