#!/usr/bin/env python

#
# Copyright (c) 2019 by VMware, Inc. ("VMware")
# Used Copyright (c) 2018 by Network Device Education Foundation, Inc.
# ("NetDEF") in this file.
#
# Permission to use, copy, modify, and/or distribute this software
# for any purpose with or without fee is hereby granted, provided
# that the above copyright notice and this permission notice appear
# in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND VMWARE DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL VMWARE BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY
# DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
# WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS
# ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE
# OF THIS SOFTWARE.
#


"""RFC5549 Automation."""
import os
import sys
import time
import json
import pytest
import random
import ipaddr
from re import search as re_search

# Save the Current Working Directory to find configuration files.
CWD = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(CWD, "../"))
sys.path.append(os.path.join(CWD, "../../"))

# pylint: disable=C0413
# Import topogen and topotest helpers
from lib.topogen import Topogen, get_topogen
from mininet.topo import Topo

from lib.common_config import (
    start_topology,
    write_test_header,
    write_test_footer,
    create_route_maps,
    verify_rib,
    create_static_routes,
    check_address_types,
    reset_config_on_routers,
    step,
    shutdown_bringup_interface,
    create_interfaces_cfg,
    get_frr_ipv6_linklocal,
)
from lib.topolog import logger
from lib.bgp import (
    clear_bgp_and_verify,
    verify_bgp_convergence,
    create_router_bgp,
    verify_bgp_rib,
)
from lib.topojson import build_topo_from_json, build_config_from_json

# Global variables
topo = None
# Reading the data from JSON File for topology creation
jsonFile = "{}/rfc5549_ibgp_ecmp.json".format(CWD)
try:
    with open(jsonFile, "r") as topoJson:
        topo = json.load(topoJson)
except IOError:
    assert False, "Could not read file {}".format(jsonFile)

# Global variables
NO_OF_RTES = 2
NETWORK_CMD_IP = "1.0.1.17/32"
NETWORK = {
    "ipv4": [
        "11.0.20.1/32",
        "11.0.20.2/32",
        "11.0.20.3/32",
        "11.0.20.4/32",
        "11.0.20.5/32",
    ],
    "ipv6": ["1::1/128", "1::2/128", "1::3/128", "1::4/128", "1::5/128"],
}
MASK = {"ipv4": "32", "ipv6": "128"}
NEXT_HOP = {
    "ipv4": ["10.0.0.1", "10.0.1.1", "10.0.2.1", "10.0.3.1", "10.0.4.1"],
    "ipv6": ["Null0", "Null0", "Null0", "Null0", "Null0"],
}
INTF_LIST = [
    "r2-link0",
    "r2-link1",
    "r2-link2",
    "r2-link3",
    "r2-link4",
    "r2-link5",
    "r2-link6",
    "r2-link7",
]
ADDR_TYPES = check_address_types()
TOPOOLOGY = """
      Please view in a fixed-width font such as Courier.

                                      +----+
                                      | R4 |
                                      |    |
                                      +--+-+
                                         | ipv4 nbr
          no bgp           ebgp/ibgp     |
                                         |     ebgp/ibgp
    +----+ 5links   +----+  8links    +--+-+             +----+
    |R0  +----------+ R1 +------------+ R2 |    ipv6 nbr |R3  |
    |    +----------+    +------------+    +-------------+    |
    +----+          +----+   ipv6 nbr +----+             +----+
"""

TESTCASES = """
1. Verify IPv4 routes advertised when 8 ECMP IBGP session configured
 between peers
2. Verify IPv4 routes are installed with correct nexthop after clearing
 the BGP session
 """


class CreateTopo(Topo):
    """
    Test topology builder.

    * `Topo`: Topology object
    """

    def build(self, *_args, **_opts):
        """Build function."""
        tgen = get_topogen(self)

        # Building topology from json file
        build_topo_from_json(tgen, topo)


def setup_module(mod):
    """Set up the pytest environment."""

    global topo
    testsuite_run_time = time.asctime(time.localtime(time.time()))
    logger.info("Testsuite start time: {}".format(testsuite_run_time))
    logger.info("=" * 40)

    logger.info("Running setup_module to create topology")

    # This function initiates the topology build with Topogen...
    tgen = Topogen(CreateTopo, mod.__name__)

    # Starting topology, create tmp files which are loaded to routers
    #  to start deamons and then start routers
    start_topology(tgen)

    # Creating configuration from JSON
    build_config_from_json(tgen, topo)
    # Don't run this test if we have any failure.
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    BGP_CONVERGENCE = verify_bgp_convergence(tgen, topo)
    assert BGP_CONVERGENCE is True, "setup_module :Failed \n Error:" " {}".format(
        BGP_CONVERGENCE
    )
    logger.info("Running setup_module() done")


def teardown_module():
    """Teardown the pytest environment."""
    logger.info("Running teardown_module to delete topology")

    tgen = get_topogen()

    # Stop toplogy and Remove tmp files
    tgen.stop_topology()


def get_llip(onrouter, intf):
    """
    API to get the link local ipv6 address of a perticular interface

    Parameters
    ----------
    * `fromnode`: Source node
    * `tonode` : interface for which link local ip needs to be returned.

    Usage
    -----
    result = get_llip('r1', 'r2-link0')

    Returns
    -------
    1) link local ipv6 address from the interface.
    2) errormsg - when link local ip not found.
    """

    tgen = get_topogen()
    intf = topo["routers"][onrouter]["links"][intf]["interface"]
    llip = get_frr_ipv6_linklocal(tgen, onrouter, intf)

    if llip:
        logger.info("llip ipv6 address to be set as NH is %s", llip)
        return llip
    return None


def get_glipv6(onrouter, intf):
    """
    API to get the global ipv6 address of a perticular interface

    Parameters
    ----------
    * `onrouter`: Source node
    * `intf` : interface for which link local ip needs to be returned.

    Usage
    -----
    result = get_glipv6('r1', 'r2-link0')

    Returns
    -------
    1) global ipv6 address from the interface.
    2) errormsg - when link local ip not found.
    """
    glipv6 = (topo["routers"][onrouter]["links"][intf]["ipv6"]).split("/")[0]
    if glipv6:
        logger.info("Global ipv6 address to be set as NH is %s", glipv6)
        return glipv6
    return None


# ##################################
# Test cases start here.
# ##################################


def test_rfc4459_clear_bgp_p1(request):
    """
    Verify extended capability next hop with clear bgp.

    Verify IPv4 routes are installed with correct
    nexthop after clearing the BGP session
    """
    tc_name = request.node.name
    write_test_header(tc_name)
    tgen = get_topogen()
    # Don't run this test if we have any failure.
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)
    reset_config_on_routers(tgen)

    step(
        "Configure 8 IPv6 IBGP ECMP session between"
        " R1 and R2 with global IPv6 address"
    )
    step("Enable capability extended-nexthop on the" " neighbor from both the routers")
    step("Activate same ipv6 nbr from ipv4 unicast family")

    step("Verify bgp convergence as ipv6 nbr is enabled on ipv4 addr family.")
    bgp_convergence = verify_bgp_convergence(tgen, topo)
    assert bgp_convergence is True, "Testcase {} : Failed \n" " Error: {}".format(
        tc_name, bgp_convergence
    )

    step(" Configure 5 IPv4 static" " routes on R1, Nexthop as different links of R0")

    for addr_type in ["ipv4"]:
        for rte in range(0, NO_OF_RTES):
            # Create Static routes
            input_dict = {
                "r1": {
                    "static_routes": [
                        {
                            "network": NETWORK[addr_type][rte],
                            "no_of_ip": 1,
                            "next_hop": NEXT_HOP[addr_type][rte],
                        }
                    ]
                }
            }
            result = create_static_routes(tgen, input_dict)
            assert result is True, "Testcase {} : Failed \n Error: {}".format(
                tc_name, result
            )

    step(
        "Advertise static routes from IPv4 unicast family and IPv6 "
        "unicast family respectively from R1 using red static cmd "
        "Advertise loopback from IPv4 unicast family using network command "
        "from R1"
    )

    configure_bgp_on_r1 = {
        "r1": {
            "bgp": {
                "address_family": {
                    "ipv4": {
                        "unicast": {
                            "redistribute": [{"redist_type": "static"}],
                            "advertise_networks": [
                                {"network": NETWORK_CMD_IP, "no_of_network": 1}
                            ],
                        }
                    }
                }
            }
        }
    }
    result = create_router_bgp(tgen, topo, configure_bgp_on_r1)
    assert result is True, "Testcase {} : Failed \n Error: {}".format(tc_name, result)

    step("configure max-ecmp path 8")

    configure_bgp_on_r1 = {
        "r1": {
            "bgp": {
                "address_family": {
                    "ipv4": {"unicast": {"maximum_paths": {"ibgp": 8}}},
                    "ipv6": {"unicast": {"maximum_paths": {"ibgp": 8}}},
                }
            }
        }
    }
    result = create_router_bgp(tgen, topo, configure_bgp_on_r1)
    assert result is True, "Testcase {} : Failed \n Error: {}".format(tc_name, result)

    configure_bgp_on_r2 = {
        "r2": {
            "bgp": {
                "address_family": {
                    "ipv4": {"unicast": {"maximum_paths": {"ibgp": 8}}},
                    "ipv6": {"unicast": {"maximum_paths": {"ibgp": 8}}},
                }
            }
        }
    }
    result = create_router_bgp(tgen, topo, configure_bgp_on_r2)
    assert result is True, "Testcase {} : Failed \n Error: {}".format(tc_name, result)
    step(
        "verify that IPv4 routes present with 8 global "
        "addresses in BGP table and in RIB"
    )

    llip = []
    for lnk in INTF_LIST:
        llip.append(get_llip("r1", lnk))
    assert llip is not [], "Testcase {} : Failed \n Error: {}".format(tc_name, result)

    dut = "r2"
    protocol = "bgp"
    # verify the routes with nh as ext_nh
    verify_nh_for_static_rtes = {
        "r1": {
            "static_routes": [
                {
                    "network": NETWORK["ipv4"][0],
                    "no_of_ip": NO_OF_RTES,
                    "next_hop": llip,
                }
            ]
        }
    }
    bgp_rib = verify_bgp_rib(
        tgen, "ipv4", dut, verify_nh_for_static_rtes, next_hop=llip
    )
    assert bgp_rib is True, "Testcase {} : Failed \n Error: {}".format(tc_name, bgp_rib)
    result = verify_rib(
        tgen, "ipv4", dut, verify_nh_for_static_rtes, next_hop=llip, protocol=protocol
    )
    assert result is True, "Testcase {} : Failed \n Error: {}".format(tc_name, result)

    step("Clear bgp neighbors on r2")
    # Clear bgp
    result = clear_bgp_and_verify(tgen, topo, dut)
    assert result is True, "Testcase {} : Failed \n Error: {}".format(tc_name, result)

    step(
        "verify that IPv4 routes present with 8 global "
        "addresses in BGP table and in RIB"
    )
    step("Nexthop address on R2 should be R1 address(R1 to R2 connected link)")
    step("IPv4 routes are re-learn on R2 after clearing the BGP session")
    step("Verify show ip bgp show ip route for IPv4 routes")

    llip = []
    for lnk in INTF_LIST:
        llip.append(get_llip("r1", lnk))
    assert llip is not [], "Testcase {} : Failed \n Error: {}".format(tc_name, result)

    verify_nh_for_static_rtes = {
        "r1": {
            "static_routes": [
                {
                    "network": NETWORK["ipv4"][0],
                    "no_of_ip": NO_OF_RTES,
                    "next_hop": llip,
                }
            ]
        }
    }
    bgp_rib = verify_bgp_rib(
        tgen, "ipv4", dut, verify_nh_for_static_rtes, next_hop=llip
    )
    assert bgp_rib is True, "Testcase {} : Failed \n Error: {}".format(tc_name, bgp_rib)
    result = verify_rib(
        tgen, "ipv4", dut, verify_nh_for_static_rtes, next_hop=llip, protocol=protocol
    )
    assert result is True, "Testcase {} : Failed \n Error: {}".format(tc_name, result)
    write_test_footer(tc_name)


if __name__ == "__main__":
    args = ["-s"] + sys.argv[1:]
    sys.exit(pytest.main(args))
