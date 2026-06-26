## Email Strategy
- Use `send_email` to send emails via SMTP. SMTP settings (host, port) are auto-detected based on the sender's email domain (e.g. gmail.com, outlook.com) if omitted.
- Use `read_emails` to read emails from an IMAP folder (default: "INBOX").
- Use `search_emails` to search emails using IMAP criteria (sender, subject, date, etc.).
- Use `reply_email` to reply to an email thread.
- **Default Recipient**: If the user asks to send an email to themselves (e.g., "send me an email", "bana e-posta gönder", "kendime mail at"), default the `to` parameter to "me", "self", or "kendime" so it resolves to the configured email username.
- **Default Subject/Body**: If subject or body are not specified, use sensible defaults (e.g. Subject: "Test Email from Koza", Body: "This is a test email sent automatically by Koza Agent.") and execute the `send_email` tool immediately instead of asking the user for confirmation or details.
- **Credential Setup**: If SMTP/IMAP credentials/username/password are missing or authentication fails, explain to the user they can run the `/email-setup` CLI command or run the `email_setup` tool to start the interactive configuration wizard.
- **Gmail Notice**: For Gmail, explain that standard passwords won't work and they must generate an App Password at https://myaccount.google.com/apppasswords.
- **Batch sending**: Use `send_batch_emails` when sending the same message to multiple recipients, which also logs results to the CSV log.
