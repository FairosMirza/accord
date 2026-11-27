"""Demo organisation and eight months of realistic history.

History is produced by running the real workflow at back-dated times (models.clock_at),
so every approval, audit event, notification and email in the demo is genuine and the
audit hash chain verifies.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import random
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import audit, workflow
from app.audit import ClientInfo
from app.db import SessionLocal, engine
from app.directory import Directory
from app.errors import DomainError
from app.models import (
    Category,
    DemoPersona,
    Department,
    FxRate,
    Invoice,
    PolicyVersion,
    Project,
    RequestStatus,
    Site,
    SpendRequest,
    User,
    clock_at,
    utcnow,
)
from app.policy import DEFAULT_POLICY, PolicyDocument
from app.timeutil import COMPANY_TZ, company_today

log = logging.getLogger(__name__)
CLIENT = ClientInfo(user_agent="Accord demo history")
DOMAIN = "orvane.example"

SITES = [
    ("Dubai (Head office)", "United Arab Emirates", "AED", "Asia/Dubai"),
    ("Accra", "Ghana", "GHS", "Africa/Accra"),
    ("Lima", "Peru", "PEN", "America/Lima"),
    ("Johannesburg", "South Africa", "ZAR", "Africa/Johannesburg"),
]
SITE_KEY = {"Dubai": "Dubai (Head office)", "Accra": "Accra", "Lima": "Lima", "Johannesburg": "Johannesburg"}

DEPARTMENTS = ["Executive Office", "Operations", "Finance", "Technology", "People & Culture", "Commercial", "Internal Audit"]

# key, name, title, department, site, manager, roles
KEY_PEOPLE = [
    ("omar", "Omar Khalil", "Chief Executive Officer", "Executive Office", "Dubai", None, ["executive", "ceo"]),
    ("nadia", "Nadia Frost", "Chief Operating Officer", "Operations", "Dubai", "omar", ["executive", "coo"]),
    ("tom", "Tom Becker", "Head of Finance", "Finance", "Dubai", "omar", ["finance", "finance_admin"]),
    ("hannah", "Hannah Cole", "Head of Commercial", "Commercial", "Dubai", "omar", []),
    ("grace", "Grace Liu", "Internal Audit Manager", "Internal Audit", "Dubai", "omar", ["auditor"]),
    ("aisha", "Aisha Rahman", "Executive Assistant to the CEO", "Executive Office", "Dubai", "omar", []),
    ("daniel", "Daniel Reyes", "Technology Lead", "Technology", "Dubai", "nadia", ["admin"]),
    ("priya", "Priya Nair", "Head of People & Culture", "People & Culture", "Dubai", "nadia", []),
    ("farah", "Farah Haddad", "Operations Manager", "Operations", "Dubai", "nadia", []),
    ("kwame", "Kwame Mensah", "Site Manager, Accra", "Operations", "Accra", "nadia", []),
    ("lucia", "Lucía Paredes", "Site Manager, Lima", "Operations", "Lima", "nadia", []),
    ("thabo", "Thabo Nkosi", "Site Manager, Johannesburg", "Operations", "Johannesburg", "nadia", []),
    ("hse", "Samuel Okafor", "Head of Health, Safety & Environment", "Operations", "Dubai", "nadia", []),
    ("sara", "Sara Lindqvist", "Accounts Payable Lead", "Finance", "Dubai", "tom", ["finance"]),
    ("fpa", "Arjun Iyer", "FP&A Analyst", "Finance", "Dubai", "tom", []),
    ("acct", "Mei Chen", "Financial Accountant", "Finance", "Dubai", "tom", ["finance"]),
    ("payroll", "Yusuf Farouk", "Payroll Specialist", "Finance", "Dubai", "tom", []),
    ("leo", "Leo Park", "Systems Engineer", "Technology", "Dubai", "daniel", []),
    ("rahul", "Rahul Kapoor", "IT Support Lead", "Technology", "Dubai", "daniel", []),
    ("eng", "Elena Petrova", "Software Engineer", "Technology", "Dubai", "daniel", []),
    ("data", "Viktor Novak", "Data Analyst", "Technology", "Dubai", "daniel", []),
    ("itsupport", "Noor Siddiqui", "IT Support Specialist", "Technology", "Dubai", "rahul", []),
    ("hrbp", "Layla Mansour", "HR Business Partner", "People & Culture", "Dubai", "priya", []),
    ("ta", "James O'Connor", "Talent Acquisition Specialist", "People & Culture", "Dubai", "priya", []),
    ("ld", "Hana Sato", "Learning & Development Coordinator", "People & Culture", "Dubai", "priya", []),
    ("lisa", "Lisa Moreau", "Marketing Manager", "Commercial", "Dubai", "hannah", []),
    ("mktexec", "Omar Farooq", "Marketing Executive", "Commercial", "Dubai", "lisa", []),
    ("marco", "Marco Silva", "Business Development Manager", "Commercial", "Dubai", "hannah", []),
    ("bd1", "Daniela Ruiz", "Business Development Executive", "Commercial", "Dubai", "marco", []),
    ("bd2", "Kofi Boateng", "Business Development Executive", "Commercial", "Accra", "marco", []),
    ("analyst", "Sofia Rossi", "Commercial Analyst", "Commercial", "Dubai", "hannah", []),
    ("auditor2", "Ahmed Saleh", "Internal Auditor", "Internal Audit", "Dubai", "grace", ["auditor"]),
    ("procure", "Ravi Menon", "Procurement Lead", "Operations", "Dubai", "farah", []),
    ("office", "Chloe Martin", "Office Administrator", "Operations", "Dubai", "farah", []),
    ("ama", "Ama Owusu", "Procurement Officer", "Operations", "Accra", "kwame", []),
    ("efua", "Efua Asante", "Site Supervisor, Maintenance", "Operations", "Accra", "kwame", []),
    ("yaw", "Yaw Darko", "Site Supervisor, Logistics", "Operations", "Accra", "kwame", []),
    ("akosua", "Akosua Appiah", "HSE Officer", "Operations", "Accra", "kwame", []),
    ("mateo", "Mateo Quispe", "Site Supervisor, Maintenance", "Operations", "Lima", "lucia", []),
    ("valentina", "Valentina Rojas", "Site Supervisor, Logistics", "Operations", "Lima", "lucia", []),
    ("diego", "Diego Huamán", "Procurement Officer", "Operations", "Lima", "lucia", []),
    ("carmen", "Carmen Flores", "HSE Officer", "Operations", "Lima", "lucia", []),
    ("johan", "Johan van der Merwe", "Site Supervisor, Maintenance", "Operations", "Johannesburg", "thabo", []),
    ("naledi", "Naledi Dlamini", "Site Supervisor, Logistics", "Operations", "Johannesburg", "thabo", []),
    ("sipho", "Sipho Ndlovu", "Procurement Officer", "Operations", "Johannesburg", "thabo", []),
    ("lerato", "Lerato Mokoena", "HSE Officer", "Operations", "Johannesburg", "thabo", []),
    ("it_accra", "Kwesi Tetteh", "IT Support Technician", "Technology", "Accra", "daniel", []),
    ("it_lima", "Andrés Castillo", "IT Support Technician", "Technology", "Lima", "daniel", []),
    ("it_jhb", "Pieter Botha", "IT Support Technician", "Technology", "Johannesburg", "daniel", []),
]
DEPARTMENT_HEADS = {
    "Executive Office": "omar",
    "Operations": "nadia",
    "Finance": "tom",
    "Technology": "daniel",
    "People & Culture": "priya",
    "Commercial": "hannah",
    "Internal Audit": "grace",
}

SITE_CREW_NAMES = {
    "Accra": (["Kojo", "Abena", "Kwabena", "Adwoa", "Nana", "Esi", "Fiifi", "Afia", "Kwaku", "Yaa", "Ekow", "Akua", "Kobby", "Maame", "Selorm", "Dzifa", "Edem", "Elikem", "Senyo", "Mawuli"],
              ["Asante", "Boateng", "Osei", "Agyeman", "Ofori", "Addo", "Quaye", "Amoah", "Sarpong", "Frimpong", "Nyarko", "Antwi", "Danso", "Owusu-Ansah", "Bonsu"]),
    "Lima": (["Javier", "Camila", "Luis", "Gabriela", "Jorge", "Sofía", "Andrea", "Ricardo", "Paola", "Miguel", "Rosa", "Carlos", "Milagros", "César", "Fiorella", "Renzo", "Daniela", "Álvaro", "Lucero", "Raúl"],
             ["Mamani", "Torres", "Vargas", "Chávez", "Ramos", "Mendoza", "Gutiérrez", "Salazar", "Espinoza", "Cárdenas", "Ccahuana", "Rivera", "Paucar", "León", "Ortiz"]),
    "Johannesburg": (["Bongani", "Zanele", "Mandla", "Karabo", "Lindiwe", "Tshepo", "Ayanda", "Nomvula", "Themba", "Palesa", "Sibusiso", "Refilwe", "Jaco", "Annelie", "Kagiso", "Thandeka", "Musa", "Busisiwe", "Dumisani", "Mpho"],
                     ["Khumalo", "Pretorius", "Zulu", "Naidoo", "Mahlangu", "Venter", "Molefe", "Sithole", "Nel", "Mthembu", "Coetzee", "Radebe", "Maseko", "du Plessis", "Shabalala"]),
}
CREW_TITLES = ["Maintenance Technician", "Plant Operator", "Logistics Coordinator", "Warehouse Officer", "Driver", "Electrician", "Mechanic", "Operations Assistant", "Stores Clerk", "Fitter", "Site Administrator"]

# name, group, gl code, quote required, confidential by default, description
CATEGORIES = [
    ("Software & subscriptions", "it", "6100", True, False, "SaaS, licences and app subscriptions"),
    ("IT hardware", "it", "6110", True, False, "Laptops, phones, network and server equipment"),
    ("IT services & consulting", "it", "6120", True, False, "Implementation partners, contractors, security testing"),
    ("Telecoms & connectivity", "it", "6130", True, False, "Internet links, mobile plans, satellite"),
    ("Flights", "travel", "6200", True, False, "Air travel for business trips"),
    ("Accommodation", "travel", "6210", True, False, "Hotels and serviced apartments"),
    ("Visas & travel fees", "travel", "6220", False, False, "Government fees, visas, travel insurance"),
    ("Ground transport & per diem", "travel", "6230", False, False, "Taxis, car hire, daily allowances"),
    ("Professional services", "general", "6300", True, False, "Audit, tax, consulting"),
    ("Legal fees", "general", "6310", True, True, "External lawyers. Confidential by default"),
    ("Recruitment", "general", "6320", True, True, "Agencies and executive search. Confidential by default"),
    ("Training & development", "general", "6330", True, False, "Courses, certifications, workshops"),
    ("Marketing & events", "general", "6400", True, False, "Events, conferences, design and print"),
    ("Office & facilities", "general", "6500", True, False, "Furniture, cleaning, utilities, rentals"),
    ("Site equipment & maintenance", "general", "6600", True, False, "Plant, tools, vehicles, repairs at the sites"),
    ("Health & safety", "general", "6610", True, False, "PPE, safety training, inspections"),
    ("Other", "general", "6900", True, False, "Anything that doesn't fit above. Finance will re-categorise"),
]

FX = {  # USD per unit
    "AED": [("2026-01-01", "0.2722900")],
    "GHS": [("2026-01-01", "0.0820"), ("2026-06-01", "0.0865"), ("2026-10-01", "0.0890")],
    "PEN": [("2026-01-01", "0.2660"), ("2026-06-01", "0.2690"), ("2026-10-01", "0.2710")],
    "ZAR": [("2026-01-01", "0.0540"), ("2026-06-01", "0.0556"), ("2026-10-01", "0.0565")],
    "EUR": [("2026-01-01", "1.0800"), ("2026-06-01", "1.1050"), ("2026-10-01", "1.0950")],
    "GBP": [("2026-01-01", "1.2650"), ("2026-06-01", "1.2800"), ("2026-10-01", "1.2700")],
}


@dataclass
class Tpl:
    title: str
    category: str
    supplier: str
    low: float
    high: float
    description: str
    currency: str | None = None  # None: requester's site currency
    recurring: tuple[str, int | None] | None = None
    project: str | None = None
    no_quote: str | None = None


TEMPLATES: dict[str, list[Tpl]] = {
    "tech": [
        Tpl("Figma Professional, 6 seats", "Software & subscriptions", "Figma", 90, 90, "Design tool for the internal apps team.", "USD", ("monthly", 12)),
        Tpl("Replacement laptops for new starters", "IT hardware", "Dell Technologies", 4200, 9600, "Standard spec laptops for joiners this quarter.", "USD"),
        Tpl("Microsoft 365 E3, additional licences", "Software & subscriptions", "Microsoft", 360, 1080, "Licences for new joiners across the sites.", "USD", ("monthly", 12)),
        Tpl("Atlassian Jira and Confluence, annual", "Software & subscriptions", "Atlassian", 5200, 6800, "Annual renewal for the technology team.", "USD"),
        Tpl("Network switches for the site office", "IT hardware", "Cisco partner (Mindware)", 3800, 7200, "Replace end-of-life switches.", "USD", project="PRJ-SITENET"),
        Tpl("Power BI Pro licences", "Software & subscriptions", "Microsoft", 140, 280, "Reporting licences for Finance and Operations.", "USD", ("monthly", 12)),
        Tpl("Monitors and docking stations", "IT hardware", "Jumbo Electronics", 4500, 9800, "Dual monitors for the finance team.", "AED"),
        Tpl("Zoom Rooms licence for the boardroom", "Software & subscriptions", "Zoom", 499, 499, "Annual licence.", "USD"),
        Tpl("Backup storage expansion", "IT hardware", "Synology reseller", 2600, 4800, "Extra capacity for site backups.", "USD", project="PRJ-SITENET"),
        Tpl("Mobile data plans for site supervisors", "Telecoms & connectivity", "Local carrier", 2500, 6000, "Data SIMs for supervisors' tablets.", None, ("monthly", 12)),
    ],
    "finance": [
        Tpl("Tax advisory: transfer pricing review", "Professional services", "PwC Middle East", 18000, 24000, "Required before the January audit.", "USD"),
        Tpl("Expense management software", "Software & subscriptions", "Pleo", 380, 460, "Card expense tool for the sites.", "USD", ("monthly", 12)),
        Tpl("CIMA course for FP&A analyst", "Training & development", "CIMA", 1900, 2600, "Professional qualification.", "USD"),
        Tpl("Payroll bureau fees, Q3", "Professional services", "Deel", 3200, 4100, "Site payroll processing.", "USD"),
    ],
    "people": [
        Tpl("Recruitment agency fee: Site Supervisor", "Recruitment", "Michael Page", 6000, 12000, "Fee on a successful hire.", "USD"),
        Tpl("LinkedIn Recruiter seat", "Software & subscriptions", "LinkedIn", 900, 900, "Recruiter licence for TA.", "USD", ("monthly", 12)),
        Tpl("Leadership training for site managers", "Training & development", "Dale Carnegie", 9000, 14000, "Three-day programme in Dubai.", "USD"),
        Tpl("First aid training, all sites", "Health & safety", "St John Ambulance", 3500, 6200, "Annual refresher for 40 staff.", "USD"),
        Tpl("Employee wellbeing app", "Software & subscriptions", "Headspace for Work", 600, 600, "Annual pilot for head office.", "USD", ("monthly", 12)),
    ],
    "commercial": [
        Tpl("Brochure design and print", "Marketing & events", "Brandmark Studio", 6500, 12000, "Capability brochure, 500 copies.", "AED"),
        Tpl("Client dinner during site tour", "Marketing & events", "Restaurant", 900, 2400, "Hosting two prospective partners.", "USD"),
        Tpl("Trade publication advertising, Q4", "Marketing & events", "Mining Review Africa", 4200, 6800, "Half-page ads in two issues.", "USD"),
        Tpl("Flights for client visit", "Flights", "Emirates", 1400, 3200, "Return economy flights.", "USD"),
        Tpl("Hotel for client visit", "Accommodation", "Marriott", 700, 1900, "Three nights.", "USD"),
        Tpl("Website refresh, phase 1", "Marketing & events", "Northstar Digital", 7500, 11000, "New corporate site design.", "USD"),
    ],
    "ops_hq": [
        Tpl("Office chairs for Dubai head office", "Office & facilities", "Herman Miller (Dubai)", 14000, 26000, "Replace 20 worn chairs.", "AED"),
        Tpl("Legal review: master supply agreement", "Legal fees", "Al Tamimi & Company", 18000, 34000, "Review of the new supply agreement.", "AED"),
        Tpl("Fleet insurance renewal", "Professional services", "AXA Gulf", 9000, 14000, "Annual renewal, 12 vehicles.", "USD"),
        Tpl("Courier account top-up", "Office & facilities", "Aramex", 1500, 3000, "Documents and samples to the sites.", "AED", no_quote="Account top-up at published rates"),
        Tpl("Printer lease", "Office & facilities", "Canon", 1100, 1100, "Head office multifunction printers.", "AED", ("monthly", 24)),
    ],
    "site": [
        Tpl("PPE restock: boots, gloves and helmets", "Health & safety", "Local safety supplier", 0, 0, "Quarterly restock for the crew."),
        Tpl("Generator service and parts", "Site equipment & maintenance", "Power systems contractor", 0, 0, "Scheduled 2,000-hour service."),
        Tpl("Forklift hire", "Site equipment & maintenance", "Plant hire company", 0, 0, "While our own unit is repaired.", recurring=("monthly", 3)),
        Tpl("Vehicle tyres for site pickups", "Site equipment & maintenance", "Tyre centre", 0, 0, "Replace worn tyres on four vehicles."),
        Tpl("Fire extinguisher inspection", "Health & safety", "Fire safety contractor", 0, 0, "Annual statutory inspection.", no_quote="Annual contract rate, no new quote"),
        Tpl("Security guard services", "Office & facilities", "Security services company", 0, 0, "Night security for the yard.", recurring=("monthly", 12)),
        Tpl("Workshop tools", "Site equipment & maintenance", "Tool supplier", 0, 0, "Replace damaged hand and power tools."),
        Tpl("Pump repair", "Site equipment & maintenance", "Pump specialist", 0, 0, "Repair of the dewatering pump."),
        Tpl("Site office internet", "Telecoms & connectivity", "Local ISP", 0, 0, "Business fibre for the site office.", recurring=("monthly", 12), project="PRJ-SITENET"),
        Tpl("Flights to head office for quarterly review", "Flights", "Airline", 0, 0, "Return flights to Dubai.", currency="USD"),
    ],
}
# Typical site spend in USD; converted to the site's currency so amounts look local.
SITE_USD_RANGES = {
    "PPE restock: boots, gloves and helmets": (1800, 6500),
    "Generator service and parts": (1500, 4800),
    "Forklift hire": (900, 1600),
    "Vehicle tyres for site pickups": (1200, 2600),
    "Fire extinguisher inspection": (400, 900),
    "Security guard services": (1100, 2200),
    "Workshop tools": (700, 3800),
    "Pump repair": (2200, 7800),
    "Site office internet": (180, 420),
    "Flights to head office for quarterly review": (900, 1800),
}

REQUESTER_GROUPS = [
    ("site", ["kwame", "lucia", "thabo", "ama", "efua", "yaw", "akosua", "mateo", "valentina", "diego", "carmen", "johan", "naledi", "sipho", "lerato"], 34),
    ("tech", ["daniel", "leo", "eng", "data", "itsupport", "it_accra", "it_lima", "it_jhb"], 20),
    ("commercial", ["hannah", "lisa", "mktexec", "marco", "bd1", "bd2", "analyst"], 14),
    ("ops_hq", ["farah", "procure", "office", "hse"], 10),
    ("finance", ["tom", "sara", "fpa", "acct"], 7),
    ("people", ["priya", "hrbp", "ta", "ld"], 7),
]

REJECTION_COMMENTS = {
    "Not in budget": "Let's revisit when we plan next quarter.",
    "Not needed right now": "We can manage with what we have for now.",
    "Get another quote": "This looks high. Please get two more quotes.",
    "Use an existing tool or supplier": "We already pay for something that does this.",
    "Missing information": "I need to understand who will use this.",
}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _email(name: str, taken: set[str]) -> str:
    base = ".".join(_ascii(p).lower().replace("'", "") for p in name.split() if p)
    email, n = f"{base}@{DOMAIN}", 2
    while email in taken:
        email, n = f"{base}{n}@{DOMAIN}", n + 1
    taken.add(email)
    return email


def make_pdf(lines: list[str]) -> bytes:
    """A small, valid one-page PDF (good enough to stand in for a supplier quote or invoice)."""

    def esc(s: str) -> str:
        return _ascii(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    body = ["BT", "/F1 20 Tf", "60 770 Td", f"({esc(lines[0])}) Tj", "/F1 11 Tf", "18 TL", "T*"]
    body += [f"({esc(line)}) '" for line in lines[1:]]
    body.append("ET")
    content = "\n".join(body)
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class Seeder:
    def __init__(self, db: Session, now: datetime):
        self.db = db
        self.now = now
        self.rng = random.Random(20261126)
        self.u: dict[str, User] = {}
        self.cat: dict[str, Category] = {}
        self.proj: dict[str, Project] = {}
        self.sites: dict[str, Site] = {}
        self.queue: list[tuple[datetime, int, Callable[[], None]]] = []
        self.counter = itertools.count()

    # ------------------------------------------------------------ time helpers

    def local(self, d: date, hour: float) -> datetime:
        h, m = int(hour), int((hour % 1) * 60)
        return datetime.combine(d, time(h, m), tzinfo=COMPANY_TZ).astimezone(UTC)

    def workday_after(self, moment: datetime, hours: float) -> datetime:
        """`hours` of working time (Mon-Fri, 08:00-18:00 Dubai) after `moment`."""
        t = moment.astimezone(COMPANY_TZ)
        remaining = hours
        while remaining > 0:
            if t.weekday() >= 5 or t.hour >= 18:
                t = datetime.combine(t.date() + timedelta(days=1), time(8), tzinfo=COMPANY_TZ)
                continue
            if t.hour < 8:
                t = t.replace(hour=8, minute=0)
            end_of_day = t.replace(hour=18, minute=0)
            available = (end_of_day - t).total_seconds() / 3600
            step = min(available, remaining)
            t += timedelta(hours=step)
            remaining -= step
        return t.astimezone(UTC)

    def random_workday(self, start: date, end: date) -> date:
        while True:
            d = start + timedelta(days=self.rng.randint(0, (end - start).days))
            if d.weekday() < 5:
                return d

    def at(self, moment: datetime, fn: Callable[[], None]) -> None:
        heapq.heappush(self.queue, (moment, next(self.counter), fn))

    # ------------------------------------------------------------ organisation

    def build_org(self) -> None:
        db = self.db
        for name, country, currency, tz in SITES:
            s = Site(name=name, country=country, currency=currency, timezone=tz)
            db.add(s)
            self.sites[name] = s
        depts = {name: Department(name=name) for name in DEPARTMENTS}
        db.add_all(depts.values())
        db.flush()
        taken: set[str] = set()
        for key, name, title, dept, site, _manager, roles in KEY_PEOPLE:
            user = User(email=_email(name, taken), name=name, job_title=title, department_id=depts[dept].id, site_id=self.sites[SITE_KEY[site]].id, roles=roles)
            db.add(user)
            self.u[key] = user
        db.flush()
        for key, *_rest, manager, _roles in KEY_PEOPLE:
            if manager:
                self.u[key].manager_id = self.u[manager].id
        for dept, key in DEPARTMENT_HEADS.items():
            depts[dept].head_id = self.u[key].id
        supervisors = {"Accra": ["efua", "yaw", "akosua"], "Lima": ["mateo", "valentina", "carmen"], "Johannesburg": ["johan", "naledi", "lerato"]}
        for site, (firsts, lasts) in SITE_CREW_NAMES.items():
            names = self.rng.sample([f"{f} {last}" for f in firsts for last in lasts], 24)
            for i, name in enumerate(names):
                db.add(
                    User(
                        email=_email(name, taken),
                        name=name,
                        job_title=CREW_TITLES[i % len(CREW_TITLES)],
                        department_id=depts["Operations"].id,
                        site_id=self.sites[SITE_KEY[site]].id,
                        manager_id=self.u[supervisors[site][i % 3]].id,
                        roles=[],
                    )
                )
        db.flush()

    def reference_data(self, start: datetime) -> None:
        db = self.db
        for i, (name, group, gl, quote, conf, desc) in enumerate(CATEGORIES):
            c = Category(name=name, group=group, gl_code=gl, quote_required=quote, confidential_default=conf, description=desc, sort_order=i)
            db.add(c)
            self.cat[name] = c
        for cur, rows in FX.items():
            for eff, rate in rows:
                db.add(FxRate(currency=cur, usd_per_unit=Decimal(rate), effective_date=date.fromisoformat(eff), source="finance", created_by_id=self.u["tom"].id))
        projects = [
            ("PRJ-FINSYS", "New finance system", "project", "Technology", "daniel", None, date(2026, 3, 1), date(2027, 3, 31), 250000, "Replace the legacy accounting system with a cloud ERP."),
            ("PRJ-SITENET", "Site connectivity upgrade", "project", "Technology", "daniel", None, date(2026, 4, 1), date(2026, 12, 31), 90000, "Reliable internet and networking at all three sites."),
            ("PRJ-CYBER", "Cyber security uplift", "project", "Technology", "daniel", None, date(2026, 5, 1), date(2027, 1, 31), 60000, "Close the gaps from the 2025 security review."),
            ("PRJ-HRIS", "HR system replacement", "project", "People & Culture", "priya", None, date(2026, 9, 1), date(2027, 6, 30), 40000, "One HR system for head office and the sites."),
            ("TRP-INDABA27", "Mining Indaba 2027", "trip", "Commercial", "hannah", "Cape Town, South Africa", date(2027, 2, 8), date(2027, 2, 11), 60000, "Africa's largest mining investment conference. Four of us are going."),
            ("TRP-LIMANOV", "Lima site visit, November", "trip", "Operations", "nadia", "Lima, Peru", date(2026, 11, 30), date(2026, 12, 4), None, "Quarterly site review."),
            ("TRP-OFFSITE", "Leadership offsite, Muscat", "trip", "Executive Office", "omar", "Muscat, Oman", date(2026, 10, 12), date(2026, 10, 14), 30000, "Annual leadership planning offsite."),
            ("TRP-LONDON", "Investor meetings, London", "trip", "Executive Office", "omar", "London, UK", date(2026, 9, 21), date(2026, 9, 24), None, "Meetings with two investors."),
        ]
        for code, name, kind, _dept, owner, dest, sd, ed, budget, desc in projects:
            p = Project(
                code=code, name=name, kind=kind, department_id=self.u[owner].department_id, owner_id=self.u[owner].id, destination=dest,
                start_date=sd, end_date=ed, budget_usd=Decimal(budget) if budget else None, description=desc, created_by_id=self.u[owner].id,
            )
            p.created_at = start
            db.add(p)
            self.proj[code] = p
        db.flush()

    def policies(self, start: datetime) -> None:
        v1 = DEFAULT_POLICY.model_copy(deep=True)
        for rule in v1.rules:
            if rule.key == "coo-travel":
                rule.when.min_total_usd = Decimal(2500)
                rule.label = "COO: travel USD 2,500 or more"
        with clock_at(start):
            pv1 = PolicyVersion(version=1, document=v1.model_dump(mode="json"), change_note="Initial policy from the kickoff call: line manager always, COO for USD 5,000+ and all IT, travel limit from draft matrix", created_by_id=self.u["tom"].id)
            self.db.add(pv1)
            self.db.flush()
            audit.record(self.db, action="policy.updated", summary="Tom Becker published approval policy v1", entity_type="policy", entity_id=1, actor=self.u["tom"], data={"to_version": 1, "document": pv1.document}, client=CLIENT)
        change = self.local(date(2026, 7, 14), 10.5)

        def v2() -> None:
            doc = PolicyDocument.model_validate(DEFAULT_POLICY.model_dump(mode="json"))
            pv2 = PolicyVersion(version=2, document=doc.model_dump(mode="json"), change_note="Draft authority matrix v0.3: travel limit raised to USD 3,000", created_by_id=self.u["tom"].id)
            self.db.add(pv2)
            self.db.flush()
            audit.record(self.db, action="policy.updated", summary="Tom Becker published approval policy v2: travel limit raised to USD 3,000", entity_type="policy", entity_id=2, actor=self.u["tom"], data={"from_version": 1, "to_version": 2, "rules_changed": ["coo-travel"], "document": pv2.document}, client=CLIENT)

        self.at(change, v2)

    # ------------------------------------------------------------ requests

    def fx(self, currency: str, on: date) -> Decimal:
        if currency == "USD":
            return Decimal(1)
        rows = sorted(FX[currency], key=lambda r: r[0])
        rate = rows[0][1]
        for eff, r in rows:
            if date.fromisoformat(eff) <= on:
                rate = r
        return Decimal(rate)

    def nice(self, amount: float, currency: str) -> Decimal:
        step = {"USD": 10, "AED": 50, "EUR": 10, "GBP": 10, "GHS": 50, "PEN": 50, "ZAR": 100}.get(currency, 10)
        if amount < step * 20:
            step = max(1, step // 10)
        return Decimal(max(step, round(amount / step) * step))

    def request(
        self,
        who: str,
        title: str,
        category: str,
        supplier: str,
        amount: Decimal,
        currency: str,
        submitted: datetime,
        *,
        description: str = "",
        project: str | None = None,
        recurring: tuple[str, int | None] | None = None,
        start_date: date | None = None,
        no_quote: str | None = None,
        confidential: bool | None = None,
        needed_by: date | None = None,
    ) -> dict[str, Any]:
        holder: dict[str, Any] = {}
        requester = self.u[who]

        def create() -> None:
            data: dict[str, Any] = {
                "title": title,
                "description": description or f"{title}.",
                "supplier": supplier,
                "category_id": self.cat[category].id,
                "project_id": self.proj[project].id if project else None,
                "currency": currency,
                "amount": amount,
                "needed_by": needed_by,
            }
            if recurring:
                data |= {"payment_type": "recurring", "billing_period": recurring[0], "term_months": recurring[1], "start_date": start_date or (submitted + timedelta(days=14)).date().replace(day=1)}
            if confidential is not None:
                data["is_confidential"] = confidential
            if no_quote:
                data["no_quote_reason"] = no_quote
            req = workflow.create_draft(self.db, requester, data)
            if not no_quote:
                qno = f"Q-{self.rng.randint(10000, 99999)}"
                pdf = make_pdf([f"Quotation {qno}", supplier, f"For: {requester.name}, Orvane Group", "", title, f"Amount: {currency} {amount:,.2f}" + (f" per {recurring[0].rstrip('ly')}" if recurring else ""), "Valid for 30 days.", "", "This is a demo document generated by Accord."])
                workflow.add_attachment(self.db, requester, req, f"Quote {qno} - {_ascii(supplier)}.pdf", pdf, "quote")
            workflow.submit(self.db, requester, req, CLIENT)
            holder["ref"] = req.ref

        self.at(submitted, create)
        holder["submitted"] = submitted
        holder["who"] = who
        return holder

    def get(self, holder: dict[str, Any]) -> SpendRequest | None:
        ref = holder.get("ref")
        if not ref:
            return None
        self.db.flush()
        return self.db.execute(select(SpendRequest).where(SpendRequest.ref == ref)).scalar()

    def decide(self, holder: dict[str, Any], when: datetime, action: str = "approve", *, reason: str | None = None, comment: str | None = None, actor: str | None = None) -> None:
        def run() -> None:
            req = self.get(holder)
            if req is None or req.status != RequestStatus.PENDING or req.pending_step is None:
                return
            step = req.pending_step
            who = self.u[actor] if actor else step.approver
            if actor is None:
                delegates = [d for d in Directory(self.db).active_delegates_for(step.approver_id, company_today()) if d.id != req.requester_id]
                if delegates:
                    who = delegates[0]
            if action == "approve":
                workflow.approve(self.db, who, req, comment, CLIENT)
            elif action == "reject":
                workflow.reject(self.db, who, req, reason or "Not in budget", comment, CLIENT)
            elif action == "return":
                workflow.return_to_requester(self.db, who, req, comment or "Please add more detail.", CLIENT)

        self.at(when, run)

    def approve_all(self, holder: dict[str, Any], start: datetime, *, max_steps: int = 3, fast: bool = False) -> datetime:
        t = start
        for _ in range(max_steps):
            t = self.workday_after(t, self.rng.uniform(0.3, 3) if fast else self.rng.uniform(0.5, 14))
            self.decide(holder, t)
        return t

    def invoice(self, holder: dict[str, Any], when: datetime, *, fraction: float = 1.0, amount: Decimal | None = None, paid_after_days: float | None = None, number: str | None = None, override: str | None = None, with_pdf: bool = True) -> None:
        def run() -> None:
            req = self.get(holder)
            if req is None or req.approved_total_usd is None or req.status not in (RequestStatus.APPROVED, RequestStatus.PENDING):
                return
            finance = self.u["sara"] if req.requester_id != self.u["sara"].id else self.u["tom"]
            per_payment = Decimal(req.amount) if req.payment_type == "recurring" else Decimal(req.approved_total_amount)
            value = amount if amount is not None else (per_payment * Decimal(str(fraction))).quantize(Decimal("0.01"))
            inv_no = number or f"INV-{self.rng.randint(100000, 999999)}"
            pdf = make_pdf([f"Tax invoice {inv_no}", req.supplier or "", "Bill to: Orvane Group", f"Your reference: {req.ref}", "", req.title, f"Total due: {req.currency} {value:,.2f}", "", "This is a demo document generated by Accord."]) if with_pdf else None
            inv = workflow.record_invoice(
                self.db, finance, req, invoice_number=inv_no, invoice_date=utcnow().astimezone(COMPANY_TZ).date() - timedelta(days=self.rng.randint(1, 4)),
                amount=value, currency=req.currency, supplier=req.supplier, notes=None, override_reason=override,
                file=(f"{inv_no}.pdf", pdf) if pdf else None, client=CLIENT,
            )
            if paid_after_days is not None:
                pay_at = self.workday_after(utcnow(), paid_after_days * 10)
                if pay_at < self.now - timedelta(hours=2):
                    inv_id = inv.id

                    def pay() -> None:
                        invoice = self.db.get(Invoice, inv_id)
                        if invoice is not None and invoice.status == "received":
                            payer = self.u["sara"] if invoice.request.requester_id != self.u["sara"].id else self.u["tom"]
                            workflow.mark_paid(self.db, payer, invoice, utcnow().astimezone(COMPANY_TZ).date(), f"PAY-{self.rng.randint(10000, 99999)}", CLIENT)

                    self.at(pay_at, pay)

        self.at(when, run)

    def later(self, holder: dict[str, Any], when: datetime, fn: Callable[[SpendRequest], None]) -> None:
        def run() -> None:
            req = self.get(holder)
            if req is not None:
                fn(req)

        self.at(when, run)

    # ------------------------------------------------------------ history

    def random_history(self, start: date, end: date, count: int) -> None:
        groups = [(g, people) for g, people, weight in REQUESTER_GROUPS for _ in range(weight)]
        for _ in range(count):
            group, people = self.rng.choice(groups)
            who = self.rng.choice(people)
            tpl = self.rng.choice(TEMPLATES[group])
            requester_site = next(name for name, s in self.sites.items() if s.id == self.u[who].site_id)
            site_currency = next(c for n, _, c, _ in SITES if n == requester_site)
            d = self.random_workday(start, end)
            submitted = self.local(d, self.rng.uniform(8.2, 17.5))
            if group == "site":
                low, high = SITE_USD_RANGES[tpl.title]
                currency = tpl.currency or (site_currency if site_currency != "AED" else "USD")
                usd = self.rng.uniform(low, high)
                amount = self.nice(usd / float(self.fx(currency, d)), currency)
                title = f"{tpl.title} ({requester_site.split(' ')[0]})"
            else:
                currency = tpl.currency or site_currency
                amount = self.nice(self.rng.uniform(tpl.low, tpl.high), currency)
                title = tpl.title
            no_quote = tpl.no_quote or (self.rng.choice(["Framework supplier at agreed rates", "Repeat order, price list attached to the framework"]) if self.rng.random() < 0.08 else None)
            h = self.request(who, title, tpl.category, tpl.supplier, amount, currency, submitted, description=tpl.description, project=tpl.project, recurring=tpl.recurring, no_quote=no_quote)
            roll = self.rng.random()
            age_days = (self.now.date() - d).days
            if roll < 0.1:
                reason = self.rng.choice(list(REJECTION_COMMENTS))
                t = self.workday_after(submitted, self.rng.uniform(1, 12))
                if self.rng.random() < 0.5:
                    self.decide(h, t)
                    t = self.workday_after(t, self.rng.uniform(1, 12))
                self.decide(h, t, "reject", reason=reason, comment=REJECTION_COMMENTS[reason] if self.rng.random() < 0.7 else None)
                continue
            if roll < 0.13:
                self.later(h, self.workday_after(submitted, self.rng.uniform(0.5, 6)), lambda r: workflow.withdraw(self.db, r.requester, r, CLIENT) if r.status == RequestStatus.PENDING else None)
                continue
            if roll < 0.18:
                t = self.workday_after(submitted, self.rng.uniform(1, 8))
                self.decide(h, t, "return", comment=self.rng.choice(["Which project is this for?", "Can you attach the updated quote?", "Please split out the delivery cost.", "Is this for the whole team or just the supervisors?"]))
                t = self.workday_after(t, self.rng.uniform(2, 16))
                self.later(h, t, lambda r: self._resubmit(r))
                t = self.approve_all(h, t)
            else:
                t = self.approve_all(h, submitted)
            if self.rng.random() < 0.04:
                self.later(h, self.workday_after(t, 30), lambda r: workflow.cancel(self.db, r.requester, r, "Supplier couldn't deliver in time, so we're not going ahead.", CLIENT) if r.status == RequestStatus.APPROVED and not r.invoices else None)
                continue
            self._invoices_for(h, t, tpl, age_days)

    def _resubmit(self, req: SpendRequest) -> None:
        if req.status != RequestStatus.RETURNED:
            return
        workflow.update_draft(self.db, req.requester, req, {"description": (req.description or "") + " Updated with the details requested."})
        workflow.submit(self.db, req.requester, req, CLIENT)

    def _invoices_for(self, h: dict[str, Any], approved_by: datetime, tpl: Tpl, age_days: int) -> None:
        if tpl.recurring:
            period_days = {"monthly": 30, "quarterly": 91, "annually": 365}[tpl.recurring[0]]
            first = self.workday_after(approved_by, self.rng.uniform(30, 120))
            months = tpl.recurring[1] or 12
            t = first
            for _ in range(min(months, 8)):
                if t > self.now - timedelta(days=1):
                    break
                self.invoice(h, t, paid_after_days=self.rng.uniform(2, 9), with_pdf=self.rng.random() < 0.4)
                t += timedelta(days=period_days)
            return
        t = self.workday_after(approved_by, self.rng.uniform(40, 220))
        if t > self.now - timedelta(days=1):
            return
        if self.rng.random() < 0.2:
            self.invoice(h, t, fraction=0.5, paid_after_days=self.rng.uniform(2, 8), with_pdf=self.rng.random() < 0.5)
            t = self.workday_after(t, self.rng.uniform(60, 200))
            if t < self.now - timedelta(days=1):
                self.invoice(h, t, fraction=0.5, paid_after_days=self.rng.uniform(2, 10), with_pdf=self.rng.random() < 0.5)
        else:
            frac = self.rng.choice([1.0, 1.0, 1.0, 0.98, 0.96, 1.02])
            paid = self.rng.uniform(2, 12) if self.rng.random() < 0.8 else None
            self.invoice(h, t, fraction=frac, paid_after_days=paid, with_pdf=self.rng.random() < 0.5)
            if paid and self.rng.random() < 0.35:
                close_at = self.workday_after(t, paid * 10 + 30)
                if close_at < self.now - timedelta(days=1):
                    self.later(h, close_at, lambda r: workflow.close(self.db, self.u["sara"] if r.requester_id != self.u["sara"].id else self.u["tom"], r, "Delivered and paid in full.", CLIENT) if r.status == RequestStatus.APPROVED and r.invoices and all(i.status == "paid" for i in r.invoices) else None)

    # ------------------------------------------------------------ curated stories

    def stories(self) -> None:
        now = self.now
        today = now.astimezone(COMPANY_TZ).date()
        u = self.u

        def days_ago(n: float, hour: float = 10.0) -> datetime:
            d = today - timedelta(days=int(n))
            while d.weekday() >= 5:
                d -= timedelta(days=1)
            return self.local(d, hour)

        def hours_ago(n: float) -> datetime:
            return now - timedelta(hours=n)

        # Finance system: what has it cost us in total?
        h = self.request("daniel", "Oracle NetSuite licences, 3-year subscription", "Software & subscriptions", "Oracle NetSuite", Decimal("3400"), "USD", self.local(date(2026, 4, 6), 9.5), project="PRJ-FINSYS", recurring=("monthly", 36), start_date=date(2026, 5, 1), description="Core ERP licences for 25 users. Three-year term gives a 22% discount.")
        t = self.approve_all(h, self.local(date(2026, 4, 6), 9.5))
        mt = self.local(date(2026, 5, 4), 11)
        for _ in range(7):
            if mt < now - timedelta(days=2):
                self.invoice(h, mt, paid_after_days=3, with_pdf=False)
            mt += timedelta(days=30)
        for i, (d, amt) in enumerate([(date(2026, 4, 20), "38000"), (date(2026, 6, 15), "42000"), (date(2026, 9, 7), "35500")], start=1):
            h = self.request("daniel", f"Finance system implementation, milestone {i}", "IT services & consulting", "Nexa Consulting", Decimal(amt), "USD", self.local(d, 10), project="PRJ-FINSYS", description=f"Fixed-price milestone {i} from the implementation statement of work.")
            t = self.approve_all(h, self.local(d, 10))
            self.invoice(h, self.workday_after(t, 60), paid_after_days=6)
        h = self.request("leo", "Data migration contractor, 6 weeks", "IT services & consulting", "Kode Partners", Decimal("18400"), "USD", self.local(date(2026, 7, 1), 14), project="PRJ-FINSYS")
        t = self.approve_all(h, self.local(date(2026, 7, 1), 14))
        self.invoice(h, self.workday_after(t, 90), fraction=0.5, paid_after_days=4)
        self.invoice(h, self.workday_after(t, 330), fraction=0.5, paid_after_days=4)

        for who, title, supplier, amt, d in [
            ("leo", "Finance system training for super users", "Nexa Consulting", "5800", date(2026, 8, 25)),
            ("daniel", "Bank integration connector", "Bankingly", "8600", date(2026, 9, 28)),
        ]:
            h = self.request(who, title, "IT services & consulting", supplier, Decimal(amt), "USD", self.local(d, 11), project="PRJ-FINSYS")
            t = self.approve_all(h, self.local(d, 11))
            self.invoice(h, self.workday_after(t, 40), paid_after_days=5)

        # The big recurring one: licences for everyone.
        h = self.request("daniel", "Microsoft 365 E3, 120 licences", "Software & subscriptions", "Microsoft (via Mindware)", Decimal("4560"), "USD", self.local(date(2026, 4, 2), 11), recurring=("monthly", 12), start_date=date(2026, 4, 1), description="Company-wide email, Teams and Office.")
        t = self.approve_all(h, self.local(date(2026, 4, 2), 11), fast=True)
        mt = self.local(date(2026, 4, 28), 10)
        while mt < now - timedelta(days=3):
            self.invoice(h, mt, paid_after_days=2, with_pdf=False)
            mt += timedelta(days=30)

        # A contract coming up for renewal (the reminder job flags it).
        h = self.request("office", "Cleaning contract, Dubai office", "Office & facilities", "Emrill Services", Decimal("6500"), "AED", self.local(date(2026, 3, 30), 12), recurring=("monthly", 9), start_date=date(2026, 3, 1), description="Daily cleaning, nine-month contract.")
        t = self.approve_all(h, self.local(date(2026, 3, 30), 12))
        mt = self.local(date(2026, 4, 25), 10)
        while mt < now - timedelta(days=3):
            self.invoice(h, mt, paid_after_days=4, with_pdf=False)
            mt += timedelta(days=30)

        # Confidential: an executive search.
        h = self.request("priya", "Executive search: Head of Operations, Lima", "Recruitment", "Korn Ferry", Decimal("45000"), "USD", days_ago(34, 9), description="Retained search, fee in three instalments.")
        t = self.approve_all(h, days_ago(34, 9))
        self.invoice(h, self.workday_after(t, 40), amount=Decimal("15000"), paid_after_days=3)

        # Nadia's holiday in August: Omar approves on her behalf.
        def holiday() -> None:
            workflow.create_delegation(self.db, u["nadia"], u["nadia"], u["omar"], date(2026, 8, 10), date(2026, 8, 21), "Annual leave", CLIENT)

        self.at(self.local(date(2026, 8, 6), 16), holiday)
        h = self.request("thabo", "Conveyor belt replacement (Johannesburg)", "Site equipment & maintenance", "Bearing Man Group", Decimal("142000"), "ZAR", self.local(date(2026, 8, 12), 9), description="Main conveyor belt is worn through; replacement before it fails.")
        t = self.approve_all(h, self.local(date(2026, 8, 12), 9))
        self.invoice(h, self.workday_after(t, 80), paid_after_days=5)

        # Mining Indaba: one trip, many requests, several currencies.
        self.trip_story(days_ago, hours_ago)

        # The leadership offsite and the London investor trip, paid in full.
        for who, title, cat, supplier, amt, cur, d, proj in [
            ("aisha", "Leadership offsite venue and rooms, Muscat", "Accommodation", "Alila Jabal Akhdar", "14800", "USD", date(2026, 9, 1), "TRP-OFFSITE"),
            ("aisha", "Flights to Muscat for the leadership team (8)", "Flights", "Oman Air", "6200", "USD", date(2026, 9, 3), "TRP-OFFSITE"),
            ("aisha", "Offsite facilitator", "Professional services", "Kinetic Leadership", "4500", "USD", date(2026, 9, 8), "TRP-OFFSITE"),
            ("omar", "London investor meetings: flights", "Flights", "Emirates", "6900", "USD", date(2026, 8, 31), "TRP-LONDON"),
            ("omar", "London investor meetings: hotel", "Accommodation", "The Ned", "3100", "GBP", date(2026, 8, 31), "TRP-LONDON"),
        ]:
            h = self.request(who, title, cat, supplier, Decimal(amt), cur, self.local(d, 11), project=proj)
            t = self.approve_all(h, self.local(d, 11))
            self.invoice(h, self.workday_after(t, 120), paid_after_days=4, with_pdf=False)
        for who, title, cat, supplier, amt, d in [
            ("rahul", "Endpoint protection renewal (120 devices)", "Software & subscriptions", "CrowdStrike", "9800", date(2026, 6, 2)),
            ("daniel", "Firewall replacement, Dubai office", "IT hardware", "Spectrum (Fortinet)", "11500", date(2026, 7, 20)),
        ]:
            h = self.request(who, title, cat, supplier, Decimal(amt), "USD", self.local(d, 10), project="PRJ-CYBER")
            t = self.approve_all(h, self.local(d, 10))
            self.invoice(h, self.workday_after(t, 60), paid_after_days=5)
        h = self.request("priya", "HR system vendor selection support", "Professional services", "Mercer", Decimal("8500"), "USD", self.local(date(2026, 9, 21), 10), project="PRJ-HRIS", description="Requirements and vendor shortlist for the new HR system.")
        t = self.approve_all(h, self.local(date(2026, 9, 21), 10))
        self.invoice(h, self.workday_after(t, 70), paid_after_days=4)

        # A leaver: Rahul leaves in October; his work moves to Daniel.
        h = self.request("itsupport", "Headsets for the service desk", "IT hardware", "Jabra (via Virgin Megastore)", Decimal("2400"), "AED", self.local(date(2026, 10, 13), 11))

        def leave() -> None:
            workflow.deactivate_user(self.db, u["daniel"], u["rahul"], CLIENT)

        self.at(self.local(date(2026, 10, 15), 17), leave)
        self.approve_all(h, self.local(date(2026, 10, 16), 9))

        # ---- the current state reviewers will see

        # Priya reports to Nadia: line manager and COO approval collapse into one step.
        self.request("priya", "Culture Amp engagement platform, annual", "Software & subscriptions", "Culture Amp", Decimal("12400"), "USD", days_ago(1, 15), project="PRJ-HRIS", description="Engagement surveys for all 120 people, including the sites, so we hear from the crews too.")

        # The original problem: a three-year software contract. Now it can't happen without approval.
        h = self.request("lisa", "HubSpot Marketing Hub, 3-year contract", "Software & subscriptions", "HubSpot", Decimal("800"), "USD", days_ago(3, 11), recurring=("monthly", 36), start_date=(today.replace(day=1) + timedelta(days=40)).replace(day=1), description="CRM and email marketing. Monthly price is fixed for three years if we sign before month end.")
        self.decide(h, days_ago(2, 9.5), comment="Agreed with Lisa, this replaces Mailchimp and the spreadsheets.")

        h = self.request("leo", "Datadog infrastructure monitoring", "Software & subscriptions", "Datadog", Decimal("640"), "USD", hours_ago(30), recurring=("monthly", 12), project="PRJ-CYBER", description="Monitoring and alerting for the new finance system and the site links.")
        self.decide(h, hours_ago(6))

        self.request("daniel", "External penetration test", "IT services & consulting", "Help AG", Decimal("14000"), "USD", hours_ago(26), project="PRJ-CYBER", description="Annual external test, required by our cyber insurance.")

        # CEO's own request goes to the fallback approver (COO).
        self.request("omar", "Strategy advisers for the 2027 plan", "Professional services", "Strategy& Middle East", Decimal("60000"), "USD", hours_ago(3), description="Six-week engagement to shape the 2027-2029 plan with the leadership team.")

        # Tom's scenario: approved for ~5,000, then the quote goes up to ~8,000.
        h = self.request("thabo", "Generator overhaul (Johannesburg)", "Site equipment & maintenance", "Power Systems SA", Decimal("85000"), "ZAR", days_ago(16, 10), description="Overhaul of the 500 kVA standby generator.")
        self.approve_all(h, days_ago(16, 10))
        self.later(
            h,
            hours_ago(20),
            lambda r: workflow.amend(self.db, r.requester, r, {"amount": Decimal("140000")}, "Supplier opened it up and found a cracked cylinder head. Revised quote attached.", CLIENT),
        )

        # Nadia's own trip goes to her manager, Omar.
        self.request("nadia", "Lima site visit: flights and hotel", "Flights", "LATAM Airlines", Decimal("4600"), "USD", hours_ago(28), project="TRP-LIMANOV", description="Business class flights Dubai-Lima and four nights near the site.")

        # Kwame has something from his team waiting.
        self.request("efua", "Safety harnesses and lanyards (Accra)", "Health & safety", "Safety Plus Ghana", Decimal("14500"), "GHS", hours_ago(4), description="Replace 12 harnesses that failed inspection.")

        # Ama's request was sent back for a quote.
        h = self.request("ama", "Water dispenser rental (Accra)", "Office & facilities", "Voltic", Decimal("450"), "GHS", days_ago(2, 9), recurring=("monthly", 12), no_quote="Small monthly rental")
        self.decide(h, days_ago(1, 11), "return", comment="Please attach the supplier's quote. Even small rentals need one for the auditors.")

        # Rejected, with a reason.
        h = self.request("bd1", "Team offsite in Bali", "Accommodation", "Ayana Resort", Decimal("18500"), "USD", days_ago(6, 12), description="Three-day offsite for the commercial team.")
        self.decide(h, days_ago(5, 10))
        self.decide(h, days_ago(4, 18), "reject", reason="Not in budget", comment="Let's do something closer to home in Q1.")

        # A laptop order where the invoice came in above the approval.
        h = self.request("leo", "Laptops for three new engineers", "IT hardware", "Dell Technologies", Decimal("7200"), "USD", days_ago(24, 10))
        t = self.approve_all(h, days_ago(24, 10), fast=True)
        self.invoice(h, days_ago(3, 12), amount=Decimal("7950"), override="Dell added a 3-year ProSupport warranty that Daniel agreed with them by email. It wasn't in the approved quote.", number="DELL-AE-558120")

        # A supplier billing error: Finance queries it and waits for a corrected invoice.
        h = self.request("yaw", "Forklift service and parts (Accra)", "Site equipment & maintenance", "Mantrac Ghana", Decimal("52000"), "GHS", days_ago(13, 9), description="6,000-hour service on the Cat forklift, with filters and hydraulic hoses.")
        self.approve_all(h, days_ago(13, 9))
        self.invoice(h, days_ago(2, 11), amount=Decimal("61400"), override="GHS 9,400 above the approval. The filter kit appears twice (lines 4 and 9).", number="MG-24117")
        self.later(
            h,
            days_ago(1, 10),
            lambda r: workflow.query_invoice(self.db, u["sara"], r.invoices[-1], "Filter kit billed twice (lines 4 and 9). Asked Mantrac for a corrected invoice.", CLIENT),
        )

        # Withdrawn by the requester.
        h = self.request("analyst", "Market data subscription", "Software & subscriptions", "S&P Global", Decimal("9600"), "USD", days_ago(9, 10))
        self.later(h, days_ago(8, 15), lambda r: workflow.withdraw(self.db, r.requester, r, CLIENT) if r.status == RequestStatus.PENDING else None)

        # Hannah is on leave for two weeks; Marco covers her approvals (but not his own requests).
        def cover() -> None:
            workflow.create_delegation(self.db, u["hannah"], u["hannah"], u["marco"], today - timedelta(days=1), today + timedelta(days=13), "Annual leave. Marco covers Commercial approvals", CLIENT)

        self.at(days_ago(2, 17), cover)
        self.request("lisa", "Mining Indaba stand design and build", "Marketing & events", "Expo Concepts SA", Decimal("9800"), "USD", hours_ago(5), project="TRP-INDABA27", description="Design, build and freight for our 3x6m stand.")

        # Nadia's December travel: Omar is set up to cover.
        def december() -> None:
            start = (today.replace(day=1) + timedelta(days=32)).replace(day=6)
            workflow.create_delegation(self.db, u["nadia"], u["nadia"], u["omar"], start, start + timedelta(days=14), "Travelling for half of the month. Omar covers my approvals.", CLIENT)

        self.at(days_ago(1, 18), december)

        # A draft Nadia hasn't submitted yet.
        def draft() -> None:
            workflow.create_draft(self.db, u["nadia"], {"title": "Board dinner, December", "category_id": self.cat["Marketing & events"].id, "currency": "AED", "amount": Decimal("7500"), "supplier": "Zuma Dubai"})

        self.at(hours_ago(2), draft)

    def trip_story(self, days_ago: Callable[..., datetime], hours_ago: Callable[[float], datetime]) -> None:
        u = self.u
        base = days_ago(40, 10)
        h = self.request("hannah", "Mining Indaba 2027: exhibitor package", "Marketing & events", "Hyve Events (Mining Indaba)", Decimal("24000"), "USD", base, project="TRP-INDABA27", description="Exhibitor package incl. 4 delegate passes.")
        t = self.approve_all(h, base)
        self.invoice(h, self.workday_after(t, 50), fraction=0.5, paid_after_days=3)
        for who, cur, amt, supplier, delay in [("hannah", "USD", "2380", "Emirates", 30), ("marco", "USD", "2150", "Emirates", 26), ("kwame", "GHS", "27500", "South African Airways", 22), ("thabo", "ZAR", "6200", "FlySafair", 20)]:
            h = self.request(who, f"Flights to Cape Town for Mining Indaba ({u[who].name.split()[0]})", "Flights", supplier, Decimal(amt), cur, days_ago(delay, 11), project="TRP-INDABA27", description="Return flights for the conference week.")
            t = self.approve_all(h, days_ago(delay, 11))
            if delay > 21:
                self.invoice(h, self.workday_after(t, 20), paid_after_days=2, with_pdf=False)
        h = self.request("marco", "Hotel in Cape Town, 4 rooms x 4 nights", "Accommodation", "Southern Sun Cape Sun", Decimal("68000"), "ZAR", days_ago(18, 15), project="TRP-INDABA27", description="Group booking near the CTICC.")
        self.approve_all(h, days_ago(18, 15))
        h = self.request("marco", "South Africa visa fee", "Visas & travel fees", "VFS Global", Decimal("75"), "USD", days_ago(12, 10), project="TRP-INDABA27", no_quote="Fixed government fee, there is no quote for a visa")
        self.approve_all(h, days_ago(12, 10), fast=True)
        h = self.request("marco", "Ground transport in Cape Town", "Ground transport & per diem", "Uber for Business", Decimal("600"), "USD", hours_ago(7), project="TRP-INDABA27", no_quote="Estimated taxi costs for the week")

    # ------------------------------------------------------------ run

    def run(self) -> None:
        start = (self.now - timedelta(days=240)).astimezone(COMPANY_TZ).date().replace(day=1)
        start_dt = self.local(start - timedelta(days=3), 9)
        with clock_at(start_dt):
            self.build_org()
            self.reference_data(start_dt)
            for user in self.u.values():
                user.created_at = start_dt
            self.policies(start_dt)
        self.db.commit()
        self.random_history(start, self.now.astimezone(COMPANY_TZ).date() - timedelta(days=12), 115)
        self.stories()
        done = 0
        # Actions can schedule follow-ups (e.g. paying an invoice later), so process in time order.
        while self.queue:
            moment, _, fn = heapq.heappop(self.queue)
            if moment > self.now:
                continue
            with clock_at(moment):
                try:
                    with self.db.begin_nested():
                        fn()
                except DomainError as exc:
                    log.warning("Demo history step skipped: %s", exc.message)
            done += 1
            if done % 50 == 0:
                self.db.commit()
        self.db.commit()
        cutoff = self.now - timedelta(days=2)
        self.db.execute(text("UPDATE notifications SET read_at = created_at + interval '2 hours' WHERE created_at < :cutoff"), {"cutoff": cutoff})
        self.personas()
        self.db.commit()

    def personas(self) -> None:
        # Blurbs describe rules, not current state: reviewers share one demo, so anything "waiting" may already be done.
        p = [
            ("nadia", "COO. Approves big spend and all IT", "Start here. See why each request needs your approval, and the whole picture across the group."),
            ("tom", "Head of Finance. Sees everything approved, owns the rules", "Track approved, invoiced and paid spend, and see who owns the next step when an invoice is above its approval. Change limits, categories and exchange rates without a developer."),
            ("priya", "Head of People & Culture, reports to Nadia", "Start an IT request: \u201cWho will approve\u201d shows Nadia once, as both your manager and COO."),
            ("marco", "Business Development Manager, covering for Hannah", "While Hannah is on leave her approvals come to Marco. His own requests still go to her, never to himself."),
            ("daniel", "Technology Lead and Accord administrator", "Approves his team's requests. Manages people, managers and roles, including leavers."),
            ("kwame", "Site Manager, Accra", "Approves his site team's spend in Ghana cedi, with the US dollar equivalent alongside."),
            ("ama", "Procurement Officer, Accra", "Raises site purchases in local currency. Approvers can send a request back for changes instead of rejecting it."),
            ("leo", "Systems Engineer", "Raises software and hardware requests. All IT goes to Nadia after Daniel. If an invoice comes in above his approval, Accord asks him to review the difference."),
            ("sara", "Accounts Payable Lead", "Records invoices against approvals and releases payments. Queries wrong invoices with the supplier. Can't pay her own requests."),
            ("hannah", "Head of Commercial (on leave)", "Sees all Commercial spend. On leave, so Marco is covering her approvals."),
            ("omar", "CEO", "Approves Nadia's own requests, and covers her approvals while she travels."),
            ("grace", "Internal Audit Manager (read-only)", "Every request and the tamper-evident audit trail, ready for January."),
        ]
        for i, (key, headline, blurb) in enumerate(p):
            self.db.add(DemoPersona(user_id=self.u[key].id, sort_order=i, headline=headline, blurb=blurb))


def seed(db: Session, now: datetime | None = None) -> None:
    Seeder(db, now or datetime.now(UTC)).run()


def _wipe_schema() -> None:
    """Drop everything, including the append-only audit log, and recreate the schema."""
    from app.main import run_migrations

    with engine.begin() as conn:
        # Never hang behind another session's locks: fail fast instead.
        conn.execute(text("SET LOCAL lock_timeout = '20s'"))
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    run_migrations()


def seed_if_empty() -> bool:
    # Several instances can boot at once against an empty database; only one may seed it.
    with engine.connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(724004)"))
        lock.commit()
        try:
            with SessionLocal() as db:
                people = db.execute(select(func.count(User.id))).scalar()
                complete = db.execute(select(func.count()).select_from(DemoPersona)).scalar()
            if people and complete:
                return False
            if people:
                # Personas are written last, so their absence means an earlier seed was interrupted.
                log.warning("Demo data is incomplete; rebuilding it")
                _wipe_schema()
            with SessionLocal() as db:
                log.info("Seeding demo data")
                seed(db)
                log.info("Demo data ready")
            return True
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(724004)"))
            lock.commit()


def reset_demo() -> None:
    """Wipe everything and re-seed. Demo mode only."""
    _wipe_schema()
    seed_if_empty()


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if "--reset" in sys.argv:
        reset_demo()
    else:
        print("seeded" if seed_if_empty() else "database already has data; use --reset")
