import sys
from pathlib import Path
from dotenv import load_dotenv

_root = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(_root))
load_dotenv(_root / ".env")

from router.router import get_routing_intent, DOMAIN_CALENDAR, DOMAIN_CONTACTS, DOMAIN_DOCUMENTS, DOMAIN_TUITION
from router.calendar_router import route_query as calendar_route_query
from search.contacts_search import contacts_rrf_search
from search.documents_search import documents_rrf_search
from search.tuition_search import tuition_rrf_search


def print_calendar_hits(hits):
    sources = []
    score = max((h.get("_score") or 0.0 for h in hits), default=0.0)
    print(f"\n[CALENDAR] Top score: {score:.4f} | Hits: {len(hits)}\n")
    for h in hits:
        s = h["_source"]
        start = s.get("start_date") or "N/A"
        end   = s.get("end_date")   or "N/A"
        print(f"  {start if start == end else f'{start} → {end}'} | {s.get('event_name') or 'N/A'}")
        for url in (s.get("source_urls") or ([s.get("source_url")] if s.get("source_url") else [])):
            u = (url or "").strip()
            if u and u not in sources:
                sources.append(u)
    if sources:
        print("\nSources:")
        for u in sources:
            print(f"  - {u}")
    print()


def print_contacts_hits(hits):
    sources = []
    score = max((h.get("_score") or 0.0 for h in hits), default=0.0)
    print(f"\n[CONTACTS] Top score: {score:.4f} | Hits: {len(hits)}\n")
    for h in hits:
        s = h["_source"]
        print(f"[{s.get('category','').upper()}] {s.get('name','N/A')}")
        print(f"Department: {s.get('department','N/A')}")
        for field in ("description", "phone", "fax", "email", "building", "address"):
            if s.get(field):
                print(f"{field.capitalize()}: {s[field]}")
        url = s.get("source_url")
        if url and url not in sources:
            sources.append(url)
        print()
    if sources:
        print("\nSources:")
        for u in sources:
            print(f"  - {u}")
    print()


def print_tuition_hits(hits):
    sources = []
    score = max((h.get("_score") or 0.0 for h in hits), default=0.0)
    print(f"\n[TUITION] Top score: {score:.4f} | Hits: {len(hits)}\n")
    for h in hits:
        s = h["_source"]
        print(f"[{s.get('school','').upper()}] {s.get('level','N/A')}")
        for label, key in [("Section", "section"), ("Fee", "fee_name"), ("Year", "academic_year"),
                           ("Term", "term"), ("Enrollment", "enrollment"), ("Program", "program"),
                           ("Unit", "unit"), ("Amount", "amount_value")]:
            print(f"{label}: {s.get(key, 'N/A')}")
        if s.get("content"):
            print(f"Content: {s['content']}")
        url = s.get("source_url")
        if url and url not in sources:
            sources.append(url)
        print()
    if sources:
        print("\nSources:")
        for u in sources:
            print(f"  - {u}")
    print()


def print_documents_hits(hits):
    sources = []
    score = max((h.get("_score") or 0.0 for h in hits), default=0.0)
    print(f"\n[DOCUMENTS] Top score: {score:.4f} | Hits: {len(hits)}\n")
    for h in hits:
        s = h["_source"]
        print(f"[{s.get('doc_type','').upper()}] {s.get('doc_name','N/A')}")
        print(f"Topic: {s.get('topic','N/A')}")
        print(f"Page {s.get('page_start','?')}-{s.get('page_end','?')}")
        if s.get("content"):
            print(f"Content: {s['content']}")
        url = s.get("source_url")
        if url and url not in sources:
            sources.append(url)
        print()
    if sources:
        print("\nSources:")
        for u in sources:
            print(f"  - {u}")
    print()


_PRINTERS = {
    DOMAIN_CALENDAR:  print_calendar_hits,
    DOMAIN_CONTACTS:  print_contacts_hits,
    DOMAIN_TUITION:   print_tuition_hits,
    DOMAIN_DOCUMENTS: print_documents_hits,
}

_SEARCHERS = {
    DOMAIN_CALENDAR:  calendar_route_query,
    DOMAIN_CONTACTS:  contacts_rrf_search,
    DOMAIN_TUITION:   tuition_rrf_search,
    DOMAIN_DOCUMENTS: documents_rrf_search,
}


def main():
    print("Combined Search CLI\n")
    while True:
        try:
            query = input("Query: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query or query.lower() == "quit":
            break

        try:
            intent = get_routing_intent(query)
            domains = intent.get("domains", [])
            if not domains:
                print("\nRouter could not confidently determine a domain.\n")
                continue

            print(f"\nRouter → {', '.join(domains)}")

            all_hits: dict = {}
            all_clarifications: dict = {}
            for domain in domains:
                if domain not in _SEARCHERS:
                    continue
                result = _SEARCHERS[domain](query)
                if isinstance(result, dict) and result.get("needs_clarification"):
                    all_clarifications[domain] = result
                elif result:
                    all_hits[domain] = result

            # Show clarification only when no domain returned results.
            if not all_hits:
                if all_clarifications:
                    first = next(iter(all_clarifications.values()))
                    print("\nClarification needed:")
                    print(first["message"])
                    if first.get("options"):
                        print("Options: " + ", ".join(first["options"][:10]))
                else:
                    print("\nNo results found.\n")
                continue

            for domain, hits in all_hits.items():
                _PRINTERS[domain](hits)

        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()
