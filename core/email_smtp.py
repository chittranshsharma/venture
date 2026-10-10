import os
import smtplib
import ssl
from email.utils import parseaddr
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from core.config_manager import CONFIG
from core.db_manager import log_message
from core.credential_store import get_credential

def send_smtp_email(to_email, subject, body, attachment_path):
    server_addr = CONFIG.get("smtp", {}).get("server", "smtp.gmail.com")
    try:
        port = int(CONFIG.get("smtp", {}).get("port", 587))
    except (ValueError, TypeError) as exc:
        raise ValueError("SMTP port must be a valid integer.") from exc
    from_email = CONFIG.get("smtp", {}).get("email", "")
    password = get_credential("smtp.password", CONFIG.get("smtp", {}).get("password", ""))
    
    if not from_email or not password:
        raise ValueError("SMTP credentials are not configured in settings.")
    if not server_addr or not 1 <= port <= 65535:
        raise ValueError("SMTP host or port is invalid.")
    if any(ch in str(to_email) + str(from_email) + str(subject) for ch in "\r\n"):
        raise ValueError("Email headers cannot contain newlines.")
    if parseaddr(to_email)[1] != to_email or "@" not in to_email:
        raise ValueError("A valid recipient email address is required.")
    if attachment_path and not os.path.isfile(attachment_path):
        raise FileNotFoundError("Requested email attachment does not exist.")
        
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    
    if attachment_path and os.path.exists(attachment_path):
        filename = os.path.basename(attachment_path)
        with open(attachment_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename= {filename}",
            )
            msg.attach(part)
            
    try:
        if port == 465:
            with smtplib.SMTP_SSL(server_addr, port, timeout=30, context=ssl.create_default_context()) as server:
                server.login(from_email, password)
                refused = server.send_message(msg)
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)
        else:
            with smtplib.SMTP(server_addr, port, timeout=30) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(from_email, password)
                refused = server.send_message(msg)
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)
        return True
    except Exception as e:
        log_message(f"Error sending email: {e}")
        raise
