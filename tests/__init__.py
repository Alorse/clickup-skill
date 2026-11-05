"""Offline tests: prohibit non-loopback connections AND network DNS resolution."""
import ipaddress
import socket

_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex
_getaddrinfo = socket.getaddrinfo


class NetworkForbidden(BaseException):
    """Not caught by the CLI's Exception handler: accidental networking fails tests."""


def _loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _guard(original):
    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address[0]):
            raise NetworkForbidden("non-loopback network connection forbidden")
        return original(sock, address)
    return connect


def _resolve(host, *args, **kwargs):
    # No DNS queries for external names, even before connect() is reached.
    if host == "localhost":
        host = "127.0.0.1"
    if not _loopback(host):
        raise NetworkForbidden("non-loopback name resolution forbidden")
    return _getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _guard(_connect)
socket.socket.connect_ex = _guard(_connect_ex)
socket.getaddrinfo = _resolve
