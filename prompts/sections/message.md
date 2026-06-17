## Messaging Strategy
- Use `twilio_send_sms` to send an SMS via Twilio.
- Use `twilio_send_whatsapp` to send a WhatsApp message via Twilio.
- Use `twilio_make_call` to make a phone call via Twilio.
- Use `discord_send` to send a message to a Discord webhook or channel.
- Use `whatsapp_send` to send a WhatsApp message.
- Use `telegram_send` to send a Telegram message to a specific chat ID.
- Check active credential status in the system prompt. If credentials/tokens are missing for a messaging service, guide the user on how to set them.
