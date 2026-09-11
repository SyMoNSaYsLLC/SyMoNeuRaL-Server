# Example environment — mail identities

**Placeholders only. Every secret value below is deliberately blank and stays blank in this
repository.** `.gitignore:161` ignores `.env`; this file is the tracked example beside it.

Identity policy — which mailbox is allowed to do what — lives in
`ops/docs/SYMONEURAL-EMAIL-IDENTITY-POLICY.md`. This file only records the variable names.

> **Setting these does not enable mail.** There is no mail sender on this box
> (`backend/apps/accounts/__init__.py:457`, verified: no sendmail, no MTA unit, no mail
> client). These names exist so that when sending is built, the identities are already decided
> and nothing has to be guessed at implementation time.

## Mailbox identities

```dotenv
SYMONEURAL_ADMIN_EMAIL=symonsayadmin@symoneural.com
SYMONEURAL_NOREPLY_EMAIL=saynoreply@symoneural.com
SYMONEURAL_ALERT_EMAIL=sayalert@symoneural.com
SYMONEURAL_SUPPORT_EMAIL=saysupport@symoneural.com
SYMONEURAL_RECOVERY_EMAIL=garrettmcdonald87@gmail.com
```

## Future SMTP transport — names only, values blank

```dotenv
SMTP_HOST=
SMTP_PORT=
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_NOREPLY=saynoreply@symoneural.com
SMTP_FROM_ALERT=sayalert@symoneural.com
SMTP_REPLY_TO_SUPPORT=saysupport@symoneural.com
```

`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME` and `SMTP_PASSWORD` are left empty on purpose. A
hostname is not a secret, but a hostname committed beside a username is half a credential and
an invitation to complete the set — so the transport block stays empty here and is filled in
only in the untracked `.env`.

**Never commit:** an app password, a provider API token, an OAuth client secret, a mailbox
password, or any generated credential. If one reaches a commit, it is burned — rotate it at
the provider rather than deleting the line and hoping.

## Which address sends what

The short version; the full table and the routing rules are in the policy file.

| Purpose | Address |
|---|---|
| Public contact, support, preview CTA | `SYMONEURAL_SUPPORT_EMAIL` |
| Automated outbound (`From`) | `SYMONEURAL_NOREPLY_EMAIL` |
| Automated outbound (`Reply-To`, when replies matter) | `SYMONEURAL_SUPPORT_EMAIL` |
| Internal alerts, failures, monitoring (destination) | `SYMONEURAL_ALERT_EMAIL` |
| Admin and control-plane notices | `SYMONEURAL_ADMIN_EMAIL` |
| Personal recovery only — never product-facing | `SYMONEURAL_RECOVERY_EMAIL` |
