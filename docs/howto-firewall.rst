.. nobodd: a boot configuration tool for the Raspberry Pi
..
.. Copyright (c) 2024 Dave Jones <dave.jones@canonical.com>
.. Copyright (c) 2024 Canonical Ltd.
..
.. SPDX-License-Identifier: GPL-3.0

===================================
How to firewall your netboot server
===================================

If you wish to add a netfilter (or iptables) firewall to your server running
nobodd and nbd-server, there are a few things to be aware of.

The `NBD`_ protocol is quite trivial to firewall; the protocol uses TCP and
listens on a single port: 10809. Hence, adding a rule that allows new inbound
TCP connections on port 10809, and a rule to permit traffic on "ESTABLISHED"
connections is generally sufficient.

The `TFTP`_ protocol is, theoretically at least, a little harder. The TFTP
protocol uses UDP (i.e. it's connectionless) and though it starts on the
`privileged port`_ 69, this is only the case for the initial in-bound packet.
All subsequent packets in a transfer take place on an ephemeral port on both
the client *and the server* (transfers are uniquely identified by the tuple of
the client's ephemeral port, and the server's ephemeral port, ensuring a client
may have multiple simultaneous transfers).

Hence, a typical transfer looks like this:

.. image:: images/tftp-basic.*

Thankfully, because the server sends the initial response from its ephemeral
port, and the client replies to that ephemeral port, it will also count as
"ESTABLISHED" traffic in netfilter's parlance. Hence, all that's required to
successfully firewall the TFTP side is to permit inbound packets on port 69,
and to permit "ESTABLISHED" UDP packets.

Putting this altogether, a typical :manpage:`iptables(8)` sequence might look
like this:

.. code-block:: console

    $ sudo -i
    [sudo] Password:
    # iptables -A INPUT -p tcp -m state --state ESTABLISHED -j ACCEPT
    # iptables -A INPUT -p tcp -m state --state NEW --dport 10809 -j ACCEPT
    # iptables -A INPUT -p udp -m state --state ESTABLISHED -j ACCEPT
    # iptables -A INPUT -p udp -m state --state NEW --dport 69 -j ACCEPT

.. _TFTP: https://en.wikipedia.org/wiki/Trivial_File_Transfer_Protocol
.. _NBD: https://en.wikipedia.org/wiki/Network_block_device
.. _privileged port: https://en.wikipedia.org/wiki/List_of_TCP_and_UDP_port_numbers#Well-known_ports
