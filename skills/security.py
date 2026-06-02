"""Security skill — port scanning, HTTP headers, whois, SSL checks."""
import platform
import shlex
import shutil
import socket
import ssl
import subprocess
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
    {
        "type": "function",
        "function": {
            "name": "kali_tool_status",
            "description": "Check whether common Kali/pentest reconnaissance tools are installed and show example usage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tools": {
                        "type": "string",
                        "default": "",
                        "description": "Comma-separated tool names. Defaults to a curated recon list.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kali_run_recon",
            "description": (
                "Run an allowlisted Kali-style reconnaissance tool against an authorized target. "
                "Requires authorized=true and does not support exploit/password attack frameworks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "description": "One of: nmap, whatweb, nikto, sslscan, testssl, wafw00f, nuclei, subfinder, httpx, dnsx, gobuster",
                    },
                    "target": {"type": "string", "description": "Authorized host, domain, URL, or target pattern required by the selected tool"},
                    "args": {"type": "string", "default": "", "description": "Additional CLI arguments. Parsed safely without a shell."},
                    "authorized": {"type": "boolean", "default": False, "description": "Must be true to confirm the user owns or is authorized to test the target."},
                    "timeout": {"type": "integer", "default": 120, "description": "Command timeout in seconds"},
                },
                "required": ["tool", "target", "authorized"],
            },
        },
    },
]


_KALI_RECON_TOOLS = {
    "nmap": {
        "default_args": ["-sV", "-Pn"],
        "example": "kali_run_recon(tool='nmap', target='example.com', args='-sV -Pn -p 80,443', authorized=true)",
    },
    "whatweb": {
        "default_args": [],
        "example": "kali_run_recon(tool='whatweb', target='https://example.com', authorized=true)",
    },
    "nikto": {
        "prefix": ["-host"],
        "default_args": [],
        "example": "kali_run_recon(tool='nikto', target='https://example.com', authorized=true)",
    },
    "sslscan": {
        "default_args": [],
        "example": "kali_run_recon(tool='sslscan', target='example.com:443', authorized=true)",
    },
    "testssl": {
        "default_args": [],
        "example": "kali_run_recon(tool='testssl', target='https://example.com', authorized=true)",
    },
    "wafw00f": {
        "default_args": [],
        "example": "kali_run_recon(tool='wafw00f', target='https://example.com', authorized=true)",
    },
    "nuclei": {
        "prefix": ["-target"],
        "default_args": ["-severity", "info,low,medium"],
        "example": "kali_run_recon(tool='nuclei', target='https://example.com', args='-severity info,low,medium', authorized=true)",
    },
    "subfinder": {
        "prefix": ["-d"],
        "default_args": [],
        "example": "kali_run_recon(tool='subfinder', target='example.com', authorized=true)",
    },
    "httpx": {
        "prefix": ["-u"],
        "default_args": [],
        "example": "kali_run_recon(tool='httpx', target='https://example.com', authorized=true)",
    },
    "dnsx": {
        "prefix": ["-d"],
        "default_args": [],
        "example": "kali_run_recon(tool='dnsx', target='example.com', authorized=true)",
    },
    "gobuster": {
        "prefix": ["dir", "-u"],
        "default_args": ["-w", "/usr/share/wordlists/dirb/common.txt"],
        "example": "kali_run_recon(tool='gobuster', target='https://example.com', args='-w /usr/share/wordlists/dirb/common.txt', authorized=true)",
    },
}

_BLOCKED_ARG_PATTERNS = (
    ";", "&&", "||", "|", "`", "$(", ">", "<", "\n", "\r",
    "--exec", "--script-help",
)


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


def _split_args(args: str) -> list[str]:
    if not args:
        return []
    if any(pattern in args for pattern in _BLOCKED_ARG_PATTERNS):
        raise ValueError("Potentially unsafe shell/control argument detected.")
    return shlex.split(args, posix=(platform.system() != "Windows"))


def _validate_target(target: str) -> str:
    target = (target or "").strip()
    if not target:
        raise ValueError("Target is required.")
    if any(pattern in target for pattern in _BLOCKED_ARG_PATTERNS) or any(ch.isspace() for ch in target):
        raise ValueError("Target contains unsafe characters.")
    return target


def kali_tool_status(tools: str = "") -> str:
    requested = [t.strip().lower() for t in tools.split(",") if t.strip()]
    names = requested or sorted(_KALI_RECON_TOOLS)
    lines = ["Kali / pentest recon tool status:"]
    for name in names:
        if name not in _KALI_RECON_TOOLS:
            lines.append(f"- {name}: unsupported by kali_run_recon")
            continue
        path = shutil.which(name)
        state = "installed" if path else "not found"
        example = _KALI_RECON_TOOLS[name]["example"]
        lines.append(f"- {name}: {state}{f' ({path})' if path else ''}\n  example: {example}")
    return "\n".join(lines)


def kali_run_recon(tool: str, target: str, args: str = "", authorized: bool = False,
                   timeout: int = 120) -> str:
    tool_name = (tool or "").strip().lower()
    if not authorized:
        return (
            "ERROR: authorized=true is required. Only run this against systems "
            "you own or have explicit permission to test."
        )
    if tool_name not in _KALI_RECON_TOOLS:
        return (
            f"ERROR: Unsupported tool '{tool}'. Allowed tools: "
            + ", ".join(sorted(_KALI_RECON_TOOLS))
        )
    executable = shutil.which(tool_name)
    if not executable:
        return f"ERROR: {tool_name} is not installed or not on PATH.\n\n{kali_tool_status(tool_name)}"

    try:
        clean_target = _validate_target(target)
        extra_args = _split_args(args)
        spec = _KALI_RECON_TOOLS[tool_name]
        command = [executable]
        command.extend(spec.get("prefix", []))
        command.append(clean_target)
        command.extend(extra_args or spec.get("default_args", []))
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout)),
        )
        output = []
        output.append(f"Command: {' '.join(command)}")
        if result.stdout.strip():
            output.append(result.stdout.strip())
        if result.stderr.strip():
            output.append(f"STDERR:\n{result.stderr.strip()}")
        output.append(f"Exit code: {result.returncode}")
        return "\n".join(output)
    except subprocess.TimeoutExpired:
        return f"ERROR: {tool_name} timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {
    "port_scan": port_scan,
    "http_headers_check": http_headers_check,
    "ssl_check": ssl_check,
    "whois_lookup": whois_lookup,
    "kali_tool_status": kali_tool_status,
    "kali_run_recon": kali_run_recon,
}
