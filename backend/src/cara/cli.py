"""The `cara` command line: accounts, datasets, encoding, studies, pilots and the simulator.

Run it where CARA is installed; with Docker, `docker compose exec backend cara ...`.
"""

import argparse
import getpass
import logging
import os
from pathlib import Path

from cara.db.models import Role
from cara.db.session import make_sessions
from cara.repositories.database import Database
from cara.services.admin import AdminService
from cara.services.annotation import AnnotationService
from cara.services.datasets import LEGACY_SET, DatasetService
from cara.services.pipeline import PipelineService
from cara.services.simulator import SettingResult, SimulatorService, Source, parse_qrels
from cara.services.users import UserService
from cara.settings import StudySettings

logger = logging.getLogger(__name__)


def _password(given: str | None) -> str:
    return given if given is not None else getpass.getpass("Password: ")


def print_results(results: list[SettingResult]) -> None:
    """Log the simulator's results as a table, for the first annotator type."""

    def show(value: float | None, digits: int = 2) -> str:
        return "-" if value is None else f"{value:.{digits}f}"

    columns = ["groups", "min act", "actions", "s/img", "recall", "uncorr."]
    logger.info(f"  {'setting':<52}" + "".join(f"{c:>8}" for c in columns))
    for result in results:
        typical = result.annotators[0]
        mark = "*" if typical.best_tradeoff else "c" if result.is_current else " "
        logger.info(
            f"{mark} {result.strategy:<52}{result.groups_per_pool:>8.1f}{result.min_actions_pc:>8.2f}"
            f"{show(result.actions_pc):>8}{show(typical.seconds_pc):>8}{show(typical.recall):>8}"
            f"{show(result.recall_uncorrected):>8}"
        )
    logger.info("* best trade-off (fastest within 2 points of recall)   c current   values per image")


def main() -> None:
    """Run one `cara` command in one transaction: everything it changes is saved, or nothing is.

    `encode` imports the encoders only when it runs: they need torch, an optional extra.
    """
    parser = argparse.ArgumentParser(prog="cara", description="Set up CARA studies and users.")
    commands = parser.add_subparsers(dest="command", required=True)

    user_add = commands.add_parser("user-add", help="create a user")
    user_add.add_argument("username")
    user_add.add_argument("--password", help="prompted for when omitted")
    user_add.add_argument("--superuser", action="store_true")

    dataset_add = commands.add_parser(
        "dataset-add", help="register a dataset folder (images, queries, embeddings)"
    )
    dataset_add.add_argument("folder", type=Path)
    dataset_add.add_argument("--name", help="default: dataset.yaml's name, else the folder name")
    dataset_add.add_argument(
        "--path", help="image folder relative to CARA_IMAGE_ROOT (default: the folder name)"
    )
    dataset_add.add_argument("--encoder", help="the encoder that made embeddings.npz, if the folder has one")

    commands.add_parser("datasets", help="list datasets: images, query sets, encoders")

    encode_parser = commands.add_parser(
        "encode", help="embed a dataset's images and text queries (needs the encode extra; use a GPU)"
    )
    encode_parser.add_argument("dataset", help="dataset name")
    encode_parser.add_argument("--encoder", required=True, help="e.g. dinov3-7b, siglip2")
    encode_parser.add_argument("--batch-size", type=int, default=64)
    encode_parser.add_argument("--num-workers", type=int, default=4)

    study_create = commands.add_parser("study-create", help="create a study on a dataset from cara.yaml")
    study_create.add_argument("settings", type=Path, help="cara.yaml")
    study_create.add_argument("--dataset", required=True, help="dataset name")
    study_create.add_argument("--query-set", default=LEGACY_SET)
    study_create.add_argument("--queries", type=int, help="random sample of this many queries (default: all)")
    study_create.add_argument("--seed", type=int, default=0)
    study_create.add_argument("--member", action="append", default=[], help="annotator to add; repeat")

    member = commands.add_parser("member", help="add a user to a study or change their role")
    member.add_argument("study_id", type=int)
    member.add_argument("username")
    member.add_argument("--role", type=Role, choices=list(Role), default=Role.ANNOTATOR)

    pilot = commands.add_parser("pilot", help="pick pilot queries, judged one image at a time")
    pilot.add_argument("study_id", type=int)
    pilot.add_argument("--count", type=int, required=True)
    pilot.add_argument("--seed", type=int, default=0)
    pilot.add_argument("--labels", type=Path, help="qrels: draw the pilot from its queries and judge them")
    pilot.add_argument("--annotator", help="the user who records the --labels judgments (a study member)")
    pilot.add_argument(
        "--then",
        nargs="+",
        default=[],
        help="annotators of the real study: they get every query but the pilot ones (kept by --annotator)",
    )

    judge = commands.add_parser("judge", help="record a user's judgments from qrels, e.g. for a demo")
    judge.add_argument("study_id", type=int)
    judge.add_argument("--labels", type=Path, required=True, help="qrels with the labels to record")
    judge.add_argument("--annotator", required=True, help="the user who records them (a study member)")
    judge.add_argument("--first", type=int, default=1, help="how many queries, from the top of their queue")

    simulate = commands.add_parser("simulate", help="compare grouping settings before judging starts")
    simulate.add_argument("study_id", type=int)
    labels = simulate.add_mutually_exclusive_group()
    labels.add_argument("--qrels", type=Path, help="existing relevance labels (TREC qrels)")
    labels.add_argument("--pilot", action="store_true", help="use the judged pilot queries as labels")
    simulate.add_argument("--max-queries", type=int, default=30)

    for name, help_text in [("build-pools", "kNN or whole-corpus pools"), ("cluster", "group every pool")]:
        commands.add_parser(name, help=help_text).add_argument("study_id", type=int)

    load = commands.add_parser(
        "load", help="dataset and study from one folder (cara.yaml, queries.jsonl, embeddings.npz)"
    )
    load.add_argument("folder", type=Path)
    load.add_argument(
        "--image-dir", help="image folder relative to CARA_IMAGE_ROOT (default: the folder name)"
    )
    load.add_argument("--member", action="append", default=[], help="annotator to add; repeat for several")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sessions = make_sessions(os.environ["CARA_DATABASE_URL"])
    with sessions.begin() as session:
        db = Database(session)
        users, datasets, pipeline = UserService(db), DatasetService(db), PipelineService(db)
        match args.command:
            case "user-add":
                users.add(args.username, _password(args.password), args.superuser)
                logger.info("added user %s", args.username)
            case "dataset-add":
                datasets.add_folder(args.folder, args.name, args.path, args.encoder)
            case "datasets":
                for summary in datasets.summaries():
                    sets = ", ".join(f"{name} ({n})" for name, n in summary.query_sets.items())
                    encoders = ", ".join(summary.encoders) or "none: run cara encode"
                    logger.info(
                        "%s: %d images; query sets %s; encoders %s",
                        summary.name,
                        summary.images,
                        sets,
                        encoders,
                    )
            case "encode":
                from cara.services.embedding import EncodingService

                dataset = datasets.named(args.dataset)
                encoding = EncodingService(db, Path(os.environ["CARA_IMAGE_ROOT"]))
                done = encoding.encode(dataset.id, args.encoder, args.batch_size, args.num_workers)
                logger.info("encoded %d images and %d text queries", done.images, done.text_queries)
            case "study-create":
                dataset = datasets.named(args.dataset)
                settings = StudySettings.from_yaml(args.settings)
                pipeline.setup_study(
                    settings, dataset.id, args.query_set, args.queries, args.seed, args.member
                )
            case "member":
                users.set_role(args.study_id, args.username, args.role)
                logger.info("%s is %s of study %d", args.username, args.role, args.study_id)
            case "build-pools":
                pipeline.build_pools(args.study_id)
            case "cluster":
                pipeline.cluster(args.study_id)
            case "pilot":
                if args.labels and not args.annotator:
                    parser.error("--labels needs --annotator")
                positives = parse_qrels(args.labels.read_text()) if args.labels else None
                among = set(positives) if positives else None
                chosen = pipeline.set_pilot(args.study_id, args.count, args.seed, among)
                logger.info("pilot queries: %s", ", ".join(chosen))
                if positives is not None:
                    user = users.get(args.annotator)
                    AdminService(db).assign_pilot(args.study_id, [args.annotator], 1)
                    every = db.studies.list_pools(args.study_id)
                    pilot_ids = {pool.query_id for pool in every if pool.query.is_pilot}
                    count = AnnotationService(db).judge_from_labels(user, args.study_id, positives, pilot_ids)
                    logger.info("%s judged %d pilot images", args.annotator, count)
                if args.then:
                    counts = AdminService(db).assign(args.study_id, 1, args.then)
                    logger.info("assigned queries: %s", counts)
            case "judge":
                user = users.get(args.annotator)
                annotation = AnnotationService(db)
                first = annotation.queue(user, args.study_id)[: args.first]
                positives = parse_qrels(args.labels.read_text())
                ids = {item.query_id for item in first}
                count = annotation.judge_from_labels(user, args.study_id, positives, ids)
                logger.info("%s judged %d images of %d queries", args.annotator, count, len(first))
            case "simulate":
                source: Source = "qrels" if args.qrels else "pilot" if args.pilot else "none"
                qrels = args.qrels.read_text() if args.qrels else None
                print_results(SimulatorService(db).simulate(args.study_id, source, qrels, args.max_queries))
            case "load":
                pipeline.load_folder(args.folder, args.image_dir or args.folder.name, args.member)
