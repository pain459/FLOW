from load_generator.controller.resources import network_counters


def test_linux_network_counters_exclude_loopback_and_reject_invalid_input():
    text = "Inter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets\n lo: 999 1 0 0 0 0 0 0 999 1 0 0 0 0 0 0\n eth0: 120 2 0 0 0 0 0 0 240 2 0 0 0 0 0 0\n eth1: 10 1 0 0 0 0 0 0 20 1 0 0 0 0 0 0"
    assert network_counters(text) == {"network_received_bytes": 130, "network_sent_bytes": 260}
    assert network_counters("unavailable") == {
        "network_received_bytes": None,
        "network_sent_bytes": None,
    }
