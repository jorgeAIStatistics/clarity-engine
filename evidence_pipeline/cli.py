"""python -m evidence_pipeline.cli --help"""

import argparse
import json
from datetime import date
from pathlib import Path
from .common import PipelineError
from .config import Settings
from .state import State
from .retrieval.europe_pmc import Target, EuropePMC
from .extraction.providers import StructuredProvider
from .extraction.service import Extractor
from .graph.ingestion import Neo4jIngestor
from .runner import Pipeline


def main(argv=None):
    parser = argparse.ArgumentParser(description="Clarity structured evidence pipeline")
    parser.add_argument("command", choices=["retrieve", "run", "graph-init", "status"])
    parser.add_argument(
        "--targets", default=str(Path(__file__).with_name("targets.example.json"))
    )
    parser.add_argument("--since", type=date.fromisoformat)
    parser.add_argument("--until", type=date.fromisoformat)
    parser.add_argument("--with-graph", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    state = State(settings.state_path)
    retriever = provider = driver = None
    try:
        if args.command == "status":
            print(
                json.dumps(
                    {
                        "runs": state.all("run")[-10:],
                        "candidates": len(state.all("candidate")),
                        "validated_extractions": len(state.all("extraction")),
                        "jobs": state.all("job"),
                    }
                )
            )
            return
        if args.command == "graph-init" or args.with_graph:
            driver = settings.graph()
            driver.verify_connectivity()
            graph = Neo4jIngestor(driver, settings.neo4j_database)
            if args.command == "graph-init":
                graph.initialize()
                print('{"status":"graph_constraints_initialized"}')
                return
        else:
            graph = None
        config = json.loads(Path(args.targets).read_text())
        targets = [Target.model_validate(t) for t in config["targets"]]
        retriever = EuropePMC()
        if args.command == "run":
            provider = StructuredProvider(
                settings.provider, settings.model, settings.api_key
            )
            extractor = Extractor(provider, state, settings.daily_calls)
        else:
            extractor = None
        result = Pipeline(state, retriever, extractor, graph, settings.run_calls).run(
            targets,
            args.since,
            args.until,
            config.get("graph_bindings", []),
            retrieval_only=args.command == "retrieve",
        )
        print(json.dumps(result))
        if result["status"] != "completed":
            raise SystemExit(1)
    except PipelineError as error:
        print(json.dumps({"error": str(error)}))
        raise SystemExit(1)
    except Exception as error:
        print(json.dumps({"error": type(error).__name__}))
        raise SystemExit(1)
    finally:
        if driver:
            driver.close()
        if provider:
            provider.close()
        if retriever:
            retriever.close()
        state.close()


if __name__ == "__main__":
    main()
