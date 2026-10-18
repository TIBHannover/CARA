"""What a study's admins do; and accounts, for superusers.

The pilot, pools and groups, the simulator, progress, agreement, adjudication, exports, members and
assignments.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from cara.api.auth import CurrentUserDep, require_admin, require_superuser
from cara.api.deps import AdminDep, AppSettingsDep, PipelineDep, SimulatorDep, UsersDep
from cara.api.schemas import AdjudicateIn, AssignIn, MemberIn, PilotIn, PilotOut, SimulatorIn, UserIn
from cara.errors import Invalid
from cara.repositories.database import Database
from cara.services.admin import AgreementReport, DisagreementItem, Export, Member, ProgressRow
from cara.services.simulator import PilotReport, Scope, SettingResult, SimulatorEvent, SimulatorService

router = APIRouter(prefix="/studies/{study_id}", tags=["admin"], dependencies=[Depends(require_admin)])
accounts = APIRouter(prefix="/users", tags=["admin"], dependencies=[Depends(require_superuser)])


@router.put("/pilot")
def set_pilot(study_id: int, body: PilotIn, admin: AdminDep, pipeline: PipelineDep) -> PilotOut:
    """Choose `count` random pilot queries (unless None) and assign them to `annotators`.

    409 once annotation has started: from then on the pilot stays as it is.
    """
    admin.ensure_pilot_open(study_id)
    if body.count is not None:
        pipeline.set_pilot(study_id, body.count, body.seed)
    assigned = admin.assign_pilot(study_id, body.annotators, body.per_query) if body.annotators else {}
    return PilotOut(queries=pipeline.pilot_queries(study_id), assigned=assigned)


@router.post("/pools", status_code=204)
def build_pools(study_id: int, pipeline: PipelineDep) -> None:
    """Rebuild and regroup every pool; 409 once judging has started."""
    pipeline.build_pools(study_id)
    pipeline.cluster(study_id)


@router.post("/groups", status_code=204)
def regroup(study_id: int, pipeline: PipelineDep) -> None:
    """Regroup every pool with the study's grouping settings; 409 once judging has started."""
    pipeline.cluster(study_id)


@router.post("/simulator")
def simulate(study_id: int, body: SimulatorIn, simulator: SimulatorDep) -> list[SettingResult]:
    """Run the settings simulator to the end and return its results."""
    return simulator.simulate(
        study_id, body.source, body.qrels, body.max_queries, body.plan, pilot_users=body.pilot_users
    )


@router.get("/pilot/report")
def pilot_report(study_id: int, simulator: SimulatorDep) -> PilotReport:
    """Report how each pilot annotator worked, and alpha over the pilot.

    Per annotator: queries and images judged, seconds per image, corrections, label shares, kappa with the
    others and accuracy against their majority label.
    """
    return simulator.pilot_report(study_id)


@router.get("/simulator/scope")
def simulator_scope(
    study_id: int,
    simulator: SimulatorDep,
    pilot_users: Annotated[list[str] | None, Query()] = None,
) -> Scope:
    """Return what the simulator can work with in the study.

    Queries and images it can sample, the pilot queries with complete labels (from `pilot_users`, default
    everyone), and each pilot annotator's agreement with the others.
    """
    return simulator.scope(study_id, pilot_users)


@router.get("/simulator/sample-qrels", response_class=PlainTextResponse)
def sample_qrels(study_id: int, simulator: SimulatorDep, settings: AppSettingsDep) -> str:
    """Example labels shipped with the study's dataset, to try the simulator without your own qrels."""
    return simulator.sample_qrels(settings.image_root, study_id)


@router.post("/simulator/stream")
def simulate_stream(study_id: int, body: SimulatorIn, request: Request) -> Iterator[SimulatorEvent]:
    """The simulation as JSON Lines: one progress event per step, the last one with the results.

    The request's own transaction closes when this function returns, before streaming starts, so the run opens
    its own. An error after the stream has started arrives as an event with step "error".
    """
    with request.app.state.sessions.begin() as session:
        try:
            yield from SimulatorService(Database(session)).simulate_steps(
                study_id, body.source, body.qrels, body.max_queries, body.plan, pilot_users=body.pilot_users
            )
        except Invalid as error:
            yield SimulatorEvent("error", "Stopped", 0, 1, str(error))


@router.get("/admin/progress")
def progress(study_id: int, admin: AdminDep) -> list[ProgressRow]:
    """Return each member's progress."""
    return admin.progress(study_id)


@router.get("/admin/agreement")
def agreement(study_id: int, admin: AdminDep) -> AgreementReport:
    """Return the study's agreement: overall, per pair of annotators, and per query."""
    return admin.agreement(study_id)


@router.get("/admin/disagreements/{query_id}")
def disagreements(study_id: int, query_id: int, admin: AdminDep) -> list[DisagreementItem]:
    """Return the images of a query the annotators disagree on."""
    return admin.disagreement_items(study_id, query_id)


@router.put("/admin/adjudications", status_code=204)
def adjudicate(study_id: int, body: AdjudicateIn, user: CurrentUserDep, admin: AdminDep) -> None:
    """Set an image's final label, which overrides the majority in the consensus qrels."""
    admin.adjudicate(study_id, user, body.member_id, body.label)


@router.get("/admin/exports/{name}", response_class=PlainTextResponse)
def export(
    study_id: int, name: Export, admin: AdminDep, username: Annotated[str | None, Query()] = None
) -> str:
    """Return an export: an annotator's qrels (needs `username`), consensus qrels, pairs or actions."""
    return admin.export(study_id, name, username)


@router.get("/members")
def members(study_id: int, admin: AdminDep) -> list[Member]:
    """Return the study's members with their roles and assigned queries."""
    return admin.members(study_id)


@router.put("/members", status_code=204)
def set_member(study_id: int, body: MemberIn, users: UsersDep) -> None:
    """Add someone to the study with a role, or change their role."""
    users.set_role(study_id, body.username, body.role)


@router.put("/assignments")
def assign(study_id: int, body: AssignIn, admin: AdminDep) -> dict[str, int]:
    """Assign the annotation queries, which starts annotation; returns each annotator's number of queries."""
    return admin.assign(study_id, body.per_query, body.annotators)


@accounts.get("")
def list_users(users: UsersDep) -> list[str]:
    """Return every username."""
    return users.usernames()


@accounts.post("", status_code=204)
def create_user(body: UserIn, user: CurrentUserDep, users: UsersDep) -> None:
    """Create an account."""
    users.create_account(user, body.username, body.password)
