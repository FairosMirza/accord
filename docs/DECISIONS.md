# Decisions and assumptions

The kickoff call was the only specification. This is every decision I made where nobody made it for me: what I assumed, why, and how to change it. Items marked **(asked)** are in my email to Nadia. When she or Tom reply, the setting changes, not the code.

## Approvals

| Decision | Why | How to change |
| --- | --- | --- |
| Line manager approves everything first | "By their line manager" | Approval rules |
| COO approves all IT spend, whatever the amount | "IT always… even the small ones". Daniel played it back as "you approve the big ones and IT" | Approval rules |
| COO approves general spend from USD 5,000 and travel from USD 3,000 **(asked)** | Tom: "I think it's 5000… it's different for travel". The travel figure is a placeholder until his authority matrix arrives | Approval rules (versioned) |
| Limits are measured in USD on the **full commitment**, not the monthly price | The incident that started this was a three-year contract. Judging it by the monthly fee would let it through | Rolling contracts use 12 months (setting) |
| Steps are sequential: the COO sees it after the line manager | The manager filters first, so fewer things reach Nadia | Rule order |
| The same person never gets two steps | Nadia: "I'm not clicking twice". Their step shows every reason they're approving for | Not configurable (a rule of the engine) |
| Nobody approves their own spend. It goes to their manager | Basic segregation of duties. It's also why Nadia's own requests go to the CEO **(asked)** | – |
| When no one is eligible (the CEO's own requests), the COO approves **(asked)** | Someone has to. The fallback is a setting | Approval rules → settings |
| Rules point at positions (COO, CEO), not at people | People change roles. The rules shouldn't break when they do | People → roles |
| Requests already in approval keep the route they started with | Changing rules mid-flight would confuse approvers and auditors. Each request records its rules version | – |
| Finance is told about approvals but doesn't approve | Tom wants to see what's approved, not add a step. A Finance step is one rule away if he wants one | Approval rules |
| Approve, reject (with a reason) or send back for changes | Tom: a reason stops people resubmitting. Nadia: "sometimes I just want to say no", so a reason is one tap from a short list | Rejection reasons are a setting |

## Cover while away

| Decision | Why |
| --- | --- |
| The approver sets a stand-in for set dates (up to three months). They can still approve themselves | "It can't all just stop" |
| "Not just anyone": stand-ins for the COO or CEO must hold an approved role (CEO, Finance lead) **(asked)**. Other managers' stand-ins must be managers themselves | So authority stays with people who have it |
| Everything a stand-in does is recorded as "X on behalf of Y" | Auditors need both names |
| A stand-in can't approve their own requests, or add a second approval to a request they already approve | Covering mustn't let one person approve twice |
| Administrators can set cover for someone who forgot | Nadia boarding a flight |

## Visibility

| Decision | Why |
| --- | --- |
| Everyone sees their own requests and anything they approve. Managers see their reporting line, and department heads their department | "The heads should see their own" |
| Executives, Finance, auditors and administrators see everything | They need the whole picture |
| A **Confidential** flag (default on for legal and recruitment) limits a request to the requester, the approvers and those roles | "Some of it is sensitive" |
| Reports and dashboards add up only what you can see | Totals that can't be reconciled to visible requests would leak confidential amounts **(asked: company-wide totals for everyone?)** |
| Drafts are private until submitted, and aren't in the audit log | Thinking out loud isn't a record. Submission is |

## Money

| Decision | Why | How to change |
| --- | --- | --- |
| USD is the reporting currency. Requests and invoices can be in any currency | "Most of it is in dollars, but the sites pay in local" | – |
| Finance-maintained exchange rates with effective dates. Each request keeps the rate it was approved at | Accounting uses agreed rates, not live market feeds. It also keeps approvals stable | Exchange rates page |
| Amendments: up to 5% more is recorded and Finance is told. More than that, or a change that needs a new approver, goes back for approval. The original approval stands until it's decided **(asked)** | Tom: "quotes do change". Without a tolerance, every shipping fee would need re-approval | Approval rules → tolerance |
| Invoices above the approved amount plus tolerance need an override reason, which is recorded | The control Tom actually needs at payment time | Same tolerance |
| Duplicate invoice numbers from the same supplier are blocked | A cheap guard against paying twice | – |
| Recurring costs are approved once for the term. Finance logs each invoice against it, and a renewal reminder goes out 30 days before it ends **(asked)** | Tom's open question. Re-raising every month would be noise, but auto-renewals can't slip through | Renewal notice is a setting |
| Each request has a reference (AC-1234) that suppliers should quote on invoices | Makes matching invoices to approvals reliable, by hand now and with AI later | – |

## Notifications

| Decision | Why |
| --- | --- |
| Email to the approver (and any stand-in) with a link straight to the request, plus an in-app bell | "E-mail or Teams… as long as they can't say they didn't see it" |
| Reminders each working day (Monday to Friday, Dubai time) after 24 hours | Persistence without spamming weekends |
| Accord records when each email was sent and when the approver first opened the request | "Can't say they didn't see it" is something we can actually check |
| Approve links open the app rather than approving from the email | One-click links get triggered by email scanners and forwarded. On a phone, signing in and approving takes two taps |
| Teams is a next step (Microsoft Graph or a Teams app) | Email works on day one. Teams needs an app registration in Orvane's tenant |

## Platform

| Decision | Why |
| --- | --- |
| Microsoft Entra ID single sign-on (OIDC). No Accord passwords | "Don't give me another password". Teams suggests Microsoft 365 **(asked)** |
| The demo uses one-click personas behind `ACCORD_DEMO_MODE`, which refuses to start in production | Reviewers need to be different people. The flag is a hard switch, not a hidden page |
| Python and FastAPI with Postgres, all in one container | Small and boring to run. Relational data suits approvals, reporting and audit |
| Google Cloud Run (Frankfurt), Neon Postgres (Frankfurt), Cloud Storage, Secret Manager | Free tiers, managed, close to Dubai. For production I'd ask Orvane IT where they host, and if they're Azure-first the container moves to Azure Container Apps unchanged |
| Append-only, hash-chained audit log, with a database trigger that blocks changes | "It needs to stand up to the auditors". Tampering is detectable, not just discouraged |
| Leavers: deactivating someone moves their pending approvals and direct reports to their manager | "People leave and join every month". In production the directory sync does this |

## Left out (for now) and why

- **Reading invoices with AI.** Daniel: "I'd do it later". The data model is ready: invoices are separate records with files attached, and requests have references suppliers can quote.
- **Directory sync from Entra ID (Microsoft Graph).** It needs Orvane's tenant. Until then an administrator manages people, managers and roles in the app, and first-time sign-ins are added automatically.
- **Teams notifications.** As above.
- **Budgets per department.** Not asked for. Projects and trips have optional budgets.
- **Accounting system integration.** Unknown system. There's a CSV export for now.
- **Split-purchase detection** (two $4,000 requests to dodge a $5,000 limit). A good next control. Auditors ask about it.
