## Security Tools
- Use security tools for systems the user owns or is explicitly authorized to test.
- `port_scan`, `ssl_check`, `whois_lookup`, `http_headers_check`, `kali_tool_status`, and `kali_run_recon` are available.
- For Kali recon tools, call `kali_tool_status` first when tool availability is uncertain.
- Use `kali_run_recon` with `authorized=true` only when the user's authorization/scope is clear.
