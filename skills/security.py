"""Security skill — port scanning, HTTP headers, whois, SSL checks."""
import socket
import ssl
import urllib.request
import json

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "port_scan",
            "description": "Scan common ports on a host to see which are open.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string"},
                    "ports": {"type": "string", "default": "21,22,23,25,53,80,443,3306,5432,6379,8080,8443", "description": "Comma-separated port numbers"},
                    "timeout": {"type": "number", "default": 1.0},
                },
                "required": ["host"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_headers_check",
            "description": "Check HTTP response headers of a URL for security issues.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ssl_check",
            "description": "Check SSL/TLS certificate info for a hostname.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string"},
                    "port": {"type": "integer", "default": 443},
                },
                "required": ["host"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "whois_lookup",
            "description": "Perform a WHOIS lookup for a domain.",
            "parameters": {
                "type": "object",
                "properties": {"domain": {"type": "string"}},
                "required": ["domain"],
            },
        },
    },
]


def port_scan(host: str, ports: str = "21,22,23,25,53,80,443,3306,5432,6379,8080,8443",
              timeout: float = 1.0) -> str:
    port_list = [int(p.strip()) for p in ports.split(",")]
    open_ports = []
    closed_ports = []
    for port in port_list:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            open_ports.append(port)
        else:
            closed_ports.append(port)
    lines = [f"Port scan: {host}"]
    lines.append(f"OPEN:   {', '.join(str(p) for p in open_ports) or 'none'}")
    lines.append(f"CLOSED: {', '.join(str(p) for p in closed_ports) or 'none'}")
    return "\n".join(lines)


SECURITY_HEADERS = [
    "Strict-Transport-Security", "Content-Security-Policy", "X-Frame-Options",
    "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy", "X-XSS-Protection"
]


def http_headers_check(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KozaAgent/1.0"}, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            headers = dict(resp.headers)
        lines = [f"HTTP Headers check: {url}\n"]
        for h in SECURITY_HEADERS:
            val = headers.get(h) or headers.get(h.lower())
            status = "✅" if val else "❌"
            lines.append(f"{status} {h}: {val or 'MISSING'}")
        # Extra info
        server = headers.get("Server") or headers.get("server", "")
        powered = headers.get("X-Powered-By") or headers.get("x-powered-by", "")
        if server:
            lines.append(f"\nℹ️  Server: {server} (info disclosure)")
        if powered:
            lines.append(f"ℹ️  X-Powered-By: {powered} (info disclosure)")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


def ssl_check(host: str, port: int = 443) -> str:
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=host) as sock:
            sock.settimeout(10)
            sock.connect((host, port))
            cert = sock.getpeercert()
        subject = dict(x[0] for x in cert.get("subject", []))
        issuer = dict(x[0] for x in cert.get("issuer", []))
        not_after = cert.get("notAfter", "")
        not_before = cert.get("notBefore", "")
        sans = [v for _, v in cert.get("subjectAltName", [])]
        return (
            f"SSL Certificate: {host}:{port}\n"
            f"Subject: {subject.get('commonName','')}\n"
            f"Issuer: {issuer.get('organizationName','')}\n"
            f"Valid from: {not_before}\n"
            f"Valid until: {not_after}\n"
            f"SANs: {', '.join(sans[:5])}"
        )
    except ssl.SSLCertVerificationError as e:
        return f"SSL VERIFICATION FAILED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def whois_lookup(domain: str) -> str:
    try:
        import whois
        w = whois.whois(domain)
        return (
            f"Domain: {w.domain_name}\n"
            f"Registrar: {w.registrar}\n"
            f"Created: {w.creation_date}\n"
            f"Expires: {w.expiration_date}\n"
            f"Updated: {w.updated_date}\n"
            f"Name servers: {w.name_servers}"
        )
    except ImportError:
        # Fallback: raw WHOIS socket
        try:
            tld = domain.split(".")[-1]
            whois_server = f"whois.iana.org"
            sock = socket.socket()
            sock.settimeout(10)
            sock.connect((whois_server, 43))
            sock.sendall((domain + "\r\n").encode())
            resp = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resp += chunk
            sock.close()
            return resp.decode("utf-8", errors="replace")[:1000]
        except Exception as e2:
            return f"whois not installed (pip install python-whois). Fallback error: {e2}"
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {
    "port_scan": port_scan,
    "http_headers_check": http_headers_check,
    "ssl_check": ssl_check,
    "whois_lookup": whois_lookup,
}
