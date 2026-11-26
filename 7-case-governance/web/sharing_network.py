"""Find local candidate addresses; no external service or outbound probe."""
import ipaddress
import os
import re
import socket
import subprocess


def eligible_address(value):
    try:
        ip=ipaddress.ip_address(value)
        return ip.version==4 and not (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast) and (
            ip.is_private or ip in ipaddress.ip_network('100.64.0.0/10'))
    except ValueError:
        return False


def lan_addresses():
    candidates=set()
    try:
        candidates.update(row[4][0] for row in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET))
    except OSError:
        pass
    if os.name=='nt':
        try:
            result=subprocess.run(['ipconfig'],capture_output=True,text=True,errors='replace',timeout=5,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            candidates.update(re.findall(r'IPv4[^\r\n]*?(\d{1,3}(?:\.\d{1,3}){3})',result.stdout))
        except (OSError,subprocess.TimeoutExpired):
            pass
    return sorted(value for value in candidates if eligible_address(value))
