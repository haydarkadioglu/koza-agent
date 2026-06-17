## Email Strategy
- Use `send_email` to send emails via SMTP. SMTP settings (host, port) are auto-detected based on the sender's email domain if omitted.
- Use `read_emails` to read emails from an IMAP folder (default: "INBOX").
- Use `search_emails` to search emails using IMAP criteria (sender, subject, date, etc.).
- Use `reply_email` to reply to an email thread.
- If SMTP/IMAP credentials/username/password are missing, prompt the user to configure them or explain how to generate App Passwords (especially for Gmail).
