import smtplib
from email.message import EmailMessage
from html import escape


def send_email(subject: str, jobs: list[dict], from_addr: str, to_addr: str, app_password: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(_text_body(jobs))
    msg.add_alternative(_html_body(jobs), subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(from_addr, app_password.replace(" ", ""))
        s.send_message(msg)


def _text_body(jobs: list[dict]) -> str:
    n = len(jobs)
    lines = [f"{n} new job{'s' if n != 1 else ''} matching your filter:", ""]
    for j in jobs:
        lines.append(f"- [{j['company']}] {j['role']}")
        lines.append(f"  Location: {j['location']}")
        lines.append(f"  Posted: {j['days_old']}d ago  |  Source: {j.get('source','')}")
        lines.append(f"  Apply: {j['url']}")
        lines.append("")
    return "\n".join(lines)


def _html_body(jobs: list[dict]) -> str:
    rows = []
    for j in jobs:
        rows.append(f"""
        <tr>
          <td style="padding:10px 8px;border-bottom:1px solid #eee;vertical-align:top;"><strong>{escape(j['company'])}</strong></td>
          <td style="padding:10px 8px;border-bottom:1px solid #eee;vertical-align:top;">{escape(j['role'])}</td>
          <td style="padding:10px 8px;border-bottom:1px solid #eee;vertical-align:top;color:#555;">{escape(j['location'])}</td>
          <td style="padding:10px 8px;border-bottom:1px solid #eee;vertical-align:top;color:#888;white-space:nowrap;">{j['days_old']}d ago</td>
          <td style="padding:10px 8px;border-bottom:1px solid #eee;vertical-align:top;"><a href="{escape(j['url'])}" style="color:#1a73e8;text-decoration:none;font-weight:600;">Apply &rarr;</a></td>
        </tr>""")
    n = len(jobs)
    return f"""<!doctype html><html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:920px;margin:0 auto;padding:16px;">
    <h2 style="margin:0 0 16px 0;">{n} new NG job{'s' if n != 1 else ''} matching your filter</h2>
    <table style="border-collapse:collapse;width:100%;font-size:14px;">
      <thead><tr style="background:#f5f5f5;text-align:left;">
        <th style="padding:10px 8px;">Company</th>
        <th style="padding:10px 8px;">Role</th>
        <th style="padding:10px 8px;">Location</th>
        <th style="padding:10px 8px;">Posted</th>
        <th style="padding:10px 8px;">Link</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <p style="color:#888;font-size:12px;margin-top:24px;">job-radar via GitHub Actions. Edit config.yml in the repo to tune keywords / locations.</p>
    </body></html>"""
