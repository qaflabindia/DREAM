"""Usage: python -m dreamlab.cli --db ./dream.db demo | dream | recall ..."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .engine import DreamEngine, Event
from .llm import OllamaProposer


def show(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="DREAM-Lab reproducible offline memory prototype")
    parser.add_argument("--db", default="./dreamlab.sqlite", help="SQLite file path")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Store an explicit-consent structured experience")
    ingest.add_argument("--tenant", required=True)
    ingest.add_argument("--subject", required=True)
    ingest.add_argument("--predicate", required=True)
    ingest.add_argument("--value", required=True)
    ingest.add_argument("--source-id", required=True)
    ingest.add_argument("--kind", choices=["observation", "feedback", "outcome", "correction"], default="observation")
    ingest.add_argument("--trust", choices=["untrusted", "observed", "self_report", "validated"], default="observed")
    ingest.add_argument("--sensitivity", choices=["public", "private", "restricted"], default="public")
    ingest.add_argument("--importance", type=float, default=0.5)
    ingest.add_argument("--payload", default="{}", help="JSON object")
    ingest.add_argument("--consent", action="store_true", help="Assert permission to store this event")

    dream = sub.add_parser("dream", help="Consolidate and test counterfactuals")
    dream.add_argument("--tenant", required=True)
    dream.add_argument("--max-events", type=int, default=256)
    dream.add_argument("--max-keys", type=int, default=64)

    recall = sub.add_parser("recall", help="Evidence-based retrieval")
    recall.add_argument("--tenant", required=True)
    recall.add_argument("--query", required=True)
    recall.add_argument("--clearance", choices=["public", "private", "restricted"], default="public")
    recall.add_argument("--limit", type=int, default=5)

    listing = sub.add_parser("memories", help="Inspect promoted and contested entries")
    listing.add_argument("--tenant", required=True)
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--clearance", choices=["public", "private", "restricted"], default="public")

    audit = sub.add_parser("audit", help="Inspect decisions and experiments")
    audit.add_argument("--tenant", required=True)

    purge = sub.add_parser("purge", help="Delete tenant data and audit history")
    purge.add_argument("--tenant", required=True)
    purge.add_argument("--confirm", action="store_true", help="Explicitly confirm destructive operation")

    propose = sub.add_parser("propose", help="Opt-in local model creates untested hypotheses")
    propose.add_argument("--tenant", required=True)
    propose.add_argument("--model", required=True, help="Installed Ollama model name")
    propose.add_argument("--endpoint", default="http://127.0.0.1:11434/api/generate")
    propose.add_argument("--clearance", choices=["public", "private", "restricted"], default="public")
    propose.add_argument("--local-model-consent", action="store_true")

    hypotheses = sub.add_parser("hypotheses", help="Inspect non-promoted model ideas")
    hypotheses.add_argument("--tenant", required=True)

    sub.add_parser("demo", help="Load synthetic events and execute a dream")

    args = parser.parse_args()
    with DreamEngine(Path(args.db)) as engine:
        if args.command == "ingest":
            payload = json.loads(args.payload)
            if not isinstance(payload, dict):
                parser.error("--payload must be a JSON object")
            event_id = engine.ingest(Event(
                tenant=args.tenant, subject=args.subject, predicate=args.predicate,
                value=args.value, source_id=args.source_id, kind=args.kind,
                trust=args.trust, sensitivity=args.sensitivity,
                importance=args.importance, payload=payload, consent=args.consent))
            show({"event_id": event_id})
        elif args.command == "dream":
            show(engine.dream(args.tenant, max_events=args.max_events, max_keys=args.max_keys))
        elif args.command == "recall":
            show(engine.recall(args.tenant, args.query, clearance=args.clearance, limit=args.limit))
        elif args.command == "memories":
            show(engine.memories(args.tenant, include_inactive=args.all, clearance=args.clearance))
        elif args.command == "audit":
            show(engine.get_audit(args.tenant))
        elif args.command == "propose":
            proposer = OllamaProposer(args.model, args.endpoint)
            show(engine.generate_hypotheses(args.tenant, proposer,
                consent_to_local_model=args.local_model_consent,
                clearance=args.clearance, model_name=args.model))
        elif args.command == "hypotheses":
            show(engine.hypotheses(args.tenant))
        elif args.command == "purge":
            if not args.confirm:
                parser.error("purge requires --confirm")
            engine.purge_tenant(args.tenant)
            show({"deleted_tenant": args.tenant, "warning": "SQLite deletion is not a secure disk wipe"})
        elif args.command == "demo":
            tenant = "synthetic-demo"
            examples = [
                Event(tenant, "ledger", "reconciliation_mode", "manual", "demo:first", trust="observed", importance=0.7, consent=True),
                Event(tenant, "ledger", "reconciliation_mode", "automated", "demo:second", trust="observed", importance=0.7, consent=True),
                Event(tenant, "reporting", "currency", "INR", "demo:verified", trust="validated", importance=0.8, consent=True),
                Event(tenant, "decimal_sum", "attempt", "binary_float failed exactness", "demo:test-run", kind="outcome", trust="observed", importance=0.99, payload={"scenario":"decimal_sum", "action":"binary_float"}, consent=True),
                Event(tenant, "owner", "communication_preference", "concise examples", "demo:user", trust="self_report", importance=0.5, consent=True),
            ]
            for event in examples:
                engine.ingest(event)
            outcome = engine.dream(tenant)
            show({"dream": outcome, "memories": engine.memories(tenant, include_inactive=True, clearance="restricted"),
                  "recall": engine.recall(tenant, "decimal_sum action policy")})


if __name__ == "__main__":
    main()
